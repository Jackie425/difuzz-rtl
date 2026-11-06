"""Execute firmware tools with bounded retries for transient execution errors."""
import errno
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time


class ToolchainError(RuntimeError):
    pass


def run_tool(arguments, *, env=None, log=None, isolate=False):
    for attempt in range(1, 4):
        process = None
        interrupted = []
        previous = {}

        def shutdown(signum, frame):
            interrupted.append(signum)
            if process is not None:
                raise KeyboardInterrupt

        try:
            # Preflight tools own a group; runtime tools belong to the simulator.
            # Defer cancellation until a newly spawned group can be cleaned up.
            if isolate:
                previous = {sig: signal.signal(sig, shutdown)
                            for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                process = subprocess.Popen(arguments, env=env, text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           start_new_session=isolate)
                if interrupted:
                    raise KeyboardInterrupt
                output, _ = process.communicate()
            except BaseException:
                if process is not None:
                    cleanup_handlers = {sig: signal.signal(sig, signal.SIG_IGN)
                                        for sig in (signal.SIGINT, signal.SIGTERM)}
                    try:
                        try:
                            if isolate:
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                        except ProcessLookupError:
                            pass
                        process.communicate()
                    finally:
                        for sig, handler in cleanup_handlers.items():
                            signal.signal(sig, handler)
                raise
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
            if process.returncode == 0:
                return output
            detail = 'exit {}\n{}'.format(process.returncode, output)
            transient = any(message in output.lower() for message in
                            ('permission denied', 'text file busy',
                             'resource temporarily unavailable'))
        except OSError as error:
            detail = str(error)
            transient = error.errno in (errno.EACCES, errno.ETXTBSY, errno.EAGAIN)
        message = '{}: {}'.format(shlex.join(map(str, arguments)), detail)
        if log is not None:
            with Path(log).open('a', encoding='utf-8') as stream:
                stream.write('attempt {}: {}\n'.format(attempt, message))
        if not transient or attempt == 3:
            raise ToolchainError(message)
        print('[toolchain retry {}/3] {}'.format(attempt, message), flush=True)
        time.sleep(0.1)


def preflight(config, env, output):
    """Exercise the selected compiler and converter, including their subtools."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assembly, elf, hexfile = (output / name for name in ('probe.S', 'probe.elf', 'probe.hex'))
    assembly.write_text('.section .text\n.global _start\n_start: .word 0x00000013\n',
                        encoding='utf-8')
    address = int(config['ram']['base'], 0) + int(config['boot_offset'], 0)
    log = output / 'toolchain-errors.log'
    run_tool(['riscv64-unknown-elf-gcc', '-march=' + config.get('march', config['isa'].lower()),
              '-mabi=' + config['mabi'], '-nostdlib', '-nostartfiles',
              '-Wl,-Ttext=0x{:x}'.format(address), '-Wl,--no-relax',
              '-Wl,--build-id=none', str(assembly), '-o', str(elf)], env=env, log=log, isolate=True)
    conversion_env = dict(env, ELF2HEX_BASE=config['ram']['base'])
    run_tool([env['ELF2HEX'], '--bit-width', str(config['xlen']), '--input', str(elf),
              '--output', str(hexfile)], env=conversion_env, log=log, isolate=True)
    if not hexfile.is_file() or not any(int(word, 16) for word in hexfile.read_text().split()):
        raise ToolchainError('converter produced no firmware image: {}'.format(hexfile))
    symbols = run_tool(['nm', str(elf)], env=env, log=log, isolate=True)
    if '_start' not in symbols:
        raise ToolchainError('symbol lookup produced no entry point: {}'.format(elf))
