import os

import cocotb
from cocotb.decorators import coroutine
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from RTLSim.host import rtlInput, SUCCESS, TIME_OUT, ILL_MEM


class IbexRTLHost:
    """Minimal RV32 Ibex bus model matching the experiment firmware map."""

    RAM_BASE = 0x00100000
    RAM_WORDS = 524288
    TOHOST = 0x00020008
    SIM_CTRL_BASE = 0x00020000
    SIM_CTRL_LIMIT = 0x00021000
    TIMER_BASE = 0x00030000
    TIMER_LIMIT = 0x00030010

    def __init__(self, dut, signature_file, feedback='reg', debug=False):
        self.dut = dut
        self.signature_file = signature_file
        self.feedback = feedback
        self.debug = debug
        self.ram_base = int(os.environ.get('DUT_RAM_BASE', hex(self.RAM_BASE)), 0)
        self.ram_size = int(os.environ.get(
            'DUT_RAM_SIZE', hex(self.RAM_WORDS * 4)), 0)
        self.ram_words = self.ram_size // 4
        self.sim_ctrl_base = int(os.environ.get(
            'DUT_SIM_CTRL_BASE', hex(self.SIM_CTRL_BASE)), 0)
        self.sim_ctrl_size = int(os.environ.get(
            'DUT_SIM_CTRL_SIZE', hex(self.SIM_CTRL_LIMIT - self.SIM_CTRL_BASE)), 0)
        self.tohost = int(os.environ.get('DUT_TOHOST', hex(self.TOHOST)), 0)
        self.timer_base = int(os.environ.get('DUT_TIMER_BASE', hex(self.TIMER_BASE)), 0)
        self.timer_size = int(os.environ.get(
            'DUT_TIMER_SIZE', hex(self.TIMER_LIMIT - self.TIMER_BASE)), 0)
        self.ram = dut.ram
        self.covsum = 0
        self.last_covsum = {
            'reg': 0, 'branch': 0, 'path': 0, 'stmt': 0, 'toggle': 0,
        }

    def _read_word(self, addr):
        if self.ram_base <= addr < self.ram_base + self.ram_size:
            return int(self.ram[(addr - self.ram_base) >> 2].value)
        return 0

    @coroutine
    def _clock(self):
        while True:
            self.dut.clk <= 0
            yield Timer(5)
            self.dut.clk <= 1
            yield Timer(5)

    def _load_image(self, hexfile, load_address):
        if load_address < self.ram_base or (load_address - self.ram_base) & 3:
            raise ValueError('Ibex image entry is outside or unaligned in RAM')
        start_index = (load_address - self.ram_base) >> 2
        with open(hexfile, 'r') as image:
            for index, line in enumerate(image):
                ram_index = start_index + index
                if ram_index >= self.ram_words:
                    # elf2hex emits the complete RAM depth.  When the ELF
                    # entry has a boot offset, the final offset words are
                    # outside the host array but should be zero padding.
                    if int(line.strip(), 16) != 0:
                        raise ValueError('Ibex image exceeds configured RAM')
                    continue
                self.ram[ram_index].value = int(line.strip(), 16) & 0xffffffff

    def _is_halt_store(self):
        return (int(self.dut.data_req.value) and
                int(self.dut.data_we.value) and
                int(self.dut.data_addr.value) == self.tohost and
                int(self.dut.data_be.value) & 1 and
                int(self.dut.data_wdata.value) & 1)

    def _mapped_data_address(self, addr):
        return (self.ram_base <= addr < self.ram_base + self.ram_size or
                self.sim_ctrl_base <= addr < self.sim_ctrl_base + self.sim_ctrl_size or
                self.timer_base <= addr < self.timer_base + self.timer_size)

    @coroutine
    def _watch_halt(self):
        while not self.halted:
            yield FallingEdge(self.dut.clk)
            if int(self.dut.data_req.value) and int(self.dut.data_gnt.value):
                addr = int(self.dut.data_addr.value)
                if not self._mapped_data_address(addr):
                    if os.environ.get('IBEX_DEBUG') == '1':
                        print('[IbexRTLHost] unmapped data addr={:08x} we={} be={:x} data={:08x}'.format(
                            addr, int(self.dut.data_we.value),
                            int(self.dut.data_be.value),
                            int(self.dut.data_wdata.value)), flush=True)
                    if os.environ.get("ILL_MEM_AUDIT") == "1":
                        print("[ILL_MEM_AUDIT] address={} cycle={}".format(
                            hex(addr),
                            getattr(self, "trace_cycles", 0)), flush=True)
                    self.illegal_mem = True
                    return
            if int(self.dut.instr_req.value) and int(self.dut.instr_gnt.value):
                addr = int(self.dut.instr_addr.value)
                if not (self.ram_base <= addr < self.ram_base + self.ram_size):
                    if os.environ.get('IBEX_DEBUG') == '1':
                        print('[IbexRTLHost] unmapped instruction addr={:08x}'.format(
                            addr), flush=True)
                    if os.environ.get("ILL_MEM_AUDIT") == "1":
                        print("[ILL_MEM_AUDIT] address={} cycle={}".format(
                            hex(addr),
                            getattr(self, "trace_cycles", 0)), flush=True)
                    self.illegal_mem = True
                    return
            if self._is_halt_store():
                self.halted = True
                return

    def _save_signature(self, symbols):
        def write_words(output, values):
            if len(values) % 4:
                raise ValueError('Ibex signatures must contain 16-byte blocks')
            for offset in range(0, len(values), 4):
                block = b''.join((value & 0xffffffff).to_bytes(4, 'little')
                                 for value in values[offset:offset + 4])
                output.write(block[::-1].hex() + '\n')

        with open(self.signature_file, 'w') as output:
            start = symbols['begin_signature']
            end = symbols['end_signature']
            values = [self._read_word(addr) for addr in range(start, end, 4)]
            write_words(output, values)

    @coroutine
    def run_test(self, rtl_input: rtlInput, assert_intr=False):
        if os.path.exists(self.signature_file):
            os.unlink(self.signature_file)
        self.covsum = 0
        self.dut.rst <= 1
        clock = cocotb.fork(self._clock())
        edge = RisingEdge(self.dut.clk)
        # Wait for the testbench time-zero RAM initialization before loading.
        yield edge
        self._load_image(rtl_input.hexfile, int(os.environ.get(
            "DUT_IMAGE_BASE", str(rtl_input.symbols["_start"])), 0))
        for _ in range(3):
            yield edge
        self.halted = False
        self.illegal_mem = False
        halt_monitor = cocotb.fork(self._watch_halt())
        yield FallingEdge(self.dut.clk)
        self.dut.rst <= 0
        yield edge
        # Preserve the feedback map's discovered points across testcases.
        self._get_feedback_covsum()

        self.covsum = self._get_curve_covsum()
        for _ in range(rtl_input.max_cycles):
            yield RisingEdge(self.dut.clk)
            if self.halted or self.illegal_mem:
                break
        halt_monitor.kill()
        self.covsum = max(self.covsum, self._get_curve_covsum())
        self._get_feedback_covsum()
        if self.halted:
            yield edge
            self._save_signature(rtl_input.symbols)
        self.dut.rst <= 1
        for _ in range(4):
            yield edge
        yield Timer(1)
        self.covsum = max(self.covsum, self._get_curve_covsum())
        self._get_feedback_covsum()
        clock.kill()
        if self.illegal_mem:
            return ILL_MEM, self.covsum
        if not self.halted:
            if os.environ.get('IBEX_DEBUG') == '1':
                print('[IbexRTLHost] timeout pc={:08x} req={} gnt={} valid={} data={:08x}'.format(
                    int(self.dut.instr_addr.value),
                    int(self.dut.instr_req.value), int(self.dut.instr_gnt.value),
                    int(self.dut.instr_rvalid.value),
                    int(self.dut.instr_rdata.value)), flush=True)
            return TIME_OUT, self.covsum
        return SUCCESS, self.covsum

    def feedback_coverage(self):
        return self._get_feedback_covsum()

    def _get_regcov(self):
        return self._accumulate_covsum('reg', self.dut.pcov_reg_covsum)

    def _get_code_covsum(self, kind):
        return self._accumulate_covsum(kind, getattr(self.dut, 'pcov_code_{}_covsum'.format(kind)))

    def _accumulate_covsum(self, key, signal):
        self.last_covsum[key] = max(self.last_covsum[key], int(signal.value))
        return self.last_covsum[key]

    def code_coverage_sums(self):
        # Keep each metric's high-water mark across inputs and DUT resets.
        for kind in ('stmt', 'branch', 'path'):
            signal = getattr(self.dut, 'pcov_code_{}_covsum'.format(kind))
            self.last_covsum[kind] = max(self.last_covsum[kind], int(signal.value))
        return tuple(self.last_covsum[kind] for kind in ('stmt', 'branch', 'path'))

    def _get_curve_covsum(self):
        if all(hasattr(self.dut, 'pcov_code_{}_covsum'.format(kind))
               for kind in ('stmt', 'branch', 'path')):
            self.code_coverage_sums()
        self.last_covsum['reg'] = max(
            self.last_covsum['reg'], int(self.dut.pcov_reg_covsum.value))
        return self.last_covsum['reg']

    def _get_feedback_covsum(self):
        if self.feedback == 'none':
            return 0
        if self.feedback in ('branch', 'path', 'stmt', 'toggle'):
            return self._get_code_covsum(self.feedback)
        if self.feedback == 'reg':
            return self._get_regcov()
        raise ValueError('unknown Ibex feedback mode: {}'.format(self.feedback))
