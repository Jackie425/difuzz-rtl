"""Load the selected DUT's stimulus policy."""
import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def _load(filename):
    config = json.loads(Path(filename).read_text())
    policy = dict(config['fuzzer'])
    if 'csr_names' not in policy:
        raise ValueError('DUT fuzzer profile requires an explicit csr_names whitelist: ' + filename)
    if 'rv_zicsr' in policy['extensions'] and not policy['csr_names']:
        raise ValueError('Zicsr stimulus requires a nonempty CSR whitelist: ' + filename)
    policy['template'] = str(Path(filename).parent / policy['template'])
    return policy


def profile():
    filename = os.environ.get('FUZZER_CONFIG')
    if not filename:
        # Direct simulator/replay launches also use the same DUT configuration.
        dut = os.environ.get('DUT_NAME')
        if dut in ('ibex', 'picorv32', 'cva6'):
            filename = str(Path(__file__).resolve().parents[3] /
                           'config' / dut / (dut + '.json'))
    return _load(filename) if filename else {}
