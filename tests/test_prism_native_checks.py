"""Native host receipt refusal tests using isolated files and no hardware."""
import copy
from pathlib import Path

import pytest

from ael.adapters import prism_lane as lane


@pytest.fixture(params=['dualmcu', 'titan'])
def checks(request, tmp_path):
    kind = request.param
    source = tmp_path / lane.LANES[kind]
    output = tmp_path / 'checks'
    output.mkdir()
    inputs = {}
    for name in ['src/application.cpp', 'deps/PRISM-Core/music/runtime.cpp']:
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('isolated source ' + name)
        inputs[name] = lane.sha(file)
    facts = {'source': {'tracked_files': list(inputs)}}
    common = {'exit_code': 0, 'hardware_access': False, 'product_admitted': False}
    if kind == 'dualmcu':
        log = output / 'positive.log'
        log.write_text('actual isolated fixture log')
        fault = output / 'fault.log'
        fault.write_text('actual isolated fixture negative log')
        record = {**common, 'schema': 'prism.native-host-test.v1', 'classification': 'PRODUCT_CANDIDATE',
                  'operation': 'test', 'inputs': inputs,
                  'operations': [{'argv': ['clang++', 'fixture.cpp'], 'returncode': 0,
                                  'log': log.name, 'log_sha256': lane.sha(log)}],
                  'mutations': [{'name': 'fixture fault', 'compile_returncode': 0,
                                 'run_returncode': 1, 'detected': True,
                                 'log': fault.name, 'log_sha256': lane.sha(fault)}]}
    else:
        binary = output / 'fixture'
        mutant = output / 'mutant'
        binary.write_bytes(b'isolated positive executable fixture')
        mutant.write_bytes(b'isolated mutated executable fixture')
        record = {**common, 'schema': 'prism-titan-native-checks.v1', 'classification': 'HOST_QUALIFICATION_ONLY',
                  'inputs': {'src/application.cpp': inputs['src/application.cpp']},
                  'core_root': str(source / 'deps/PRISM-Core'),
                  'core_inputs': {'music/runtime.cpp': inputs['deps/PRISM-Core/music/runtime.cpp']},
                  'results': [{'case': 'application compile', 'argv': ['clang++', 'fixture.cpp', '-o', str(binary)], 'exit_code': 0},
                              {'case': 'application sanitised', 'argv': [str(binary)], 'exit_code': 0},
                              {'case': 'mutant compile', 'argv': ['clang++', 'mutant.cpp', '-o', str(mutant)], 'exit_code': 0},
                              {'case': 'fixture planted fault', 'argv': [str(mutant)], 'exit_code': 1}]}
    return kind, record, output, source, facts


def test_native_checks_remain_host_scope(checks):
    kind, record, output, source, facts = checks
    lane.validate_native_checks(record, output, source, kind, facts)
    assert facts['rejected_compiled_faults']
    assert facts['qualification'].startswith('NATIVE_HOST_CANDIDATE_CHECKS:')
    assert facts['native_check_receipt']['product_admitted'] is False


@pytest.mark.parametrize('fault', ['failed', 'boolean_exit', 'hardware', 'admitted', 'development',
                                  'wrong_schema', 'untracked', 'source_changed', 'positive_failed',
                                  'fault_survived', 'fault_absent'])
def test_false_native_execution_is_rejected(checks, fault):
    kind, original, output, source, facts = checks
    record = copy.deepcopy(original)
    if fault == 'failed': record['exit_code'] = 1
    if fault == 'boolean_exit': record['exit_code'] = False
    if fault == 'hardware': record['hardware_access'] = True
    if fault == 'admitted': record['product_admitted'] = True
    if fault == 'development': record['development_core'] = True
    if fault == 'wrong_schema': record['schema'] = 'BENCH_ONLY'
    if fault == 'untracked': facts['source']['tracked_files'].remove('src/application.cpp')
    if fault == 'source_changed': (source / 'src/application.cpp').write_text('changed source')
    if kind == 'dualmcu':
        if fault == 'positive_failed': record['operations'][0]['returncode'] = 1
        if fault == 'fault_survived': record['mutations'][0]['run_returncode'] = 0
        if fault == 'fault_absent': record['mutations'] = []
    else:
        if fault == 'positive_failed': record['results'][0]['exit_code'] = 1
        if fault == 'fault_survived': record['results'][-1]['exit_code'] = 0
        if fault == 'fault_absent': record['results'].pop()
    with pytest.raises(RuntimeError):
        lane.validate_native_checks(record, output, source, kind, facts)


def test_native_core_input_is_bound(checks):
    kind, record, output, source, facts = checks
    (source / 'deps/PRISM-Core/music/runtime.cpp').write_text('changed Core')
    with pytest.raises(RuntimeError):
        lane.validate_native_checks(record, output, source, kind, facts)


def test_changed_dual_fault_log_is_rejected(checks):
    kind, record, output, source, facts = checks
    if kind != 'dualmcu': pytest.skip('Dual receipt binds external command logs')
    (output / 'fault.log').write_text('replaced failure log')
    with pytest.raises(RuntimeError, match='log missing or changed'):
        lane.validate_native_checks(record, output, source, kind, facts)


@pytest.mark.parametrize('fault', ['compile_absent', 'compiler_marker', 'wrong_output',
                                  'compile_after_run', 'missing_binary', 'reused_fault'])
def test_titan_fault_requires_its_actual_compiled_output(checks, fault):
    kind, original, output, source, facts = checks
    if kind != 'titan':
        pytest.skip('Titan ordered command receipt')
    record = copy.deepcopy(original)
    if fault == 'compile_absent': record['results'].pop(2)
    if fault == 'compiler_marker': record['results'][2]['argv'][0] = 'echo'
    if fault == 'wrong_output': record['results'][2]['argv'][-1] = str(output / 'other')
    if fault == 'compile_after_run': record['results'][2:] = list(reversed(record['results'][2:]))
    if fault == 'missing_binary': (output / 'mutant').unlink()
    if fault == 'reused_fault': record['results'].append(copy.deepcopy(record['results'][-1]))
    with pytest.raises(RuntimeError):
        lane.validate_native_checks(record, output, source, kind, facts)
