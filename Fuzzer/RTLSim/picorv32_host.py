"""picorv32 memory, reset, halt and coverage adapter for the Hcover testbench."""
import os
import cocotb
from cocotb.decorators import coroutine
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from RTLSim.host import ILL_MEM, SUCCESS, TIME_OUT, rtlInput

class PicoRV32RTLHost:
    """Own PicoRV32's 32-bit RAM and granted data-bus halt protocol."""

    def __init__(self, dut, signature_file, feedback='reg', debug=False):
        self.dut = dut
        self.signature_file = signature_file
        self.feedback = feedback
        self.debug = debug
        self.ram_base = int(os.environ.get('DUT_RAM_BASE', '0x00002000'), 0)
        self.ram_size = int(os.environ.get('DUT_RAM_SIZE', '0x001fe000'), 0)
        self.tohost = int(os.environ.get('DUT_TOHOST', '0x001ff008'), 0)
        self.sim_ctrl_base = int(os.environ.get('DUT_SIM_CTRL_BASE', '0x001ff000'), 0)
        self.sim_ctrl_size = int(os.environ.get('DUT_SIM_CTRL_SIZE', '0x1000'), 0)
        self.timer_base = int(os.environ.get('DUT_TIMER_BASE', '0x10001000'), 0)
        self.timer_size = int(os.environ.get('DUT_TIMER_SIZE', '0x10'), 0)
        self.xlen = int(os.environ.get('XLEN', '32'))
        self.ram = dut.ram
        self.ram_words = len(self.ram)
        self.last_covsum = {
            'reg': 0, 'branch': 0, 'path': 0, 'stmt': 0, 'toggle': 0,
        }
        self.covsum = 0
        self.halted = False
        self.illegal_mem = False
        self.trace = os.environ.get('DUT_TRACE', '') == '1'
        self.trace_writes = 0
        self.trace_cycles = 0
        self.loaded_slots = set()

    def _signal(self, name):
        return getattr(self.dut, name, None)

    def _read_word(self, addr):
        if addr < self.ram_base or addr >= self.ram_base + self.ram_size:
            return 0
        index = (addr - self.ram_base) // 4
        if index < 0 or index >= self.ram_words:
            return 0
        return int(self.ram[index].value)

    def _load_image(self, image, address):
        word_bytes = 4
        index = (address - self.ram_base) // word_bytes
        if index < 0:
            raise ValueError('image starts below configured RAM')
        with open(image, 'rb') as stream:
            raw_values = [int(line, 16) for line in stream.read().splitlines()]
        pending = {index + offset: value
                   for offset, value in enumerate(raw_values) if value}
        # Clear words written by the previous input, including its signature.
        for slot in self.loaded_slots - pending.keys():
            pending[slot] = 0
        self.loaded_slots = {slot for slot, value in pending.items() if value}
        for slot, value in pending.items():
            if slot >= self.ram_words:
                raise ValueError('image exceeds configured RAM')
            self.ram[slot].value = value
            if self.trace and slot == index:
                print('[DUT_TRACE] load slot={} value=0x{:016x} readback=0x{:016x}'.format(slot, value, int(self.ram[slot].value)), flush=True)

    def _cov(self, kind):
        names = {
            'reg': 'pcov_reg_covsum',
            'branch': 'pcov_code_branch_covsum',
            'path': 'pcov_code_path_covsum',
            'stmt': 'pcov_code_stmt_covsum',
            'toggle': 'pcov_code_toggle_covsum',
        }
        signal = self._signal(names.get(kind, 'pcov_reg_covsum'))
        if signal is None:
            signal = self._signal('pcov_code_covsum')
        return int(signal.value) if signal is not None else 0

    def _get_feedback_covsum(self):
        value = self._cov(self.feedback)
        self.last_covsum[self.feedback] = max(self.last_covsum[self.feedback], value)
        return self.last_covsum[self.feedback]

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
        # Measure the same register coverage for every feedback strategy.
        return self._cov('reg')

    def feedback_coverage(self):
        return self._get_feedback_covsum()

    def _save_signature(self, symbols):
        start, end = (symbols['begin_signature'], symbols['end_signature'])
        word_bytes = 4
        values = [self._read_word(addr) for addr in range(start, end, word_bytes)]
        with open(self.signature_file, 'w', encoding='utf-8') as stream:
            for offset in range(0, len(values), 4):
                block = b''.join((value & 0xffffffff).to_bytes(4, 'little')
                                 for value in values[offset:offset + 4])
                stream.write(block[::-1].hex() + '\n')

    @coroutine
    def _clock(self):
        while True:
            self.dut.clk <= 0
            yield Timer(5)
            self.dut.clk <= 1
            yield Timer(5)

    def _mapped_data_address(self, addr):
        return (self.ram_base <= addr < self.ram_base + self.ram_size or
                self.sim_ctrl_base <= addr < self.sim_ctrl_base + self.sim_ctrl_size or
                self.timer_base <= addr < self.timer_base + self.timer_size)

    @coroutine
    def _watch(self):
        while not self.halted and not self.illegal_mem:
            yield FallingEdge(self.dut.clk)
            self.trace_cycles += 1
            valid = int(self.dut.data_req.value) and int(self.dut.data_gnt.value)
            if self.trace and self.trace_cycles <= 120 and int(self.dut.instr_req.value):
                print('[DUT_TRACE] cycle={} data_req={} instr_req={} addr=0x{:08x} rst={}'.format(self.trace_cycles, int(self.dut.data_req.value), int(self.dut.instr_req.value), int(self.dut.data_addr.value), int(self.dut.rst.value)), flush=True)
            # PicoRV32 shares mem_addr (exposed as data_addr) for fetch and data.
            addr = int(self.dut.data_addr.value)
            fetch = int(self.dut.instr_req.value) and int(self.dut.instr_gnt.value)
            if ((valid and not self._mapped_data_address(addr)) or
                    (fetch and not self.ram_base <= addr < self.ram_base + self.ram_size)):
                if os.environ.get("ILL_MEM_AUDIT") == "1":
                    print("[ILL_MEM_AUDIT] address={} cycle={}".format(
                        hex(addr),
                        self.trace_cycles), flush=True)
                self.illegal_mem = True
                return
            if valid:
                if int(self.dut.data_we.value) and addr == self.tohost and int(self.dut.data_wdata.value) & 1:
                    self.halted = True
                    if self.trace:
                        print('[DUT_TRACE] halt addr=0x{:08x} data=0x{:08x} cycle={}'.format(addr, int(self.dut.data_wdata.value), self.trace_cycles), flush=True)
                elif int(self.dut.data_we.value) and self.trace and (self.trace_writes < 20):
                    print('[DUT_TRACE] write addr=0x{:08x} data=0x{:08x} cycle={}'.format(addr, int(self.dut.data_wdata.value), self.trace_cycles), flush=True)
                    self.trace_writes += 1

    @coroutine
    def run_test(self, rtl_input: rtlInput, assert_intr=False):
        del assert_intr
        self.halted = False
        self.illegal_mem = False
        reset = self.dut.rst
        self.dut.clk <= 0
        reset <= 1
        clock = cocotb.fork(self._clock())
        edge = RisingEdge(self.dut.clk)
        yield edge
        # The first edge follows the testbench's time-zero RAM initialization.
        image_base = int(os.environ.get(
            'DUT_IMAGE_BASE', str(rtl_input.symbols['_start'])), 0)
        self._load_image(rtl_input.hexfile, image_base)
        ram_word_bytes = 4
        self.loaded_slots.update(range(
            (rtl_input.symbols['begin_signature'] - self.ram_base) // ram_word_bytes,
            (rtl_input.symbols['end_signature'] - self.ram_base + ram_word_bytes - 1)
            // ram_word_bytes))
        if self.trace:
            print('[DUT_TRACE] image start=0x{:016x} word0=0x{:016x} ram_words={}'.format(rtl_input.symbols['_start'], self._read_word(rtl_input.symbols['_start']), self.ram_words), flush=True)
        reset_cycles = 5
        for _ in range(reset_cycles - 1):
            yield edge
        reset <= 0
        watcher = cocotb.fork(self._watch())
        for _ in range(rtl_input.max_cycles):
            yield edge
            if self.halted or self.illegal_mem:
                break
        watcher.kill()
        self.covsum = max(self.covsum, self._get_curve_covsum())
        if self.halted:
            yield edge
            self._save_signature(rtl_input.symbols)
        reset <= 1
        for _ in range(3):
            yield edge
        clock.kill()
        if self.illegal_mem:
            if self.trace:
                print('[DUT_TRACE] illegal memory cycle={}'.format(self.trace_cycles), flush=True)
            return ILL_MEM, self.covsum
        if not self.halted:
            if self.trace:
                print('[DUT_TRACE] timeout cycles={}'.format(self.trace_cycles), flush=True)
            return TIME_OUT, self.covsum
        return SUCCESS, self.covsum
