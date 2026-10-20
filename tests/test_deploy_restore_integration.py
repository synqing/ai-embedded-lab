"""Offline production-linked restoration tests. No target or installed service access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import tempfile
import threading

import pytest

SCRIPTS = Path('/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts')
spec = importlib.util.spec_from_file_location('deployment_restoration', SCRIPTS / 'deploy_admission.py')
admission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admission)
PYTHON = '/tmp/wp02-py313/bin/python'


def bound_files(tmp_path):
    old = tmp_path / 'prior.json'
    old.write_text(json.dumps({'uid': admission.UID, 'build': 'prior', 'schema_sha256': 'schema',
                              'ops': ['emotiscope_get', 'emotiscope_patch']}))
    digest = hashlib.sha256(old.read_bytes()).hexdigest()
    plist = tmp_path / 'broker.plist'
    plist.write_bytes(plistlib.dumps({'EnvironmentVariables': {
        'TITAN_ADMISSION_SOURCE': str(old), 'TITAN_ADMISSION_SHA256': digest}}))
    return old, digest, plist


def test_prior_binding_rejects_changed_original_admission(tmp_path):
    old, digest, plist = bound_files(tmp_path)
    assert admission.prior_binding(plist, admission.UID)['PRIOR_BUILD'] == 'prior'
    old.write_text(old.read_text() + ' ')
    with pytest.raises(admission.Refusal, match='hash mismatch'):
        admission.prior_binding(plist, admission.UID)


@pytest.mark.parametrize('stage,readiness,bootstrap,stop,expected_rc,starts', [
    ('prewrite', 0, 0, 0, 0, 1),
    ('destination', 0, 0, 0, 0, 1),
    ('unknown', 0, 0, 0, 2, 2),
    ('destination', 1, 0, 0, 2, 2),
    ('destination', 0, 1, 0, 2, 2),
    ('prewrite', 0, 0, 1, 2, 0),
])
def test_real_restore_shell_uses_stage_identity_and_no_duplicate_owner(tmp_path, stage, readiness, bootstrap, stop, expected_rc, starts):
    old, digest, plist = bound_files(tmp_path)
    scripts = tmp_path / 'scripts'; scripts.mkdir()
    # Production source copied unchanged. All system service/process tools below
    # are shell functions with state solely in this temporary test directory.
    (scripts / 'deploy_restore.sh').write_text((SCRIPTS / 'deploy_restore.sh').read_text().replace('SECONDS + 30', 'SECONDS + 1'))
    (scripts / 'deploy_admission.py').write_bytes((SCRIPTS / 'deploy_admission.py').read_bytes())
    wrapper = tmp_path / 'python'
    wrapper.write_text(f'''#!/bin/bash
if [ "$2" = broker-ready ]; then
  printf '%s\\n' "$*" >> '{tmp_path}/readiness'
  exit {readiness}
fi
exec '{PYTHON}' "$@"
'''); wrapper.chmod(0o700)
    harness = tmp_path / 'harness.sh'
    harness.write_text(f'''#!/bin/bash
set -u
HERE='{scripts}'
PY='{wrapper}'
PLIST='{plist}'
OUT='{tmp_path}/operation'
LOG='{tmp_path}/log'
UID_EXPECTED='{admission.UID}'
U=gui/test
log() {{ echo "$*" >> "$LOG"; }}
launchctl() {{
 echo "$1" >> '{tmp_path}/calls'
 if [ "$1" = bootout ]; then
   [ {stop} = 0 ] || return 1
   rm -f '{tmp_path}/running'; return 0
 fi
 [ ! -e '{tmp_path}/running' ] || {{ echo DUPLICATE >> "$LOG"; return 99; }}
 touch '{tmp_path}/running'
 return {bootstrap}
}}
pgrep() {{ test -e '{tmp_path}/running'; }}
sleep() {{ :; }}
plutil() {{ return 0; }}
. "$HERE/deploy_restore.sh"
save_plist_admission || exit 97
trap on_exit EXIT
trap on_term TERM
trap on_int INT
touch '{tmp_path}/running'
stop_broker || exit 2
case '{stage}' in
 destination) EXPECTED_BUILD=destination; EXPECTED_PROTOCOL=native;;
 unknown) EXPECTED_BUILD='';;
esac
broker_restore || exit 2
''')
    run = subprocess.run(['/bin/bash', str(harness)], capture_output=True, text=True, timeout=10,
                         env={'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path)})
    assert run.returncode == expected_rc, (run.stdout, run.stderr)
    calls = (tmp_path / 'calls').read_text().splitlines()
    assert calls.count('bootstrap') == starts
    assert 'DUPLICATE' not in (tmp_path / 'log').read_text()
    if stage != 'unknown' and starts and bootstrap == 0:
        reads = (tmp_path / 'readiness').read_text().splitlines()
        expected = 'prior' if stage == 'prewrite' else 'destination'
        assert all(f'--build {expected} --protocol ' in line for line in reads)
    if expected_rc:
        assert plist.read_bytes() == (tmp_path / 'operation.prior-broker.plist').read_bytes()


class FakeSocket:
    def __init__(self, directory, handler):
        self.path = str(Path(directory) / 'sock')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path); self.server.listen(1)
        self.requests = []
        self.error = None
        def serve():
            try:
                self.server.settimeout(4)
                conn, _ = self.server.accept()
                with conn, conn.makefile('rwb') as stream:
                    while line := stream.readline():
                        request = json.loads(line); self.requests.append(request)
                        stream.write((json.dumps(handler(request)) + '\n').encode()); stream.flush()
            except Exception as exc:
                self.error = exc
        self.thread = threading.Thread(target=serve, daemon=True); self.thread.start()
    def close(self):
        self.thread.join(5); self.server.close()
        assert not self.thread.is_alive()
        if self.error: raise self.error


@pytest.mark.parametrize('protocol', ['legacy', 'native'])
@pytest.mark.parametrize('failure', [None, 'wrong_identity', 'fault', 'cached', 'wrong_boot'])
def test_actual_query_socket_checks_protocol_fresh_identity_health_and_settings(protocol, failure):
    bound = {'uid': admission.UID, 'build': 'installed'}
    if protocol == 'native': bound['protocol'] = admission.NATIVE_PROTOCOL
    def reply(req):
        op = req['op']
        if op == 'hello': return {'ok': True, 'session': 'session', 'bound': bound}
        assert req['session'] == 'session'
        uid = 'wrong' if failure == 'wrong_identity' else admission.UID
        if op == 'native_identity': return {'ok': True, 'identity': {'uid': uid, 'source_id': 'installed'}}
        if op in ('native_health', 'legacy_health'):
            return {'ok': True, 'cached': failure == 'cached', 'faults': 1 if failure == 'fault' else 0,
                    'completed_count': 12, 'boot': 4, 'info': {'uid': uid, 'build': 'installed', 'boot_id': 4}}
        if op == 'native_status': return {'ok': True, 'boot': 0 if failure == 'wrong_boot' else 4, 'target_matches': True}
        assert op == 'emotiscope_get'
        return {'ok': True, 'state': {'boot_id': 5 if failure == 'wrong_boot' else 4, 'selected_board': req['board']}}
    with tempfile.TemporaryDirectory(prefix='titan-restore-', dir='/tmp') as directory:
        fake = FakeSocket(directory, reply)
        try:
            if failure:
                with pytest.raises(admission.Refusal):
                    admission.query_broker(fake.path, admission.UID, 'installed', 2, protocol)
            else:
                result = admission.query_broker(fake.path, admission.UID, 'installed', 2, protocol)
                assert result['protocol'] == protocol
        finally: fake.close()
        assert not any(r['op'].endswith(('patch', 'scene', 'global', 'durable')) for r in fake.requests)
        if protocol == 'legacy': assert not any(r['op'].startswith('native') for r in fake.requests)


@pytest.mark.parametrize('failure', ['set', 'lint'])
def test_destination_plist_failure_restores_exact_prior_bytes(tmp_path, failure):
    _, _, plist = bound_files(tmp_path)
    original = plist.read_bytes()
    helper = tmp_path / 'restore.sh'
    # Only the external PlistBuddy boundary is replaced in this temporary copy.
    helper.write_text((SCRIPTS / 'deploy_restore.sh').read_text().replace('/usr/libexec/PlistBuddy', 'fake_plistbuddy'))
    harness = tmp_path / 'run.sh'
    harness.write_text(f'''set -u
HERE='{SCRIPTS}'
PY='{PYTHON}'
PLIST='{plist}'
OUT='{tmp_path}/operation'
LOG='{tmp_path}/log'
UID_EXPECTED='{admission.UID}'
ADM_ABS='{tmp_path}/destination.json'
ADM_SHA=changed
U=gui/test
log() {{ echo "$*" >> "$LOG"; }}
fake_plistbuddy() {{ echo mutated > "$PLIST"; [ '{failure}' != set ]; }}
plutil() {{ [ "$(cat "$PLIST")" != mutated ]; }}
. '{helper}'
save_plist_admission || exit 97
if set_destination_admission; then exit 98; fi
restore_saved_admission || exit 99
''')
    result = subprocess.run(['/bin/bash', str(harness)], env={'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path)},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert plist.read_bytes() == original


def settings_fixture(tmp_path, protocol):
    import copy
    if protocol == 'native':
        states = {'boot': 7, 'target_matches': True, 'global_revision': 22, 'brightness': 0, 'output_limit': 0.0,
                  'scenes': [{'revision': 30 + i, 'mode': 1 if i == 0 else 7, 'palette': i,
                              'gain': 0.0 if i == 0 else .5, 'response_ms': 40.0 + i} for i in (0, 1)]}
        schema = admission.HEALTH_SCHEMA
        ops = list(admission.NATIVE_OPS)
    else:
        codec, _ = admission.legacy_codec()
        states = []
        for board in (0, 1):
            state = {'version': 8, 'boot_id': 7, 'revision': 22 + board, 'selected_board': board,
                     'board_capabilities': 511, 'schema_sha256': 'schema'}
            for field, (name, kind) in codec.FIELDS.items():
                if name == 'board': continue
                key = 'mode' if name == 'current_mode' else name
                if kind == codec.KIND_F32:
                    lower, upper = codec.FLOAT_RANGES.get(field, (0., 1.))
                    state[key] = lower
                elif kind == codec.KIND_BOOL: state[key] = False
                elif name == 'palette': state[key] = 1
                elif name == 'current_mode': state[key] = 32 if board == 0 else 18
                else: state[key] = 0
            states.append(state)
        schema, ops = 'schema', list(admission.LEGACY_OPS)
    identity = {'uid': admission.UID, 'build': 'exact-build', 'schema': schema, 'protocol': protocol, 'source': 'exact-source'}
    record = dict(uid=identity['uid'], build=identity['build'], schema_sha256=schema, ops=ops)
    if protocol == 'native': record['protocol'] = admission.NATIVE_PROTOCOL
    path = tmp_path / 'admission.json'; path.write_text(json.dumps(record))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return states, identity, path, digest


@pytest.mark.parametrize('protocol', ['native', 'legacy'])
@pytest.mark.parametrize('defect', [None, 'wrong_source', 'stale', 'lost_reply', 'post_mismatch', 'wrong_capture_hash'])
def test_complete_settings_capture_restore_real_helper_no_replay(tmp_path, protocol, defect):
    import copy
    states, identity, path, digest = settings_fixture(tmp_path, protocol)
    original = copy.deepcopy(states)
    writes = []
    restoring = [False]
    def reply(req):
        op = req['op']
        if op == 'hello':
            bound = dict(uid=identity['uid'], build=identity['build'])
            if protocol == 'native': bound['protocol'] = admission.NATIVE_PROTOCOL
            return {'ok': True, 'session': 's', 'bound': bound}
        assert req['session'] == 's'
        source = 'wrong' if restoring[0] and defect == 'wrong_source' else identity['source']
        if op == 'native_identity': return {'ok': True, 'identity': {'uid': identity['uid'], 'source_id': identity['build'], 'core_commit': source}}
        if op == 'legacy_health': return {'ok': True, 'info': {'uid': identity['uid'], 'build': identity['build'], 'source': source, 'schema_sha256': identity['schema'], 'boot_id': 7}}
        if op == 'native_status': return dict(ok=True, **copy.deepcopy(states))
        if op == 'emotiscope_get':
            assert req['state_version'] == 8
            return {'ok': True, 'state': copy.deepcopy(states[req['board']])}
        writes.append(copy.deepcopy(req))
        if defect == 'stale': return {'ok': False, 'error': 'stale'}
        if defect == 'lost_reply': return {'ok': False, 'error': 'transport_timeout_ambiguous'}
        if op == 'native_scene':
            board = req['scene']; assert req['expected_revision'] == states['scenes'][board]['revision']
            assert req['boot'] == 7
            for k in ('mode', 'palette', 'gain', 'response_ms'): states['scenes'][board][k] = req[k]
            states['scenes'][board]['revision'] += 1
        elif op == 'native_global':
            assert req['expected_revision'] == states['global_revision']
            states.update(brightness=req['brightness'], output_limit=req['output_limit'])
            states['global_revision'] += 1
        else:
            assert op == 'emotiscope_patch' and req['state_version'] == 8 and req['boot_id'] == 7
            board = req['fields']['board']; assert req['revision'] == states[board]['revision']
            for k, value in req['fields'].items():
                if k != 'board': states[board]['mode' if k == 'current_mode' else k] = value
            states[board]['revision'] += 1
        if defect == 'post_mismatch':
            if protocol == 'native': states['brightness'] = 99
            else: states[0]['brightness'] = .7
        return {'ok': True}
    capture = tmp_path / 'original-settings.json'
    with tempfile.TemporaryDirectory(prefix='settings-cap-', dir='/tmp') as directory:
        server = FakeSocket(directory, reply)
        try: admission.capture_settings(server.path, path, digest, capture)
        finally: server.close()
    capture_sha = hashlib.sha256(capture.read_bytes()).hexdigest()
    saved = json.loads(capture.read_text())
    assert saved['composition'] == admission.user_composition(protocol, original)
    assert writes == []
    # Preserve the fresh boot/revisions, but change every writable setting to
    # another valid value. The helper must restore all fields, including zeros.
    if protocol == 'native':
        states.update(brightness=255, output_limit=1.)
        for scene in states['scenes']: scene.update(gain=1.2, response_ms=250.)
    else:
        codec, _ = admission.legacy_codec()
        for board, state in enumerate(states):
            for field, (name, kind) in codec.FIELDS.items():
                if field in codec.UNSUPPORTED_PALETTE_FIELDS or name == 'board' or (board == 1 and field in (19, 20)): continue
                key = 'mode' if name == 'current_mode' else name
                if kind == codec.KIND_F32: state[key] = codec.FLOAT_RANGES.get(field, (0., 1.))[1]
                elif kind == codec.KIND_BOOL: state[key] = True
                elif name == 'current_mode': state[key] = 1
                elif name == 'palette': state[key] = 2
                else: state[key] = codec.U32_MAX[field]
    restoring[0] = True
    with tempfile.TemporaryDirectory(prefix='settings-put-', dir='/tmp') as directory:
        if defect == 'wrong_capture_hash':
            with pytest.raises(admission.Refusal, match='hash mismatch'):
                admission.restore_settings(str(Path(directory) / 'nonexistent'), path, digest, capture, 'wrong')
            assert writes == []
            return
        server = FakeSocket(directory, reply)
        try:
            if defect:
                with pytest.raises(admission.Refusal): admission.restore_settings(server.path, path, digest, capture, capture_sha)
            else:
                result = admission.restore_settings(server.path, path, digest, capture, capture_sha)
                assert result['restored'] is True and result['replayed'] is False
                assert admission.user_composition(protocol, states) == saved['composition']
        finally: server.close()
    if defect == 'wrong_source': assert writes == []
    if defect in ('stale', 'lost_reply'): assert len(writes) == 1
    assert all(r['op'] not in ('native_durable', 'patch') for r in writes)


def test_ael_return_gateway_passes_hash_bound_original_settings(tmp_path):
    from ael.adapters import prism_bench_trial as bench
    build = tmp_path / 'build'; build.mkdir()
    image = build / 'rtthread.hex'; image.write_bytes(b'test-owned image bytes')
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    (build / 'receipt.json').write_text(json.dumps({'pass': True, 'artifacts': {'rtthread.hex': image_sha}}))
    admitted = tmp_path / 'admission.json'; admitted.write_text(json.dumps({'hex_sha256': image_sha}))
    settings = tmp_path / 'outbound.prior-settings.json'; settings.write_text('{"test_only":"full-state-placeholder"}')
    digest = hashlib.sha256(settings.read_bytes()).hexdigest()
    manifest = {'recovery': {'deployment': {'build_dir': str(build), 'admission': str(admitted)}}}
    binding = {'path': str(settings), 'sha256': digest}
    argv = bench.deployment_argv(manifest, image, 'donor-recovery', tmp_path / 'unused-output', restore_settings=binding)
    assert argv[-4:] == ['--restore-settings', str(settings), '--restore-settings-sha', digest]
    assert argv[1].endswith('deploy_titan_image.sh')
    settings.write_text('{"changed":true}')
    with pytest.raises(Exception, match='original settings capture changed'):
        bench.deployment_argv(manifest, image, 'donor-recovery', tmp_path / 'unused-output', restore_settings=binding)


def test_non_writable_legacy_difference_refuses_before_any_patch(tmp_path, monkeypatch):
    import copy
    states, identity, path, digest = settings_fixture(tmp_path, 'legacy')
    saved = {'schema': 'titan.deployment.settings/1', 'identity': identity,
             'composition': admission.user_composition('legacy', states), 'raw': copy.deepcopy(states),
             'codec_sha256': admission.legacy_codec()[1]}
    capture = tmp_path / 'settings.json'; capture.write_text(json.dumps(saved))
    captured_sha = hashlib.sha256(capture.read_bytes()).hexdigest()
    states[0]['color'] = .25  # intentionally unsupported fixed HSV field
    class OfflineConnection:
        def __init__(self, socket_path, expected):
            self.identity = identity; self.protocol = 'legacy'; self.boot = 7
        def states(self): return copy.deepcopy(states)
        def call(self, *args, **kwargs): raise AssertionError('must refuse before any patch')
        def close(self): pass
    monkeypatch.setattr(admission, 'SettingsConnection', OfflineConnection)
    with pytest.raises(admission.Refusal, match='non-writable legacy control changed: color'):
        admission.restore_settings('not-a-real-socket', path, digest, capture, captured_sha)
