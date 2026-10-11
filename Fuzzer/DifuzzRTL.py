import os
import time
import signal
from datetime import datetime

from cocotb.regression import TestFactory

from src.utils import save_file
from src.env_parser import envParser
from src.multicore_manager import proc_state, procManager

from Fuzzer import Run
from Minimizer import Minimize

### Multicore Fuzzing ###

def wait_check(proc_pid_arr: list, manager: procManager):
    end_pid, exit_code = os.waitpid(0, 0)
    idx = proc_pid_arr.index(end_pid)

    if exit_code != 0:
        print('[DifuzzRTL] Something bad happens! exit_code: {}'.format(exit_code))
        for pid in proc_pid_arr:
            if pid != end_pid:
                os.kill(pid, signal.SIGKILL)
        exit(-1)

    state = manager.get_state(idx)
    if state != proc_state.NORMAL:
        print('[DifuzzRTL] Child {} is in abnormal state {}!'.format(idx, proc_state.tpe[state]))
        for pid in proc_pid_arr:
            if pid != end_pid:
                os.kill(pid, signal.SIGKILL)
        exit(-1)

    return idx

#########################

""" Fuzzer entry """
parser = envParser()

parser.add_option('toplevel', None, 'Toplevel module of DUT')
parser.add_option('num_iter', 1, 'The number of fuzz iterations')
parser.add_option('template', 'Template', 'Template test file location')
parser.add_option('in_file', None, 'SimInput to replay')
parser.add_option('out', 'output', 'Directory to save the result')
parser.add_option('record', 0, 'Record the result')
parser.add_option('multicore', 0, 'The number of cores to use')
parser.add_option('debug', 0, 'Debugging?')
parser.add_option('minimize', 0, 'Minimizing?')
parser.add_option('prob_intr', 0, 'Probability of asserting interrupt')
parser.add_option('no_guide', 0, 'Only random testing?')
parser.add_option('feedback', 'covsum', 'Seed feedback: none or covsum')
parser.add_option('isa', 'RV64G', 'Instruction-set profile')
parser.add_option('xlen', 64, 'XLEN')
parser.add_option('march', 'rv64g', 'Compiler -march')
parser.add_option('mabi', 'lp64', 'Compiler -mabi')
parser.add_option('data_sections', 6, 'Number of mutable data sections')
parser.add_option('data_words_per_section', 64, 'Words per mutable data section')
parser.add_option('max_cycles', 0, 'DUT cycle limit per test; 0 selects target default')
parser.add_option('feedback_kind', 'reg',
                  'Feedback metric: reg, branch, path, or stmt')

parser.print_help()
parser.parse_option()
if os.environ.get('FUZZER_TOPLEVEL'):
    parser.arg_map['toplevel'] = (os.environ['FUZZER_TOPLEVEL'], 'FUZZER_TOPLEVEL',
                                  'Fuzzer target configuration')

if parser.arg_map['toplevel'][0] in ('Ibex', 'picorv32_verif_top', 'cva6'):
    out = parser.arg_map['out'][0]
    os.makedirs(out, exist_ok=True)
    for name in ('mismatch', 'illegal', 'corpus'):
        os.makedirs(os.path.join(out, name), exist_ok=True)
    date = datetime.today().strftime('%Y%m%d')
    cov_log = os.path.join(out, 'cov_log_{}.txt'.format(date))
    if not os.path.isfile(cov_log):
        save_file(cov_log, 'w', 'time\titer\tregcovsum\tstmtcovsum\tbranchcovsum\tpathcovsum\n')
    factory = TestFactory(Run)
    parser.register_option(factory)
    factory.add_option('cov_log', [cov_log])
    factory.add_option('start_time', [time.monotonic()])
    factory.add_option('max_cycles', [parser.arg_map['max_cycles'][0] or None])
    factory.generate_tests()

