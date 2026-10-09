import os
import json
import shutil

from ISASim.host import rvISAhost
from RTLSim.host import rvRTLhost

from src.preprocessor import rvPreProcessor
from src.signature_checker import sigChecker
from src.mutator import simInput, rvMutator
from src.multicore_manager import proc_state, procManager

def save_err(out: str, proc_num: int, manager: procManager, stop_code: int):

    if stop_code == proc_state.NORMAL:
        return

    status = proc_state.tpe[stop_code]

    manager.P('state')
    fd = open(out + '/fuzz_log', 'a')
    fd.write('[DifuzzRTL] Thread {}: {} occurred\n'.format(proc_num, status))
    fd.close()

    if not os.path.isdir(out + '/err'):
        os.makedirs(out + '/err')
    manager.V('state')

    shutil.copyfile(out + '/.input_{}.si'.format(proc_num),
                    out + '/err/err_{}_{}.si'.format(status, proc_num))


def run_isa_test(isaHost, isa_input, stop, out, proc_num, assert_intr=False):
    isa_ret = isaHost.run_test(isa_input, assert_intr)
    if isa_ret == 124:
        destination = out + '/isa_timeout'
        os.makedirs(destination, exist_ok=True)
        for extension in ('elf', 'S'):
            shutil.copy(out + '/.input_{}.{}'.format(proc_num, extension),
                        destination + '/timeout.' + extension)
        stop[0] = proc_state.NORMAL
        return proc_state.ERR_ISA_TIMEOUT
    if isa_ret != 0:
        stop[0] = proc_state.ERR_ISA_ASSERT
        return proc_state.ERR_ISA_ASSERT
    stop[0] = proc_state.NORMAL
    return proc_state.NORMAL


def debug_print(message, debug, highlight=False):
    if highlight:
        print('\x1b[1;31m' + message + '\x1b[1;m')
    elif debug:
        print(message)

def save_file(file_name, mode, line):
    fd = open(file_name, mode)
    fd.write(line)
    fd.close()

def save_mismatch(base, proc_num, out, sim_input: simInput, data: list, num,
                  signatures=None):
    for directory in ('sim_input', 'elf', 'asm', 'hex'):
        os.makedirs(os.path.join(out, directory), exist_ok=True)
    if signatures:
        os.makedirs(out + '/signature', exist_ok=True)
    sim_input.save(out + '/sim_input/id_{}.si'.format(num), data)

    elf = base + '/.input_{}.elf'.format(proc_num)
    asm = base + '/.input_{}.S'.format(proc_num)
    hexfile = base + '/.input_{}.hex'.format(proc_num)

    shutil.copy(elf, out + '/elf/id_{}.elf'.format(num))
    shutil.copy(asm, out + '/asm/id_{}.S'.format(num))
    shutil.copy(hexfile, out + '/hex/id_{}.hex'.format(num))
    if signatures:
        for label, path in signatures.items():
            shutil.copy(path, out + '/signature/id_{}_{}.txt'.format(num, label))

def setup(dut, toplevel, template, out, proc_num, debug, minimizing=False,
          no_guide=False, isa='RV64G', xlen=64,
          march='rv64g', mabi='lp64', data_sections=6,
          data_words_per_section=64, max_cycles=None,
          feedback_kind='reg'):
    ibex = toplevel == 'Ibex'
    mutator = rvMutator(no_guide=no_guide, isa=isa,
                        template_max=2 if xlen == 32 else 3,
                        data_sections=data_sections,
                        data_words_per_section=data_words_per_section)

    cc = 'riscv64-unknown-elf-gcc'
    elf2hex = os.environ.get('ELF2HEX', 'riscv64-unknown-elf-elf2hex')
    preprocessor = rvPreProcessor(
        cc, elf2hex, template, out, proc_num, march=march, mabi=mabi,
        xlen=xlen, data_sections=data_sections,
        ram_base=int(os.environ['DUT_RAM_BASE'], 0),
        ram_size=int(os.environ['DUT_RAM_SIZE'], 0),
        max_cycles=max_cycles,
        boot_offset=int(os.environ['DUT_BOOT_OFFSET'], 0),
        tohost=int(os.environ['DUT_TOHOST'], 0))

    spike = os.environ['SPIKE']
    isa_sigfile = out + '/.isa_sig_{}.txt'.format(proc_num)
    rtl_sigfile = out + '/.rtl_sig_{}.txt'.format(proc_num)

    spike_arg = ['--isa={}'.format(isa),
                 '--priv={}'.format(os.environ.get('SPIKE_PRIVILEGE', 'm')),
                 '-m{}'.format(os.environ.get('SPIKE_MEMORY', '0x80000000:0x02000000'))]
    if toplevel in ('Ibex', 'picorv32_verif_top', 'cva6'):
        spike_arg.extend([
            '--pmpregions={}'.format(os.environ['SPIKE_PMP_REGIONS']),
            '--pmpgranularity={}'.format(os.environ['SPIKE_PMP_GRANULARITY'])])
    if ibex or toplevel == 'cva6':
        spike_arg.append('--dtb={}'.format(os.environ['SPIKE_DTB']))
    if ibex:
        spike_arg.extend([
            '--extlib={}'.format(os.environ['SPIKE_DEVICE_PLUGIN']),
            '--device=ibex_clint,{}'.format(os.environ['SPIKE_CLINT_ARGS'])])
    spike_arg.extend(json.loads(os.environ.get('SPIKE_EXTRA_ARGS', '[]')))
    if debug:
        spike_arg.append('-l')

    isaHost = rvISAhost(spike, spike_arg, isa_sigfile)
    host = os.environ.get('DUT_HOST', {'Ibex': 'ibex',
        'cva6': 'cva6', 'picorv32_verif_top': 'picorv32'}.get(toplevel))
    if host == 'ibex':
        from RTLSim.ibex_host import IbexRTLHost
        rtlHost = IbexRTLHost(dut, rtl_sigfile, feedback=feedback_kind, debug=debug)
    elif host == 'cva6':
        from RTLSim.cva6_host import Cva6RTLHost
        rtlHost = Cva6RTLHost(dut, rtl_sigfile, feedback=feedback_kind, debug=debug)
    elif host == 'picorv32':
        from RTLSim.picorv32_host import PicoRV32RTLHost
        rtlHost = PicoRV32RTLHost(dut, rtl_sigfile, feedback=feedback_kind, debug=debug)
    else:
        rtlHost = rvRTLhost(dut, toplevel, rtl_sigfile, debug=debug)

    checker = sigChecker(isa_sigfile, rtl_sigfile, debug, minimizing)

    return (mutator, preprocessor, isaHost, rtlHost, checker)
