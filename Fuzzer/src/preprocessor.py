import os
import subprocess
from dut_profile import profile

from ISASim.host import isaInput
from RTLSim.host import rtlInput
from mutator import simInput, templates, V_U

class rvPreProcessor():
    def __init__(self, cc, elf2hex, template='Template', out_base ='.', proc_num=0,
                 march='rv64g', mabi='lp64', xlen=64, ram_base=0x80000000,
                 ram_size=0x00200000,
                 data_sections=6, max_cycles=None,
                 boot_offset=0, tohost=None):
        self.template = template
        self.base = out_base
        self.proc_num = proc_num

        self.er_num = 0
        self.xlen = xlen
        self.data_sections = data_sections
        self.max_cycles = max_cycles
        linker_script = os.path.join(out_base, '.link.ld')
        with open('{}/include/link.ld'.format(template), encoding='utf-8') as source:
            with open(linker_script, 'w', encoding='utf-8') as target:
                target.write(source.read())
        self.cc_args = [ cc, '-march=' + march, '-mabi=' + mabi, '-static', '-mcmodel=medany',
                         '-fvisibility=hidden', '-nostdlib', '-nostartfiles',
                         '-Wl,--defsym=__dut_ram_base=0x{:x}'.format(ram_base),
                         '-Wl,--defsym=__dut_ram_size=0x{:x}'.format(ram_size),
                         '-Wl,--defsym=__dut_boot_offset=0x{:x}'.format(boot_offset),
                         '-Wl,--defsym=__dut_tohost=0x{:x}'.format(
                             tohost if tohost is not None else int(os.environ['DUT_TOHOST'], 0)),
                         '-I', '{}/include'.format(template),
                         '-T', linker_script ]

        self.elf2hex_args = [ elf2hex, '--bit-width', str(xlen), '--input' ]

    def get_symbols(self, elf_name, sym_name):
        with open(sym_name, 'w') as stream:
            subprocess.run(['nm', elf_name], stdout=stream, check=True)
        with open(sym_name) as stream:
            return {fields[2]: int(fields[0], 16) for line in stream
                    if len(fields := line.split()) == 3}

    def write_isa_intr(self, isa_input, rtl_input, epc):
        fd = open(rtl_input.intrfile, 'r')
        tuples = [ line.split(':') for line in fd.readlines() ]
        fd.close()

        # TODO, assert interrupt multiple time
        assert len(tuples) == 1, 'Interrupt must be asserted only one time'
        val = int(tuples[0][1], 2)

        fd = open(isa_input.intrfile, 'w')
        fd.write('{:016x}:{:04b}\n'.format(epc, val))
        fd.close()

    def process(self, sim_input: simInput, data: list, intr: bool, num_data_sections=None):
        if num_data_sections is None:
            num_data_sections = self.data_sections
        section_size = len(data) // num_data_sections

        assert data, 'Empty data can not be processed'
        assert (section_size & (section_size - 1)) == 0, \
            'Number of memory blocks should be power of 2'

        version = sim_input.get_template()
        test_template = profile().get('template')
        if not test_template:
            if self.xlen == 32:
                raise ValueError('RV32 requires a DUT template via FUZZER_CONFIG or DUT_NAME')
            test_template = self.template + '/rv{}-{}.S'.format(self.xlen, templates[version])

        interrupt_args = ['-DINTERRUPT'] if intr else []
        extra_args = interrupt_args + [ '-I', '{}/include/p'.format(self.template) ]
        if version == V_U:
            rand = data[0] & 0xffffffff
            extra_args = interrupt_args + [ '-DENTROPY=0x{:08x}'.format(rand), '-std=gnu99', '-O2',
                                   '-I', '{}/include/v'.format(self.template),
                                   '{}/include/v/string.c'.format(self.template),
                                   '{}/include/v/vm.c'.format(self.template) ]

        si_name = self.base + '/.input_{}.si'.format(self.proc_num)
        asm_name = self.base + '/.input_{}.S'.format(self.proc_num)
        elf_name = self.base + '/.input_{}.elf'.format(self.proc_num)
        hex_name = self.base + '/.input_{}.hex'.format(self.proc_num)
        sym_name = self.base + '/.input_{}.symbols'.format(self.proc_num)
        rtl_intr_name = self.base + '/.input_{}.rtl.intr'.format(self.proc_num)
        isa_intr_name = self.base + '/.input_{}.isa.intr'.format(self.proc_num)

        prefix_insts = sim_input.get_prefix()
        insts = sim_input.get_insts()
        suffix_insts = sim_input.get_suffix()
        sim_input_ints = sim_input.ints.copy()

        ints = []
        for inst in insts[:-1]:
            INT = sim_input_ints.pop(0)
            if 'la' in inst:
                ints.append(INT)
                ints.append(0)
            else:
                ints.append(INT)

        sim_input.save(si_name, data)

        with open(test_template) as stream:
            template_lines = stream.readlines()

        assembly = []
        step = 2 if self.xlen == 64 else 1
        directive = '.dword' if self.xlen == 64 else '.word'
        mask = (1 << self.xlen) - 1
        for line in template_lines:
            assembly.append(line)
            if '_fuzz_prefix:' in line:
                for inst in prefix_insts:
                    assembly.append(inst + ';\n')

            if '_fuzz_main:' in line:
                for inst in insts:
                    assembly.append(inst + ';\n')

            if '_fuzz_suffix:' in line:
                for inst in suffix_insts:
                    assembly.append(inst + ';\n')

            for n in range(num_data_sections):
                start = n * section_size
                end = start + section_size
                if '_random_data{}'.format(n) in line:
                    k = 0
                    for i in range(start, end, step):
                        label = ''
                        if i >= start + step * 4 and i < end - step * 4:
                            label = 'd_{}_{}:'.format(n, k)
                            k += 1

                        values = data[i:i + step]
                        assembly.append('{:<16}{} {}\n'.format(
                            label, directive, ', '.join(
                                '0x{:0{}x}'.format(value & mask, self.xlen // 4)
                                for value in values)))

        with open(asm_name, 'w') as stream:
            stream.writelines(assembly)

        cc_args = self.cc_args + extra_args + [ asm_name, '-o', elf_name ]

        while True:
            cc_ret = subprocess.call(cc_args)
            # if cc_ret == -9: cc process is killed by OS due to memory usage
            if cc_ret != -9: break

        if cc_ret == 0:
            elf2hex_args = self.elf2hex_args + [elf_name, '--output', hex_name]
            if subprocess.call(elf2hex_args) != 0:
                return None, None, None
            symbols = self.get_symbols(elf_name, sym_name)
            if self.xlen == 32:
                symbols['_signature_format'] = 'rv32'

            if intr:
                fuzz_main = symbols['_fuzz_main']
                fd = open(rtl_intr_name, 'w')
                for i, INT in enumerate(ints):
                    if INT:
                        fd.write('{:016x}:{:04b}\n'.format(fuzz_main + 4 * i, INT))
                fd.close()

            max_cycles = self.max_cycles or (6000 if version != V_U else 200000)

            isa_input = isaInput(elf_name, isa_intr_name)
            rtl_input = rtlInput(hex_name, rtl_intr_name, data, symbols, max_cycles)
        else:
            isa_input = None
            rtl_input = None
            symbols = None

        return (isa_input, rtl_input, symbols)
