"""Fresh maintenance fixture reads: no device or system service is accessed."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import threading
from types import SimpleNamespace

import pytest

SHOW = Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001/tools/serial-studio')
sys.path.insert(0, str(SHOW))
import titan_control_server as control
from titan_broker import Broker

UID = control.TARGET_UID.decode()

@pytest.fixture
def status_lane(tmp_path, monkeypatch):
    owner = tmp_path / 'owner.json'
    owner.write_text(json.dumps({'pid': os.getpid(), 'task': 'TEST ONLY fixture status'}))
    monkeypatch.setattr(control, 'OWNER_LEASE_PATH', owner)
    monkeypatch.setenv('TITAN_LIVE_CONTROL_ADMITTED', '1')
    admission = dict(uid=UID, build='b'*64, protocol='titan-native',
        schema_sha256='replacement-health-v1', controls_persistent=False,
        durable_commit='explicit-v1', ops=list(control.NATIVE_OPS))
    (tmp_path / 'accepted-candidate.json').write_text(json.dumps(admission))
    identity = dict(uid=UID, source_id='b'*64, controls_persistent=False,
        durable_commit='explicit-v1', capabilities=dict(controls='replacement-control-v1',
        health='replacement-health-v1'))
    words = [0] * 160
    words[:4] = [4, 59, 14, 6]
    raw = struct.pack('<160I', *words)
    calls = []
    state = dict(raw=raw, boot=59)
    def exchange(op, payload):
        calls.append(op)
        if op == 0x50524200:
            return {'ok': True, 'body': json.dumps(identity).encode()}
        assert op in (0x50524201, 0x50524202)
        body = struct.pack('<4I', 1, state['boot'], int(op == 0x50524202), 1) + UID.encode() + bytes(64)
        return {'ok': True, 'body': body}
    def fixture_read(boot, epoch):
        calls.append((0x50524602, boot, epoch))
        return state['raw']
    plane = control.RestrictedControlPlane(transact=exchange, evidence=tmp_path,
        bound=admission, fixture_status_read=fixture_read)
    hello = plane.handle({'op': 'hello', 'maintenance': {
        'owner_lease_sha256': hashlib.sha256(owner.read_bytes()).hexdigest()}}, 'owner')
    assert hello['ok'] and hello['maintenance']
    req = dict(op='native_fixture_status', session=hello['session'], boot=59, epoch=14)
    return plane, req, state, calls, owner


def test_fresh_status_does_not_arm_cancel_or_save(status_lane):
    plane, req, state, calls, owner = status_lane
    reply = plane.handle(req, 'owner')
    assert reply['ok'] and reply['cached'] is False and reply['replayed'] is False
    assert bytes.fromhex(reply['raw_hex']) == state['raw']
    assert calls == [0x50524200, 0x50524201, 0x50524202, (0x50524602, 59, 14)]


@pytest.mark.parametrize('bad', ['ordinary_client', 'stale_session', 'changed_owner', 'boot',
    'epoch', 'active', 'uninitialised', 'act0', 'act1', 'act2', 'act3', 'length', 'version'])
def test_status_refuses_wrong_owner_or_active_fixture(status_lane, bad):
    plane, req, state, calls, owner = status_lane
    conn = 'owner'
    if bad == 'ordinary_client': conn = 'other'
    elif bad == 'stale_session': req['session'] = 'wrong'
    elif bad == 'changed_owner': owner.write_text('{}')
    elif bad == 'boot': state['boot'] = 60
    else:
        raw = bytearray(state['raw'])
        if bad == 'epoch': struct.pack_into('<I', raw, 8, 15)
        elif bad == 'active': struct.pack_into('<I', raw, 12, 4)
        elif bad == 'uninitialised': struct.pack_into('<I', raw, 12, 0)
        elif bad.startswith('act'): struct.pack_into('<I', raw, (72+int(bad[-1]))*4, 0x80)
        elif bad == 'length': raw = raw[:-4]
        elif bad == 'version': struct.pack_into('<I', raw, 0, 5)
        state['raw'] = bytes(raw)
    reply = plane.handle(req, conn)
    assert reply['ok'] is False
    assert not any(op in (0x50524601, 0x50524603, 0x50524604, 0x50524206) for op in calls if type(op) is int)


def test_broker_callback_has_one_fixed_opcode():
    broker = object.__new__(Broker)
    calls = []
    def exchange(op, payload, timeout):
        calls.append((op, payload))
        return {'ok': True, 'body': b'fresh raw fixture'}
    broker.transport = SimpleNamespace(_isolated_fixture_exchange=exchange)
    broker._sched = threading.Lock()
    assert broker._fixture_status_read(59, 14) == b'fresh raw fixture'
    assert calls == [(0x50524602, struct.pack('<II', 59, 14))]
    assert broker._sched.acquire(blocking=False)
    broker._sched.release()


def test_fresh_status_rebinds_after_actual_status_reports_unbound(status_lane):
    plane, req, state, calls, owner = status_lane
    plane._bound_boot = 59  # A local cache does not prove the board is still bound.
    reply = plane.handle(req, 'owner')
    assert reply['ok']
    assert 0x50524202 in calls
