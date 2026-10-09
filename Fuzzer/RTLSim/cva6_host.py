"""cva6 memory, reset, halt and coverage adapter for the Hcover testbench."""
import os
import cocotb
from cocotb.decorators import coroutine
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from RTLSim.host import ILL_MEM, SUCCESS, TIME_OUT, rtlInput

class Cva6RTLHost:
    """Own CVA6's 64-bit AXI RAM and memory-write halt."""

    def __init__(self, dut, signature_file, feedback='reg', debug=False):
        self.dut = dut
        self.signature_file = signature_file
        self.feedback = feedback
        self.debug = debug
        self.ram_base = int(os.environ.get('DUT_RAM_BASE', '0x80000000'), 0)
        self.ram_size = int(os.environ.get('DUT_RAM_SIZE', '0x02000000'), 0)
        self.tohost = int(os.environ.get('DUT_TOHOST', '0x8000f000'), 0)
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
        index = (addr - self.ram_base) // 8
        value = int(self.ram[index].value) if 0 <= index < self.ram_words else 0
        if self.xlen == 32 and addr - self.ram_base & 4:
            return value >> 32 & 0xffffffff
        return value & (0xffffffff if self.xlen == 32 else 0xffffffffffffffff)

    def _load_image(self, image, address):
        word_bytes = 8
        if address < self.ram_base or (address - self.ram_base) % word_bytes:
            raise ValueError('CVA6 image entry is outside or unaligned in RAM')
        index = (address - self.ram_base) // word_bytes
        # Disable the testbench write port while loading RAM through VPI.
        host_we = self._signal('host_mem_we')
        if host_we is not None:
            host_we.value = 0
        with open(image, 'rb') as stream:
            raw_values = [int(line, 16) for line in stream.read().splitlines()]
        if self.xlen == 32:
            values = [
                raw_values[i] | (raw_values[i + 1] if i + 1 < len(raw_values) else 0) << 32
                for i in range(0, len(raw_values), 2)]
        else:
            values = raw_values
        pending = {index + offset: value for offset, value in enumerate(values) if value}
        for slot in self.loaded_slots - pending.keys():
            pending[slot] = 0
        self.loaded_slots = {slot for slot, value in pending.items() if value}
        for slot, value in pending.items():
            if slot >= self.ram_words:
                raise ValueError('image exceeds configured RAM')
            self.ram[slot].value = value

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

    def _get_curve_covsum(self):
        # Measure the same register coverage for every feedback strategy.
        return self._cov('reg')

    def feedback_coverage(self):
        return self._get_feedback_covsum()

    def _save_signature(self, symbols):
        start, end = (symbols['begin_signature'], symbols['end_signature'])
        word_bytes = 4 if self.xlen == 32 else 8
        values = [self._read_word(addr) for addr in range(start, end, word_bytes)]
        with open(self.signature_file, 'w', encoding='utf-8') as stream:
            if word_bytes == 4:
                for offset in range(0, len(values), 4):
                    block = b''.join((value & 0xffffffff).to_bytes(4, 'little')
                                     for value in values[offset:offset + 4])
                    stream.write(block[::-1].hex() + '\n')
            else:
                for offset in range(0, len(values), 2):
                    pair = values[offset:offset + 2]
                    if len(pair) == 1:
                        pair.append(0)
                    stream.write('{:016x}{:016x}\n'.format(pair[1], pair[0]))

    @coroutine
    def _clock(self):
        while True:
            self.dut.clk <= 0
            yield Timer(5)
            self.dut.clk <= 1
            yield Timer(5)

    @coroutine
    def _watch(self):
        while not self.halted and not self.illegal_mem:
            yield FallingEdge(self.dut.clk)
            self.trace_cycles += 1
            # These RAM-controller registers describe accepted AXI transactions,
            # including instruction fetches and each address of a burst.
            for active, address in (('rd_active_q', 'rd_addr_q'),
                                    ('wr_active_q', 'wr_addr_q')):
                if int(getattr(self.dut, active).value):
                    addr = int(getattr(self.dut, address).value)
                    if not self.ram_base <= addr < self.ram_base + self.ram_size:
                        if os.environ.get("ILL_MEM_AUDIT") == "1":
                            print("[ILL_MEM_AUDIT] address={} cycle={}".format(
                                hex(addr),
                                self.trace_cycles), flush=True)
                        self.illegal_mem = True
                        return
            # A final read beat can clear rd_active_q on the same edge that
            # publishes its DECERR. Catch that beat even if the core drops it.
            if int(self.dut.dbg_axi_r_valid.value) and int(self.dut.r_resp_q.value) == 3:
                if os.environ.get("ILL_MEM_AUDIT") == "1":
                    print("[ILL_MEM_AUDIT] address={} cycle={}".format(
                        "DECERR-final-beat",
                        self.trace_cycles), flush=True)
                self.illegal_mem = True
                return
            if self.trace:
                response = self._signal('r_resp_q')
                address = self._signal('rd_addr_q')
                if (response is not None and address is not None and
                        int(self.dut.dbg_axi_r_valid.value) and
                        int(self.dut.dbg_axi_r_ready.value) and int(response.value)):
                    print('[CVA6_AXI_ERROR] cycle={} response={} next_address=0x{:016x}'.format(
                        self.trace_cycles, int(response.value), int(address.value)), flush=True)
            if self.trace and self.trace_cycles <= 30:
                print('[DUT_TRACE] cv cycle={} pc=0x{:08x} ar={}/{} rst={}'.format(self.trace_cycles, int(self.dut.dbg_iq_pc.value), int(self.dut.dbg_axi_ar_valid.value), int(self.dut.dbg_axi_ar_ready.value), int(self.dut.rst.value)), flush=True)
            if self.trace and int(self.dut.dbg_axi_ar_valid.value) and int(self.dut.dbg_axi_ar_ready.value) and (self.trace_cycles < 200):
                print('[DUT_TRACE] ar handshake cycle={}'.format(self.trace_cycles), flush=True)
            valid = int(self.dut.mem_write_valid.value)
            if valid:
                addr = int(self.dut.mem_write_addr.value)
                if not self.ram_base <= addr < self.ram_base + self.ram_size:
                    if os.environ.get("ILL_MEM_AUDIT") == "1":
                        print("[ILL_MEM_AUDIT] address={} cycle={}".format(
                            hex(addr),
                            self.trace_cycles), flush=True)
                    self.illegal_mem = True
                    return
                if (addr == self.tohost and int(self.dut.mem_write_strb.value) & 1
                        and int(self.dut.mem_write_data.value) & 1):
                    self.halted = True
                    if self.trace:
                        print('[DUT_TRACE] halt addr=0x{:016x} cycle={}'.format(addr, self.trace_cycles), flush=True)
                elif self.trace and self.trace_writes < 20:
                    print('[DUT_TRACE] write addr=0x{:016x} data=0x{:016x} cycle={}'.format(addr, int(self.dut.mem_write_data.value), self.trace_cycles), flush=True)
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
        ram_word_bytes = 8
        self.loaded_slots.update(range(
            (rtl_input.symbols['begin_signature'] - self.ram_base) // ram_word_bytes,
            (rtl_input.symbols['end_signature'] - self.ram_base + ram_word_bytes - 1)
            // ram_word_bytes))
        if self.trace:
            print('[DUT_TRACE] image start=0x{:016x} word0=0x{:016x} ram_words={}'.format(rtl_input.symbols['_start'], self._read_word(rtl_input.symbols['_start']), self.ram_words), flush=True)
        # Five reset edges include the initial edge before the RAM deposits.
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
        timeout_state = {}
        if not self.halted:
            for name in ('dbg_iq_pc', 'dbg_commit_pc', 'dbg_csr_mepc', 'dbg_csr_mcause', 'dbg_csr_mtval', 'dbg_csr_mtvec', 'dbg_axi_ar_valid', 'dbg_axi_ar_ready', 'dbg_axi_r_valid', 'dbg_axi_r_ready'):
                signal = self._signal(name)
                if signal is not None:
                    timeout_state[name] = hex(int(signal.value))
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
            print('[CVA6_TIMEOUT] {}'.format(timeout_state), flush=True)
            if self.trace:
                print('[DUT_TRACE] timeout cycles={}'.format(self.trace_cycles), flush=True)
            return TIME_OUT, self.covsum
        return SUCCESS, self.covsum
