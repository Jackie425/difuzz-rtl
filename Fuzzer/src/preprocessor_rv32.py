import os
import re
import subprocess

from ISASim.host import isaInput
from RTLSim.host import rtlInput
from mutator import simInput, templates, V_U


class rv32PreProcessor:
    """RV32-only stimulus preprocessor for Ibex.

    This is intentionally separate from the baseline rvPreProcessor (RV64) so we don't
    change DifuzzRTL's original Rocket/Boom flow.

    It consumes a simInput + random data words and emits:
      .si/.S/.elf/.hex/.symbols
    using Template/rv32-<template>.S and Template/include/link.ld.

    Notes:
    - Uses 64-bit-per-line elf2hex output to stay compatible with IbexTB loader.
      - Does not implement the baseline v-u (C) path; it compiles all templates as assembly.
    """

    def __init__(self, cc: str, elf2hex: str, template: str = "Template", out_base: str = ".", proc_num: int = 0):
        self.cc = cc
        self.elf2hex = elf2hex
        self.template = template
        self.base = out_base
        self.proc_num = proc_num

        self.cc_args = [
            cc,
            "-march=rv32im_zicsr_zifencei",
            "-mabi=ilp32",
            "-static",
            "-mcmodel=medany",
            "-fvisibility=hidden",
            "-nostdlib",
            "-nostartfiles",
            "-I",
            f"{template}",
            "-I",
            f"{template}/include",
            "-T",
            f"{template}/include/link.ld",
        ]

        # Keep 64-bit words per line so the existing loader can stay unchanged.
        self.elf2hex_args = [elf2hex, "--bit-width", "64", "--input"]

    def get_symbols(self, elf_name: str, sym_name: str):
        fd = open(sym_name, "w")
        subprocess.call(["nm", elf_name], stdout=fd)
        fd.close()

        symbols = {}
        with open(sym_name, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    addr = int(parts[0], 16)
                except Exception:
                    continue
                sym = parts[2]
                symbols[sym] = addr

        return symbols

    def process(self, sim_input: simInput, data: list, intr: bool, num_data_sections: int = 6):
        section_size = len(data) // num_data_sections

        assert data, "Empty data can not be processed"
        assert (section_size & (section_size - 1)) == 0, "Number of memory blocks should be power of 2"

        version = sim_input.get_template()
        test_template = f"{self.template}/rv32-{templates[version]}.S"

        si_name = self.base + f"/.input_{self.proc_num}.si"
        asm_name = self.base + f"/.input_{self.proc_num}.S"
        elf_name = self.base + f"/.input_{self.proc_num}.elf"
        hex_name = self.base + f"/.input_{self.proc_num}.hex"
        sym_name = self.base + f"/.input_{self.proc_num}.symbols"

        prefix_insts = sim_input.get_prefix()
        insts = sim_input.get_insts()
        suffix_insts = sim_input.get_suffix()

        # Save .si with embedded random data for later replay
        sim_input.save(si_name, data)

        with open(test_template, "r") as fd:
            template_lines = fd.readlines()

        # Some RV32 template variants are thin wrappers that only include
        # rv32-p-m.S. Expand one local include so fuzz markers are visible.
        has_markers = any(("_fuzz_prefix:" in ln) or ("_fuzz_main:" in ln) or ("_fuzz_suffix:" in ln)
                          for ln in template_lines)
        if not has_markers:
            for ln in template_lines:
                m = re.match(r'^\s*#include\s+"([^"]+)"\s*$', ln)
                if not m:
                    continue
                inc_name = m.group(1)
                inc_path = os.path.join(os.path.dirname(test_template), inc_name)
                if os.path.isfile(inc_path):
                    with open(inc_path, "r") as ifd:
                        template_lines = ifd.readlines()
                break

        assembly = []
        for line in template_lines:
            assembly.append(line)
            if "_fuzz_prefix:" in line:
                for inst in prefix_insts:
                    assembly.append(inst + ";\n")

            if "_fuzz_main:" in line:
                for inst in insts:
                    assembly.append(inst + ";\n")

            if "_fuzz_suffix:" in line:
                for inst in suffix_insts:
                    assembly.append(inst + ";\n")

            for n in range(num_data_sections):
                start = n * section_size
                end = start + section_size
                # Only inject once, at the label definition.
                if f"_random_data{n}:" in line:
                    k = 0
                    for i in range(start, end, 2):
                        label = ""
                        if i > start + 2 and i < end - 4:
                            label = f"d_{n}_{k}:"
                            k += 1
                        assembly.append(f"{label:<16}.dword 0x{data[i]:016x}, 0x{data[i+1]:016x}\n")

        with open(asm_name, "w") as fd:
            fd.writelines(assembly)

        cc_args = self.cc_args.copy()
        # Optional interrupt define (usually disabled for Ibex baseline use)
        if intr:
            cc_args += ["-DINTERRUPT"]
        cc_args += [asm_name, "-o", elf_name]

        cc_ret = subprocess.call(cc_args)
        if cc_ret != 0:
            return (None, None, None)

        subprocess.call(self.elf2hex_args + [elf_name, "--output", hex_name])
        symbols = self.get_symbols(elf_name, sym_name)

        # Keep timeout policy aligned with RV64 baseline:
        # p-m/p-s/p-u => 6000, v-u => 200000
        max_cycles = 6000
        if version in [V_U]:
            max_cycles = 200000

        # Keep return signature consistent with baseline preprocessor.
        isa_input = isaInput(elf_name, "")
        rtl_input = rtlInput(hex_name, "", data, symbols, max_cycles=max_cycles)
        return (isa_input, rtl_input, symbols)
