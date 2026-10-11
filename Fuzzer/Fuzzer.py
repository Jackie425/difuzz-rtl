import os
import time
import random

from cocotb.decorators import coroutine
from RTLSim.host import ILL_MEM, SUCCESS, TIME_OUT, ASSERTION_FAIL

from src.utils import debug_print, run_isa_test, save_err, save_file, save_mismatch, setup
from src.multicore_manager import proc_state


@coroutine
def Run(dut, toplevel,
        num_iter=1, template='Template', in_file=None,
        out='output', record=False, cov_log=None,
        multicore=0, manager=None, proc_num=0, start_time=0, start_iter=0, start_cov=0,
        prob_intr=0, no_guide=False, debug=False, minimize=0, feedback='covsum',
        isa='RV64G', xlen=64, march='rv64g', mabi='lp64',
        data_sections=6, data_words_per_section=64, max_cycles=None,
        feedback_kind='reg'):

    assert toplevel in ['RocketTile', 'BoomTile', 'Ibex', 'picorv32_verif_top', 'cva6' ], \
        '{} is not toplevel'.format(toplevel)

    benchmark = toplevel in ('Ibex', 'picorv32_verif_top', 'cva6')
    audit = os.environ.get('ILL_MEM_AUDIT') == '1'
    seed = os.environ.get('FUZZ_SEED')
    random.seed(int(seed) if seed is not None else time.time() * (proc_num + 1))

    (mutator, preprocessor, isaHost, rtlHost, checker) = \
        setup(dut, toplevel, template, out, proc_num, debug,
              no_guide=no_guide, isa=isa, xlen=xlen,
              march=march, mabi=mabi, data_sections=data_sections,
              data_words_per_section=data_words_per_section,
              max_cycles=max_cycles, feedback_kind=feedback_kind)

    if in_file: num_iter = 1

    stop = [ proc_state.NORMAL ]
    mNum = 0
    cNum = 0
    iNum = 0
    last_coverage = 0
    last_metric_coverage = 0

    debug_print('[DifuzzRTL] Start Fuzzing', debug)
    print('[DifuzzRTL] FUZZ_START', flush=True)

    if multicore:
        yield manager.cov_restore(dut)

    def input_result(test_id, outcome):
        # Persist each finished input even when the timed runner terminates us.
        with open(out + '/input-results.tsv', 'a') as stream:
            stream.write('{}\t{}\n'.format(test_id, outcome))

    for it in range(num_iter):
        test_id = start_iter + it
        debug_print('[DifuzzRTL] Iteration [{}]'.format(it), debug)

        if multicore:
            if it == 0:
                mutator.update_corpus(out + '/corpus', 1000)
            elif it % 1000 == 0:
                mutator.update_corpus(out + '/corpus')

        assert_intr = random.random() < prob_intr

        if in_file: (sim_input, data, assert_intr) = mutator.read_siminput(in_file)
        else: (sim_input, data) = mutator.get(assert_intr)

        if debug:
            print('[DifuzzRTL] Fuzz Instructions')
            for inst, INT in zip(sim_input.get_insts(), sim_input.ints + [0]):
                print('{:<50}{:04b}'.format(inst, INT))

        (isa_input, rtl_input, symbols) = preprocessor.process(sim_input, data, assert_intr)

        if isa_input and rtl_input:
            if benchmark:
                isaHost.set_start_pc(symbols[os.environ.get('SPIKE_START_SYMBOL', '_start')])
            ret = run_isa_test(isaHost, isa_input, stop, out, proc_num)
            if audit:
                print("[INPUT_AUDIT] ISA result={}".format(ret), flush=True)
            if ret == proc_state.ERR_ISA_TIMEOUT:
                input_result(test_id, 'isa_timeout')
                if record:
                    save_mismatch(out, proc_num, out + '/isa_timeout', sim_input, data, test_id)
                continue
            elif ret == proc_state.ERR_ISA_ASSERT and not audit:
                # Retain rejected inputs without stopping the timed experiment.
                if record:
                    save_mismatch(out, proc_num, out + '/illegal', sim_input,
                                  data, test_id if benchmark else iNum)
                iNum += 1
                input_result(test_id, 'isa_error')
                continue

            audit_isa_failed = audit and ret != proc_state.NORMAL
            try:
                (ret, coverage) = yield rtlHost.run_test(rtl_input, assert_intr)
            except Exception as error:
                stop[0] = proc_state.ERR_RTL_SIM
                raise RuntimeError('RTL simulation failed: {}'.format(error)) from error

            if audit:
                print("[INPUT_AUDIT] RTL result={}".format(ret), flush=True)

            feedback_coverage = (rtlHost.feedback_coverage()
                                 if hasattr(rtlHost, 'feedback_coverage')
                                 else coverage)

            if assert_intr and ret == SUCCESS:
                (intr_prv, epc) = checker.check_intr(symbols)
                if epc != 0:
                    preprocessor.write_isa_intr(isa_input, rtl_input, epc)
                    ret = run_isa_test(isaHost, isa_input, stop, out, proc_num, True)
                    if ret == proc_state.ERR_ISA_TIMEOUT: continue
                    elif ret == proc_state.ERR_ISA_ASSERT:
                        if record:
                            save_mismatch(out, proc_num, out + '/illegal', sim_input,
                                  data, test_id if benchmark else iNum)
                        iNum += 1
                        continue
                else: continue

            cause = '-'
            match = False
            if ret == SUCCESS:
                match = audit_isa_failed or checker.check(symbols)
            elif ret == ILL_MEM:
                match = True
                debug_print('[DifuzzRTL] Memory access outside DRAM -- {}'. \
                            format(iNum), debug, True)
                if record:
                    save_mismatch(out, proc_num, out + '/illegal',
                                  sim_input, data,
                                  test_id if benchmark else iNum)
                iNum += 1

            if not match or ret not in [SUCCESS, ILL_MEM]:
                if multicore:
                    mNum = manager.read_num('mNum')
                    manager.write_num('mNum', mNum + 1)

                if record:
                    signatures = None
                    if benchmark:
                        signatures = {}
                        if os.path.isfile(checker.isa_sigfile):
                            signatures['isa'] = checker.isa_sigfile
                        if os.path.isfile(rtlHost.signature_file):
                            signatures['rtl'] = rtlHost.signature_file
                    save_mismatch(out, proc_num, out + '/mismatch',
                                  sim_input, data,
                                  test_id if benchmark else mNum,
                                  signatures)

                mNum += 1
                if ret == TIME_OUT: cause = 'Timeout'
                elif ret == ASSERTION_FAIL: cause = 'Assertion fail'
                else: cause = 'Mismatch'

                debug_print('[DifuzzRTL] Bug -- {} [{}]'. \
                            format(mNum, cause), debug, not match or (ret != SUCCESS))

            input_result(test_id, 'isa_error' if audit_isa_failed else
                         'valid' if ret == SUCCESS and match else
                         'illegal_memory' if ret == ILL_MEM else
                         'rtl_timeout' if ret == TIME_OUT else 'mismatch')

            valid = ret == SUCCESS and match and not audit_isa_failed
            if record and valid:
                metric_coverage = max(last_metric_coverage, coverage)
                values = (time.monotonic() - start_time, start_iter + it,
                          start_cov + metric_coverage)
                if benchmark:
                    values += rtlHost.code_coverage_sums()
                save_file(cov_log, 'a', '\t'.join(map(str, values)) + '\n')
                last_metric_coverage = metric_coverage

            if valid and feedback != 'none' and feedback_coverage > last_coverage:
                if multicore:
                    cNum = manager.read_num('cNum')
                    manager.write_num('cNum', cNum + 1)

                if record:
                    corpus_id = test_id if benchmark else cNum
                    sim_input.save(out + '/corpus/id_{}.si'.format(corpus_id))

                cNum += 1
                mutator.add_corpus(sim_input)
                last_coverage = feedback_coverage

            mutator.update_phase(it)

        else:
            input_result(test_id, 'compile_error')
            stop[0] = proc_state.ERR_COMPILE
            # Compile failed
            break

    if multicore:
        save_err(out, proc_num, manager, stop[0])
        manager.set_state(proc_num, stop[0])

    debug_print('[DifuzzRTL] Stop Fuzzing', debug)

    if multicore:
        yield manager.cov_store(dut, proc_num)
        manager.store_covmap(proc_num, start_time, start_iter, num_iter)
