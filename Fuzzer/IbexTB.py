import cocotb
from cocotb.triggers import RisingEdge


def _load_hex64_lines(path: str) -> list[int]:
    """Load a riscv-elf2hex style file: one 64-bit word per line (hex)."""
    words: list[int] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("0x") or line.startswith("0X"):
                line = line[2:]
            words.append(int(line, 16) & ((1 << 64) - 1))
    return words


def _parse_nm_symbols(path: str) -> dict[str, int]:
    """Parse the nm output file written by Difuzz preprocessor."""
    syms: dict[str, int] = {}
    with open(path, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                addr = int(parts[0], 16)
            except Exception:
                continue
            syms[parts[2]] = addr
    return syms


def _parse_si_data_words(path: str) -> list[int]:
    """Parse the 'data:' section from a .si file (hex 64-bit words)."""
    data: list[int] = []
    in_data = False
    with open(path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not in_data:
                if line == "data:" or line.startswith("data:"):
                    in_data = True
                continue
            if not line:
                continue
            data.append(int(line, 16) & ((1 << 64) - 1))
    return data


def parse_si_data_words(path: str) -> list[int]:
    """Public wrapper for parsing the 'data:' section from a .si file."""
    return _parse_si_data_words(path)


def append_random_data_to_signature_if_missing(sig_path: str, symbols: dict[str, int], si_path: str) -> None:
    """Append random data sections to an ISA signature file if they are missing.

    This matches the Rocket-style layout used by DifuzzRTL: signature region first,
    then _random_data0.._random_data5.
    """
    sig_start = symbols.get('begin_signature')
    sig_end = symbols.get('end_signature')
    if sig_start is None or sig_end is None or sig_end <= sig_start:
        return

    sig_lines_expected = (sig_end - sig_start) // 16
    data_sections = []
    for n in range(6):
        s = symbols.get(f'_random_data{n}')
        e = symbols.get(f'_end_data{n}')
        if s is None or e is None or e <= s:
            data_sections.append(0)
        else:
            data_sections.append((e - s) // 16)

    total_expected = sig_lines_expected + sum(data_sections)
    try:
        with open(sig_path, 'r') as f:
            existing = f.readlines()
    except Exception:
        existing = []

    if len(existing) >= total_expected:
        return

    data_words = _parse_si_data_words(si_path)
    if not data_words:
        return

    offset = 0
    with open(sig_path, 'a') as f:
        for n in range(6):
            s = symbols.get(f'_random_data{n}')
            e = symbols.get(f'_end_data{n}')
            if s is None or e is None or e <= s:
                continue
            n_qwords = (e - s) // 8
            section = data_words[offset:offset + n_qwords]
            offset += n_qwords
            for i in range(0, len(section), 2):
                if i + 1 >= len(section):
                    break
                f.write(f'{section[i+1]:016x}{section[i]:016x}\n')


class SimpleMem32:
    """A tiny, blocking memory model for ibex_top (32-bit data) backed by bytes."""

    def __init__(self):
        self.mem8: dict[int, int] = {}

    def load_hex64(self, start_addr: int, hex64_words: list[int]):
        addr = start_addr
        for w in hex64_words:
            for i in range(8):
                self.mem8[addr + i] = (w >> (8 * i)) & 0xFF
            addr += 8

    def write64(self, addr: int, data64: int):
        for i in range(8):
            self.mem8[addr + i] = (data64 >> (8 * i)) & 0xFF

    def read32(self, addr: int) -> int:
        a = addr & ~0x3
        val = 0
        for i in range(4):
            val |= (self.mem8.get(a + i, 0) & 0xFF) << (8 * i)
        return val & 0xFFFFFFFF

    def read64(self, addr: int) -> int:
        a = addr & ~0x7
        val = 0
        for i in range(8):
            val |= (self.mem8.get(a + i, 0) & 0xFF) << (8 * i)
        return val & 0xFFFFFFFFFFFFFFFF

    def write32(self, addr: int, data: int, be: int):
        a = addr & ~0x3
        for i in range(4):
            if (be >> i) & 0x1:
                self.mem8[a + i] = (data >> (8 * i)) & 0xFF


def _drive_ibex_defaults(dut, *, boot_addr: int, pcov_meta_reset: bool):
    dut.test_en_i.value = 0
    dut.ram_cfg_i.value = 0

    dut.hart_id_i.value = 0
    dut.boot_addr_i.value = boot_addr & 0xFFFFFFFF

    dut.scramble_key_valid_i.value = 0
    dut.scramble_key_i.value = 0
    dut.scramble_nonce_i.value = 0

    dut.debug_req_i.value = 0

    try:
        fe_w = len(dut.fetch_enable_i)
    except Exception:
        fe_w = 1
    dut.fetch_enable_i.value = (1 << fe_w) - 1

    if hasattr(dut, "scan_rst_ni"):
        dut.scan_rst_ni.value = int(getattr(dut, "rst_ni").value) if hasattr(dut, "rst_ni") else 1

    dut.irq_software_i.value = 0
    dut.irq_timer_i.value = 0
    dut.irq_external_i.value = 0
    dut.irq_fast_i.value = 0
    dut.irq_nm_i.value = 0

    if hasattr(dut, "pcov_meta_reset"):
        dut.pcov_meta_reset.value = 1 if pcov_meta_reset else 0

    dut.instr_gnt_i.value = 0
    dut.instr_rvalid_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_rdata_intg_i.value = 0
    dut.instr_err_i.value = 0

    dut.data_gnt_i.value = 0
    dut.data_rvalid_i.value = 0
    dut.data_rdata_i.value = 0
    dut.data_rdata_intg_i.value = 0
    dut.data_err_i.value = 0


def _dump_signature_rocket_format(mem: SimpleMem32, symbols: dict[str, int], sig_file: str) -> None:
    sig_start = symbols.get("begin_signature")
    sig_end = symbols.get("end_signature")
    if sig_start is None or sig_end is None or sig_end <= sig_start:
        return

    data_addrs: list[tuple[int, int]] = []
    for n in range(6):
        s = symbols.get(f"_random_data{n}")
        e = symbols.get(f"_end_data{n}")
        if s is None or e is None or e <= s:
            continue
        data_addrs.append((s, e))

    with open(sig_file, "w") as fd:
        for i in range(sig_start, sig_end, 16):
            fd.write(f"{mem.read64(i + 8):016x}{mem.read64(i):016x}\n")

        for (data_start, data_end) in data_addrs:
            for i in range(data_start, data_end, 16):
                fd.write(f"{mem.read64(i + 8):016x}{mem.read64(i):016x}\n")


async def run_ibex_program(
    dut,
    *,
    hex_path: str,
    symbols_path: str,
    si_path: str,
    max_cycles: int = 200000,
    reset_cov: bool = False,
    rtl_sig_path: str | None = None,
):
    """Run one program on ibex_top and return (final_cov, cycles_executed)."""

    symbols = _parse_nm_symbols(symbols_path)

    load_addr = symbols.get("_boot_base")
    if load_addr is None:
        start = symbols.get("_start", 0)
        load_addr = start & ~0xFF

    boot_addr = load_addr

    _drive_ibex_defaults(dut, boot_addr=boot_addr, pcov_meta_reset=bool(reset_cov))

    if not hasattr(run_ibex_program, "_clock_started"):

        async def clock_gen():
            while True:
                dut.clk_i.value = 0
                await cocotb.triggers.Timer(1, units="us")
                dut.clk_i.value = 1
                await cocotb.triggers.Timer(1, units="us")

        if hasattr(cocotb, "start_soon"):
            cocotb.start_soon(clock_gen())
        else:
            cocotb.fork(clock_gen())
        run_ibex_program._clock_started = True

    dut.rst_ni.value = 0
    if hasattr(dut, "scan_rst_ni"):
        dut.scan_rst_ni.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk_i)

    if hasattr(dut, "pcov_meta_reset") and reset_cov:
        dut.pcov_meta_reset.value = 0

    dut.rst_ni.value = 1
    if hasattr(dut, "scan_rst_ni"):
        dut.scan_rst_ni.value = 1
    for _ in range(5):
        await RisingEdge(dut.clk_i)

    mem = SimpleMem32()
    mem.load_hex64(load_addr, _load_hex64_lines(hex_path))

    data_words = _parse_si_data_words(si_path)
    if data_words:
        offset = 0
        for n in range(6):
            s = symbols.get(f"_random_data{n}")
            e = symbols.get(f"_end_data{n}")
            if s is None or e is None or e <= s:
                continue
            n_qwords = (e - s) // 8
            for i in range(n_qwords):
                if offset + i >= len(data_words):
                    break
                mem.write64(s + i * 8, data_words[offset + i])
            offset += n_qwords

    def get_cov() -> int:
        if hasattr(dut, "pcov_regcov_covsum"):
            return int(dut.pcov_regcov_covsum.value)
        if hasattr(dut, "io_covSum"):
            return int(dut.io_covSum.value)
        return 0

    tohost_addr = symbols.get("tohost")

    instr_accept_q = 0
    instr_addr_q = 0
    data_accept_q = 0
    data_rdata_q = 0

    last_cov = get_cov()

    cycles = 0
    for cycle in range(max_cycles):
        cycles = cycle

        rst_ni = int(dut.rst_ni.value)

        fetch_valid = 1 if (instr_accept_q and rst_ni) else 0
        dut.instr_rvalid_i.value = fetch_valid
        if fetch_valid:
            dut.instr_rdata_i.value = mem.read32(instr_addr_q & 0xFFFFFFFF)
        dut.instr_rdata_intg_i.value = 0
        dut.instr_err_i.value = 0

        dut.data_rvalid_i.value = 1 if (data_accept_q and rst_ni) else 0
        if data_accept_q and rst_ni:
            dut.data_rdata_i.value = data_rdata_q & 0xFFFFFFFF
        dut.data_rdata_intg_i.value = 0
        dut.data_err_i.value = 0

        instr_req = int(dut.instr_req_o.value)
        data_req = int(dut.data_req_o.value)
        dut.instr_gnt_i.value = 1 if (rst_ni and instr_req) else 0
        dut.data_gnt_i.value = 1 if rst_ni else 0

        instr_accept = 1 if (instr_req and int(dut.instr_gnt_i.value)) else 0
        data_accept = 1 if (data_req and int(dut.data_gnt_i.value)) else 0

        next_instr_accept_q = instr_accept
        next_instr_addr_q = instr_addr_q
        if instr_accept:
            next_instr_addr_q = int(dut.instr_addr_o.value)

        next_data_accept_q = data_accept
        next_data_rdata_q = data_rdata_q
        if data_accept:
            is_write = int(dut.data_we_o.value) == 1
            addr = int(dut.data_addr_o.value)
            wdata = int(dut.data_wdata_o.value)
            be = int(dut.data_be_o.value)
            if is_write:
                mem.write32(addr, wdata, be)
                next_data_rdata_q = 0
            else:
                next_data_rdata_q = mem.read32(addr)

        await RisingEdge(dut.clk_i)

        if not rst_ni:
            instr_accept_q = 0
            instr_addr_q = 0
            data_accept_q = 0
            data_rdata_q = 0
        else:
            instr_accept_q = next_instr_accept_q
            instr_addr_q = next_instr_addr_q
            data_accept_q = next_data_accept_q
            data_rdata_q = next_data_rdata_q

        if tohost_addr is not None and mem.read32(tohost_addr) != 0:
            break

        last_cov = get_cov()

    if rtl_sig_path:
        _dump_signature_rocket_format(mem, symbols, rtl_sig_path)

    return last_cov, cycles
