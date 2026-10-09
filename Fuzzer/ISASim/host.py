import os
import subprocess

class isaInput():
    def __init__(self, binary, intrfile):
        self.binary = binary
        self.intrfile = intrfile

class rvISAhost():
    def __init__(self, spike, spike_args, isa_sigfile, debug=False):
        self.spike = spike
        self.spike_args = spike_args
        self.isa_sigfile = isa_sigfile

        self.debug = debug

    def debug_print(self, message):
        if self.debug:
            print(message)

    def run_test(self, isa_input: isaInput, assert_intr=False):
        binary = isa_input.binary
        intr = ['--intr={}'.format(isa_input.intrfile)] if assert_intr else []

        audit = ['-l', '--log-commits'] if os.environ.get('ILL_MEM_AUDIT') == '1' else []
        args = [ self.spike ] + self.spike_args + intr + audit + \
            [ '+signature={}'.format(self.isa_sigfile), binary ]

        self.debug_print('[ISAHost] Start ISA simulation')
        try:
            return subprocess.call(args, timeout=float(os.environ.get('ISA_TIMEOUT', '10')))
        except subprocess.TimeoutExpired:
            return 124

    def set_start_pc(self, address):
        self.spike_args = [arg for arg in self.spike_args
                           if not arg.startswith('--pc=')]
        self.spike_args.insert(1, '--pc={}'.format(hex(address)))
