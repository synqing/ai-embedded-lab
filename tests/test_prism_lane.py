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
