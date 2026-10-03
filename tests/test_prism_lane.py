"""Red-capable boundaries: stale publications must never pass as live hardware."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from ael.adapters import prism_lane as lane


def sample():
    return {'identity': {'identified': True, 'uid': lane.TITAN_UID, 'build': 'expected',
                         'runtime_kind': 'live', 'contract': 'sr12800.hop64.bins64.emotiscope'},
            'pid': 123, 'epoch': 1, 'serial_opens': 1, 'quiesced': False,
            'topic_mono': {'identity': 99, 'pdm': 99, 'palette': 99}, 'host_mono': 99,
            'pdm': {'running': True, 'rate_locked': 1, 'stream_epoch': 7, 'rearm_denied': 7,
                    'asrc_starved': 0, 'pair_skew_drops': 0, 'push_rejected': 0, 'stale_discards': 0,
                    'ap_hops': 200, 'last_hop_peak': 300,
                    'lanes': [{'error_flags': 0, 'overflow_events': 0, 'drop_events': 0,
                               'recovery_count': 6} for _ in range(2)]},
            'palette': {'emit_enabled': True, 'renderer': 'emotiscope_v1.1', 'host_pixel_stream_required': False,
                        'din_a': 'P601', 'din_b': 'P604', 'pixels_per_din': 80,
                        'pair_fault': 0, 'emit_errors': 0, 'completed_generation': 100,
                        'pair_frame_crc': 1234, 'brightness': 100}}


def test_valid_identified_but_not_admitted_observation():
    row = sample()
    row['identity']['accepted'] = False
    assert lane.validate_titan(row, 'expected', 100) == row
    # Build + UID + fresh native telemetry are checked independently. This
    # grants no programming/control admission from the broker's boolean.


@pytest.mark.parametrize('path,value', [
    (('topic_mono', 'pdm'), 93), (('topic_mono', 'identity'), 101),
    (('host_mono',), 96), (('quiesced',), True),
    (('identity', 'uid'), 'wrong'), (('identity', 'build'), 'wrong'),
    (('identity', 'identified'), False), (('identity', 'runtime_kind'), 'replay'),
    (('identity', 'contract'), 'wrong'), (('pdm', 'rate_locked'), 0),
    (('palette', 'emit_enabled'), False), (('palette', 'pair_fault'), 1),
    (('palette', 'emit_errors'), 1), (('palette', 'host_pixel_stream_required'), True),
    (('palette', 'pixels_per_din'), 160), (('palette', 'din_b'), 'P603'),
])
def test_bad_telemetry_refused(path, value):
    row = sample(); obj = row
    for key in path[:-1]: obj = obj[key]
    obj[path[-1]] = value
    with pytest.raises(RuntimeError): lane.validate_titan(row, 'expected', 100)


def advancing():
    rows = []
    for i in range(3):
        row = sample(); row['host_mono'] += i
        row['topic_mono'] = {k: v + i for k, v in row['topic_mono'].items()}
        row['pdm']['ap_hops'] += i * 200
        row['palette']['completed_generation'] += i * 100
        row['palette']['pair_frame_crc'] += i
        rows.append(row)
    return rows


def test_progress_and_existing_historical_errors():
    facts = lane.titan_progress(advancing())
    assert facts['completed_frames_per_second'] == 100
    assert facts['historical_audio_rearms'] == 7


@pytest.mark.parametrize('failure', ['audio', 'led', 'pixels', 'restart', 'rearm', 'recovery', 'quiet', 'missing'])
def test_missing_or_frozen_or_faulted_progress(failure):
    rows = advancing()
    if failure == 'audio':
        for r in rows: r['pdm']['ap_hops'] = 200
    if failure == 'led':
        for r in rows: r['palette']['completed_generation'] = 100
    if failure == 'pixels':
        for r in rows: r['palette']['pair_frame_crc'] = 1234
    if failure == 'restart': rows[-1]['epoch'] += 1
    if failure == 'rearm': rows[-1]['pdm']['rearm_denied'] += 1
    if failure == 'recovery': rows[-1]['pdm']['lanes'][0]['recovery_count'] += 1
    if failure == 'quiet':
        for r in rows: r['pdm']['last_hop_peak'] = 0
    if failure == 'missing': rows = rows[:1]
    with pytest.raises(RuntimeError): lane.titan_progress(rows)


@pytest.mark.parametrize('action', ['build', 'flash', 'recover'])
def test_scaffold_cannot_execute_native_operations(action, tmp_path, monkeypatch):
    monkeypatch.setattr(lane, 'source_facts', lambda *a: {'state': 'SCAFFOLD'})
    def forbidden(*a, **kw): pytest.fail('unsupported operation launched a process')
    monkeypatch.setattr(lane.subprocess, 'run', forbidden)
    logs = tmp_path / 'logs'; logs.mkdir()
    ctx = SimpleNamespace(run_dir=tmp_path, logs_dir=logs)
    result = lane.PrismLaneAdapter().execute({'inputs': {'lane': 'titan', 'source': str(tmp_path), 'action': action}}, {}, ctx)
    assert result['ok'] is False and result['retryable'] is False
    assert 'No native firmware' in result['error_summary']


def test_dualmcu_cannot_use_standard_emotiscope(tmp_path, monkeypatch):
    monkeypatch.setattr(lane, 'source_facts', lambda *a: {})
    monkeypatch.setattr(lane, 'observe_titan', lambda *a: pytest.fail('wrong hardware path'))
    logs = tmp_path / 'logs'; logs.mkdir()
    result = lane.PrismLaneAdapter().execute({'inputs': {'lane': 'dualmcu', 'source': str(tmp_path), 'action': 'observe'}}, {}, SimpleNamespace(run_dir=tmp_path, logs_dir=logs))
    assert not result['ok'] and 'wired SPI' in result['error_summary']


@pytest.mark.parametrize('fault', ['script_suffix', 'flag_suffix', 'directory', 'identified', 'source', 'schema'])
def test_recovery_mismatch_never_restarts(fault, tmp_path, monkeypatch):
    owner = tmp_path / 'owner'; owner.mkdir()
    donor = tmp_path / 'donor'
    row = sample(); row['identity'].update(source='source', schema_sha256='schema')
    command = f'/usr/bin/python {donor}/tools/serial-studio/titan_broker.py run --evidence {owner} --continuous-output'
    if fault == 'script_suffix': command = command.replace('.py ', '.py.old ')
    if fault == 'flag_suffix': command += '-disabled'
    if fault == 'directory': command = command.replace(str(owner), str(tmp_path / 'other'))
    if fault == 'identified': row['identity']['identified'] = False
    if fault == 'source': row['identity']['source'] = 'wrong'
    if fault == 'schema': row['identity']['schema_sha256'] = 'wrong'
    (owner / 'live-stats.json').write_text(json.dumps(row))
    plist = tmp_path / 'Library/LaunchAgents/com.spectrasynq.titan-broker.plist'
    plist.parent.mkdir(parents=True); plist.touch()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(lane.plistlib, 'load', lambda f: {'Label': 'com.spectrasynq.titan-broker',
                        'WorkingDirectory': str(donor), 'EnvironmentVariables': {'TITAN_BROKER_EVIDENCE': str(owner)}})
    monkeypatch.setattr(lane, 'titan_build_binding', lambda c: {'build_id': 'expected', 'source_pin': 'source', 'live_schema': {'sha256': 'schema'}})
    monkeypatch.setattr(lane.subprocess, 'check_output', lambda args, **kw: 'pid = 123\n' if args[0] == 'launchctl' else command)
    monkeypatch.setattr(lane.subprocess, 'run', lambda *a, **kw: pytest.fail('mismatch restarted owner'))
    with pytest.raises(RuntimeError):
        lane.recover_titan_owner({'lane': 'titan', 'owner_dir': str(owner), 'donor_source': str(donor)}, None, {})


@pytest.mark.parametrize('local_input', ['core/local.h', 'docs/contracts/titan-emotiscope-spectrum-defaults-v1.json'])
def test_untracked_build_header_changes_identity(tmp_path, local_input):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    (tmp_path / 'core').mkdir(); (tmp_path / 'core/main.cpp').write_text('int main(){}')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture'], cwd=tmp_path, check=True)
    local = tmp_path / local_input; local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text('1')
    before = lane.donor_identity(tmp_path)
    local.write_text('2')
    after = lane.donor_identity(tmp_path)
    assert before != after and local_input in after['inputs']


@pytest.mark.parametrize('ignore_term', [False, True])
def test_timeout_kills_compiler_child(tmp_path, ignore_term):
    child = ('import time,pathlib,signal; ' + ('signal.signal(signal.SIGTERM,signal.SIG_IGN); ' if ignore_term else '') +
             'pathlib.Path("ready").touch(); time.sleep(0.8); pathlib.Path("escaped").write_text("bad")')
    parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); time.sleep(10)'
    with (tmp_path / 'log').open('w') as log:
        with pytest.raises(subprocess.TimeoutExpired):
            lane.run_command([sys.executable, '-c', parent], cwd=tmp_path, stdout=log, timeout=.15)
    time.sleep(.9)
    assert (tmp_path / 'ready').exists(), 'Child did not start; timeout test inconclusive'
    assert not (tmp_path / 'escaped').exists()


def bench_context(tmp_path, monkeypatch, *, scenario='valid', kind='dualmcu', action='bench-build'):
    source = tmp_path / ('Kx-Titan' if kind == 'titan' else 'K1-DualMCU'); (source / 'scripts').mkdir(parents=True)
    (source / 'scripts/bench.py').write_text('# lane-owned entry\n')
    run = tmp_path / 'run'; logs = run / 'logs'; logs.mkdir(parents=True)
    facts = {'source': {'tracked_files': ['scripts/bench.py']}}
    identity = {'commit': 'fixture', 'inputs': {'scripts/bench.py': 'fixture'}}
    identities = iter([identity, {}] if scenario == 'changed' else [identity, identity])
    monkeypatch.setattr(lane, 'donor_identity', lambda _: next(identities))

    def execute(argv, **kwargs):
        assert argv[:2] == [sys.executable, '-B']
        assert str(source / 'scripts/bench.py') in argv
        assert '--output' in argv and '--donor-source' not in argv
        output = Path(argv[argv.index('--output') + 1]); output.mkdir(parents=True)
        assert output.is_relative_to(source)
        command_log = output / 'execution.log'; command_log.write_text('executed fixture\n')
        if scenario != 'no_receipt':
            artifact_name = 'firmware.elf' if kind == 'titan' else 'build/firmware.elf'
            record = {'schema': 'prism.operation.v1', 'classification': 'BENCH_ONLY_UNCERTAIN_LEGACY', 'returncode': 0,
                      'operation': 'build', 'product_admission': False, 'device_proof': False,
                      'artefacts': {artifact_name: lane.hashlib.sha256(b'fixture ELF').hexdigest()},
                      'commands': [{'argv': ['fixture'], 'returncode': 0, 'log': 'execution.log',
                                    'log_sha256': lane.sha(command_log)}]}
            if scenario == 'wrong_operation': record['operation'] = 'verify'
            if scenario == 'false_admission': record['product_admission'] = True
            if scenario == 'device_claim': record['device_proof'] = True
            if scenario == 'receipt_failed': record['returncode'] = 1
            if scenario == 'unclassified': record['classification'] = 'PRODUCT'
            if scenario == 'unknown_schema': record['schema'] = 'outcome.PASS'
            if scenario == 'artifact_drift': record['artefacts'][artifact_name] = '0' * 64
            if scenario == 'missing_declared': record['artefacts']['missing.hex' if kind == 'titan' else 'build/missing.hex'] = '0' * 64
            if scenario == 'log_drift': record['commands'][0]['log_sha256'] = '0' * 64
            if kind == 'titan':
                nested = output / ('build/receipt.json' if action == 'bench-build' else 'checks/receipt.json')
                nested.parent.mkdir(exist_ok=True)
                build_id = 'b' * 64
                child = ({'pass': True, 'build_id': build_id, 'artifacts': record['artefacts']}
                         if action == 'bench-build' else
                         {'schema': 'titan-adapter-checks.v1', 'exit_code': 0, 'hardware_tested': False})
                if scenario == 'nested_failed_build': child['pass'] = False
                if scenario == 'nested_wrong_build': child['build_id'] = 'c' * 64
                if scenario == 'nested_wrong_artifacts': child['artifacts'] = {}
                nested.write_text(json.dumps(child))
                record = {'schema': 'titan-bench-execution.v1', 'classification': 'BENCH_ONLY_GPL_OR_UNCERTAIN',
                          'operation': 'build' if action == 'bench-build' else 'test', 'exit_code': 0,
                          'product_admitted': False, 'hardware_access': False, 'artifacts': record['artefacts'], 'build_id': build_id,
                          'build_receipt_sha256' if action == 'bench-build' else 'checks_receipt_sha256': lane.sha(nested)}
                if scenario == 'nested_drift': nested.write_text('{}')
                if scenario == 'nested_device_claim':
                    nested.write_text(json.dumps({'schema': 'titan-adapter-checks.v1', 'exit_code': 0, 'hardware_tested': True}))
                    record['checks_receipt_sha256'] = lane.sha(nested)
            (output / 'receipt.json').write_text(json.dumps(record))
        if scenario != 'no_firmware':
            (output / 'build').mkdir(exist_ok=True)
            (output / 'build/firmware.elf').write_bytes(b'fixture ELF')
        return SimpleNamespace(returncode=1 if scenario == 'failed' else 0)

    monkeypatch.setattr(lane, 'run_command', execute)
    cfg = {'source': str(source), 'lane': kind, 'action': action, 'target': 'rt1062_production'}
    return cfg, SimpleNamespace(run_dir=run, logs_dir=logs), facts


def test_lane_owned_bench_build_is_distinct_from_product(tmp_path, monkeypatch):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch)
    lane.lane_bench(cfg, ctx, facts)
    assert facts['returncode'] == 0
    assert facts['qualification'].startswith('BENCH_ONLY:')
    assert facts['binaries'][0]['sha256'] == lane.sha(Path(facts['binaries'][0]['path']))
    assert facts['lane_receipts']


@pytest.mark.parametrize('scenario', ['no_receipt', 'no_firmware', 'changed', 'failed',
                                     'wrong_operation', 'false_admission', 'device_claim',
                                     'receipt_failed', 'unclassified', 'unknown_schema', 'artifact_drift',
                                     'missing_declared', 'log_drift'])
def test_lane_bench_cannot_pass_without_execution_artifacts(tmp_path, monkeypatch, scenario):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch, scenario=scenario)
    with pytest.raises(RuntimeError):
        lane.lane_bench(cfg, ctx, facts)


@pytest.mark.parametrize('fault', ['untracked', 'symlink', 'missing', 'wrong_target'])
def test_bench_dispatch_refuses_unbound_entry_without_execution(tmp_path, monkeypatch, fault):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch)
    script = Path(cfg['source']) / 'scripts/bench.py'
    if fault == 'untracked': facts['source']['tracked_files'] = []
    if fault == 'missing': script.unlink()
    if fault == 'symlink':
        script.unlink(); script.symlink_to(tmp_path / 'outside.py')
    if fault == 'wrong_target': cfg.update(lane='dualmcu', target='s3_audio_renderer')
    monkeypatch.setattr(lane, 'run_command', lambda *a, **kw: pytest.fail('invalid entry launched'))
    with pytest.raises(RuntimeError): lane.lane_bench(cfg, ctx, facts)


def test_diagnosis_has_no_hardware_side_effects(tmp_path, monkeypatch):
    facts = {'source': {'core_tag': 'v0.2.0'}}
    monkeypatch.setattr(lane.subprocess, 'run', lambda *a, **kw: pytest.fail('diagnosis executed a process'))
    lane.lane_diagnosis({'source': str(tmp_path)}, facts)
    assert facts['capabilities']['native_product_deployment'] is False
    assert len(facts['remaining']) == 3


@pytest.mark.parametrize('action', ['bench-build', 'regression'])
def test_titan_receipts_bind_nested_execution(tmp_path, monkeypatch, action):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch, kind='titan', action=action)
    lane.lane_bench(cfg, ctx, facts)
    assert len(facts['lane_receipts']) == 2
    assert Path(facts['lane_output']).is_relative_to(Path(cfg['source']))


@pytest.mark.parametrize('action', ['bench-build', 'regression'])
def test_titan_changed_nested_execution_refused(tmp_path, monkeypatch, action):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch, kind='titan', action=action, scenario='nested_drift')
    with pytest.raises(RuntimeError, match='nested execution receipt'):
        lane.lane_bench(cfg, ctx, facts)


def test_titan_regression_cannot_claim_device_proof(tmp_path, monkeypatch):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch, kind='titan', action='regression', scenario='nested_device_claim')
    with pytest.raises(RuntimeError, match='host scope'):
        lane.lane_bench(cfg, ctx, facts)


@pytest.mark.parametrize('scenario', ['nested_failed_build', 'nested_wrong_build', 'nested_wrong_artifacts'])
def test_titan_build_requires_successful_consistent_child(tmp_path, monkeypatch, scenario):
    cfg, ctx, facts = bench_context(tmp_path, monkeypatch, kind='titan', scenario=scenario)
    with pytest.raises(RuntimeError, match='nested build failed or differs'):
        lane.lane_bench(cfg, ctx, facts)