else:
    out = parser.arg_map['out'][0]
    record = parser.arg_map['record'][0]
    multicore = min(parser.arg_map['multicore'][0], 40)
    minimize = parser.arg_map['minimize'][0]
    parser.arg_map.pop('minimize', None)

    toplevel = parser.arg_map['toplevel'][0]
    template = parser.arg_map['template'][0]
    debug = parser.arg_map['debug'][0]
    max_cycles = parser.arg_map['max_cycles'][0] or None

    if not os.path.isdir(out):
        os.makedirs(out)
    for subdir in ('mismatch', 'illegal'):
        directory = os.path.join(out, subdir)
        if not os.path.isdir(directory):
            for child in ('', 'sim_input', 'elf', 'asm', 'hex'):
                os.makedirs(os.path.join(directory, child), exist_ok=True)
    os.makedirs(os.path.join(out, 'corpus'), exist_ok=True)

    date = datetime.today().strftime('%Y%m%d')
    cov_log = out + '/cov_log_{}.txt'.format(date)
    if (multicore or record) and not os.path.isfile(cov_log):
        save_file(cov_log, 'w', 'time\titer\tregcovsum\tstmtcovsum\tbranchcovsum\tpathcovsum\n')

    start_time = time.monotonic()

    if not multicore:
        if minimize:
            factory = TestFactory(Minimize)
            factory.add_option('toplevel', [toplevel])
            factory.add_option('template', [template])
            factory.add_option('out', [out])
            factory.add_option('debug', [debug])

        else:
            factory = TestFactory(Run)
            parser.register_option(factory)
            factory.add_option('max_cycles', [max_cycles])
            factory.add_option('feedback_kind', [parser.arg_map['feedback_kind'][0]])
            factory.add_option('cov_log', [cov_log])
            factory.add_option('start_time', [start_time])

        factory.generate_tests()

    else:
        manager = procManager(multicore, out, date)

        save_file(cov_log, 'a', '{:<10}\t{:<10}\t{:<10}\n'.
                  format(0, 0, 0))
        if not os.path.isdir(out + '/covmap'):
            os.makedirs(out + '/covmap')
        if not os.path.isdir(out + '/coverage'):
            os.makedirs(out + '/coverage')

        for i in range(multicore):
            if not os.path.isdir(out + '/covmap-{:02}'.format(i)):
                os.makedirs(out + '/covmap-{:02}'.format(i))

            if not os.path.isfile(out + '/coverage/cov_log_{}_{}.txt'.
                                  format(date, i)):
                save_file(out + '/coverage/cov_log_{}_{}.txt'.format(date, i),
                          'w', 'time\titer\tregcovsum\tstmtcovsum\tbranchcovsum\tpathcovsum\n')

        num_tot_iter = parser.arg_map['num_iter'][0]
        num_iter = 5000

        num_batch = num_tot_iter // num_iter
        print('[DifuzzRTL] Muticore Fuzzing, Number of batches -- {}'.format(num_batch))

        parent = True
        num_running = 0
        proc_num = 0
        proc_pid_arr = [ 0 for i in range(multicore) ] # proc_num as index
        for i in range(num_batch * multicore):
            proc_num = proc_pid_arr.index(0)
            print('[DifuzzRTL] Multicore Fuzzing Batch [{}], Thread [{}]'.format(i, proc_num))

            child_pid = os.fork()
            if child_pid == 0:
                parent = False
                break

            proc_pid_arr[proc_num] = child_pid
            num_running += 1

            if num_running == multicore:
                idx = wait_check(proc_pid_arr, manager)
                proc_pid_arr[idx] = 0
                num_running -= 1


        if not parent:
            manager.P('covMap')
            fd = open(out + '/cov_log_{}.txt'.format(date), 'r')
            lines = fd.readlines()
            fd.close()
            last_tuple = lines[-1].split('\t')
            manager.V('covMap')

            cov_log = out + '/coverage/cov_log_{}_{}.txt'.format(date, proc_num)
            start_iter = int(last_tuple[1])
            start_cov = int(last_tuple[2])

            factory = TestFactory(Run)
            parser.register_option(factory)
            factory.add_option('max_cycles', [max_cycles])
            factory.add_option('feedback_kind', [parser.arg_map['feedback_kind'][0]])
            factory.add_option('num_iter', [num_iter])
            factory.add_option('cov_log', [cov_log])
            factory.add_option('manager', [manager])
            factory.add_option('proc_num', [proc_num])
            factory.add_option('start_time', [start_time])
            factory.add_option('start_iter', [start_iter + 1])
            factory.add_option('start_cov', [start_cov])

            factory.generate_tests()

        else:
            while num_running:
                idx = wait_check(proc_pid_arr, manager)
                proc_pid_arr[idx] = 0
                num_running -= 1

            manager.remove()

            print('[DifuzzRTL] Stop Multicore Fuzzing')

            minimizer = False
            for i in range(multicore):
                child_pid = os.fork()
                if child_pid == 0:
                    minimizer = True
                    break

            if minimizer:
                factory = TestFactory(Minimize)
                factory.add_option('toplevel', [toplevel])
                factory.add_option('template', [template])
                factory.add_option('out', [out])
                factory.add_option('num_cores', [multicore])
                factory.add_option('proc_num', [i])
                factory.add_option('debug', [debug])
                factory.generate_tests()
