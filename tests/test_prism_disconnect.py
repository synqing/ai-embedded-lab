"""Explicit emulated serial owner; these cases never claim physical evidence."""
import copy
import json
import struct

import pytest

from ael import prism_disconnect as d
from ael import prism_native as native
from ael.prism_drive import Refusal


class Owner:
    def __init__(self, fault=None):
        self.time = 1.0
        self.opened = True
        self.closed = 0
        self.reopened = 0
        self.calls = []
        self.fault = fault
        self.manifest = {'port': '/dev/explicit-test-double', 'source_binding_hash': 'a' * 64}
        self.info = dict(uid=native.UID, schema_sha256=native.SCHEMA, build_source_sha256='a'*64,
                         boot_id=7, clock_hz=1000000000, initialisation_failed=False,
                         output_timeouts=0, capture_errors=[0, 0], output_last_fsp_error=0,
                         capture_clock_rejections=0, capture_restart_attempts=0,
                         output_recovery_attempts=0, usb_disconnect_events=10, usb_dtr=True)
        self.drive = dict(boot_id=7, active=False, phase='idle', queue_depth=0, weight=0,
                          live_source=0, disconnects=10, trial=9, accepted=42, opens=9,
                          initial_state_resets=9)
        self.snapshots = 0

    def close(self):
        self.closed += 1
        self.opened = self.fault == 'close-noop'
        return self.owner_state()

    def reopen(self):
        assert not self.opened
        self.reopened += 1
        self.opened = True
        if self.fault != 'no-device-disconnect':
            self.info['usb_disconnect_events'] += 1
        self.drive['disconnects'] += 1
        self.drive['live_source'] = 0
        mutations = {
            'wrong-uid': ('uid', '0'*32), 'wrong-build': ('build_source_sha256', 'b'*64),
            'wrong-schema': ('schema_sha256', 'c'*64), 'reset': ('boot_id', 8),
            'clock-changed': ('clock_hz', 900000000), 'capture-fault': ('capture_errors', [1, 0]),
            'output-fault': ('output_timeouts', 1), 'capture-restart': ('capture_restart_attempts', 1),
            'dtr-false': ('usb_dtr', False), 'two-disconnects': ('usb_disconnect_events', 12)}
        if self.fault in mutations:
            key, value = mutations[self.fault]
            self.info[key] = value
        drive_mutations = {'source-D': ('live_source', 1), 'revived': ('active', True),
                           'queued': ('queue_depth', 1), 'weight': ('weight', .1),
                           'changed-trial': ('trial', 10), 'accepted-record': ('accepted', 43),
                           'reopened-trial': ('opens', 10), 'reset-programme': ('initial_state_resets', 10),
                           'missing-disconnect': ('disconnects', 10)}
        if self.fault in drive_mutations:
            key, value = drive_mutations[self.fault]
            self.drive[key] = value
        if self.fault == 'open-error':
            raise OSError('Emulated owner conflict; no retry')
        state = self.owner_state()
        if self.fault == 'different-port':
            state['port'] = '/dev/wrong-device'
        if self.fault == 'rts-reset-line':
            state['rts'] = True
        return state

    def owner_state(self):
        return dict(port=self.manifest['port'], is_open=self.opened, dtr=True, rts=False)

    def pause(self, seconds):
        self.time += seconds if self.fault != 'short-wait' else seconds / 2
        if self.fault == 'deadline':
            self.time += 121
        if self.reopened and self.fault == 'late-replay':
            self.drive['active'] = True

    def exchange(self, opcode, payload=b''):
        assert self.opened, 'No exchange may run during the disconnected interval'
        self.calls.append((opcode, payload))
        self.time += .001
        if opcode == 1:
            return json.dumps(self.info).encode()
        if opcode == d.STATUS:
            assert payload == struct.pack('<I', 7)
            return json.dumps(self.drive).encode()
        if opcode == d.SELECT:
            assert payload == struct.pack('<II', 7, 1)
            self.drive['live_source'] = 1
            return b''
        if opcode == 0x50520001:
            assert payload == native.bind_payload(7)
            return b''
        if opcode == 23:
            self.snapshots += 1
            body = bytearray(1184)
            struct.pack_into('<I', body, 0, 0x53564C54)
            struct.pack_into('<HH', body, 4, 1, 25)
            struct.pack_into('<I', body, 624, 41431)
            body[728:744] = bytes.fromhex(native.UID)
            body[744:776] = bytes.fromhex('a'*64)
            body[776:808] = bytes.fromhex(native.SCHEMA)
            time_us = int(self.time*1e6)
            epoch = 2 if self.reopened and self.fault == 'epoch' else 1
            if self.reopened and self.fault == 'stalled-capture':
                time_us = 0
            for pos, value in ((8, self.snapshots), (16, epoch), (32, time_us),
                               (40, time_us), (48, time_us*12800//1000000)):
                struct.pack_into('<Q', body, pos, value)
            for pos, value in ((608, time_us//5000), (612, int(bool(self.reopened and self.fault == 'rejected'))),
                               (820, 0 if self.reopened and self.fault == 'render-reset' else time_us//10000)):
                struct.pack_into('<I', body, pos, value)
            return body
        if opcode == d.TRANSMITTER:
            tx = dict(schema='prism.titan.transmitter.v2', first_fault=0, failures=0,
                      last_fsp_error=0, pattern_requested=0, wire_reset_completions=int(self.time*100))
            if self.reopened and self.fault == 'stalled-wire':
                tx['wire_reset_completions'] = 0
            if self.reopened and self.fault == 'tx-fault':
                tx['first_fault'] = 1
            if self.reopened and self.fault == 'fixture-pattern':
                tx['pattern_requested'] = 100
            return json.dumps(tx).encode()
        raise AssertionError('Unexpected opcode: ' + str(opcode))


def run(owner, tmp_path):
    return d.execute(owner.exchange, owner.close, owner.reopen, owner.manifest,
                     {'seconds': 2}, tmp_path, copy.deepcopy(owner.info),
                     monotonic=lambda: owner.time, pause=owner.pause)


def test_actual_owner_boundaries_and_consumer_result(tmp_path):
    owner = Owner()
    result = run(owner, tmp_path)
    assert owner.closed == owner.reopened == 1
    assert result['reconnected_live_source'] == 'A'
    assert result['device_disconnect_events'] == 1
    assert result['audio_window']['analysis_samples'] > 0
    assert result['wire_reset_completion_delta'] > 0
    assert not result['optical_verified'] and result['physical_latency'] == 'UNMEASURED'
    assert not {0x50524401, 0x50524402, 0x50524404}.intersection(op for op, _ in owner.calls)
    rows = [json.loads(x) for x in (tmp_path/'titan-disconnect.jsonl').read_text().splitlines()]
    assert rows[-1]['event'] == 'result'
    closed = next(x for x in rows if x['event'] == 'owner_closed')
    reopened = next(x for x in rows if x['event'] == 'owner_reopened')
    assert reopened['host_monotonic_s'] - closed['host_monotonic_s'] >= 2


@pytest.mark.parametrize('fault', [
    'close-noop', 'no-device-disconnect', 'wrong-uid', 'wrong-build', 'wrong-schema',
    'reset', 'clock-changed', 'capture-fault', 'output-fault', 'capture-restart',
    'dtr-false', 'two-disconnects', 'source-D', 'revived', 'queued', 'weight',
    'changed-trial', 'accepted-record', 'reopened-trial', 'reset-programme',
    'missing-disconnect', 'open-error', 'different-port', 'rts-reset-line',
    'short-wait', 'deadline', 'late-replay', 'epoch', 'stalled-capture', 'rejected',
    'render-reset', 'stalled-wire', 'tx-fault', 'fixture-pattern'])
def test_negative_owner_identity_replay_and_continuity_cases(tmp_path, fault):
    owner = Owner(fault)
    with pytest.raises((Refusal, ValueError, OSError)):
        run(owner, tmp_path)
    rows = [json.loads(x) for x in (tmp_path/'titan-disconnect.jsonl').read_text().splitlines()]
    assert rows[-1]['event'] == 'failure'
    assert not any(x['event'] == 'result' for x in rows)
    assert owner.reopened <= 1
    if fault in ('wrong-uid', 'wrong-build', 'wrong-schema', 'reset'):
        assert any(x['event'] == 'identity_after' for x in rows)
        assert not any(op == 0x50520001 for op, _ in owner.calls)


@pytest.mark.parametrize('spec', [{}, {'seconds':0}, {'seconds':31}, {'seconds':True},
                                  {'seconds':float('nan')}, {'seconds':float('inf')},
                                  {'seconds':2,'reset':True}, None])
def test_prepare_refuses_before_any_owner_access(spec):
    with pytest.raises(Refusal):
        d.prepare(spec)


def test_active_initial_replay_refuses_without_close(tmp_path):
    owner = Owner()
    owner.drive['active'] = True
    with pytest.raises(Refusal):
        run(owner, tmp_path)
    assert owner.closed == 0


def test_log_is_immutable(tmp_path):
    owner = Owner()
    path = tmp_path/'titan-disconnect.jsonl'
    path.write_text('retained failure\n')
    with pytest.raises(FileExistsError):
        run(owner, tmp_path)
    assert path.read_text() == 'retained failure\n'
    assert not owner.calls


@pytest.mark.parametrize('conflict', [False, True])
def test_real_run_session_same_serial_owner_seam(monkeypatch, tmp_path, conflict):
    import base64
    import subprocess
    import zlib
    import serial
    owner = Owner()
    owner.opened = False
    ports = []
    sequences = []
    cookies = set()
    lsof_calls = []

    class EmulatedSerial:
        def __init__(self, **kwargs):
            assert kwargs['port'] is None
            self.data = b''
            self.open_count = 0
            self.timeout = kwargs['timeout']
            self.write_timeout = kwargs['write_timeout']
            ports.append(self)

        @property
        def is_open(self):
            return owner.opened

        def open(self):
            assert self.dtr is True and self.rts is False
            assert self.port == owner.manifest['port']
            self.open_count += 1
            if self.open_count == 1:
                owner.opened = True
            else:
                owner.reopen()

        def close(self):
            owner.close()

        def write(self, packet):
            assert owner.opened
            opcode, seq, cookie, size, crc, version, hcrc = struct.unpack_from('<7I', packet, 4)
            assert packet[:4] == b'K1S1' and version == 1
            assert zlib.crc32(packet[:28]) == hcrc
            assert len(packet[32:]) == size and zlib.crc32(packet[32:]) == crc
            sequences.append(seq)
            cookies.add(cookie)
            body = owner.exchange(opcode, packet[32:])
            header = b'K1R1' + struct.pack('<6I', 0, seq, cookie, len(body), 0, zlib.crc32(body))
            self.data = header + struct.pack('<I', zlib.crc32(header)) + body
            return len(packet)

        def read(self, size):
            out, self.data = self.data[:size], self.data[size:]
            return out

    def owner_inventory(argv, **kwargs):
        assert not owner.opened
        assert argv == ['lsof', '-t', owner.manifest['port']]
        assert kwargs['timeout'] == 3
        lsof_calls.append(argv)
        return subprocess.CompletedProcess(argv, 0 if conflict else 1, '987\n' if conflict else '', '')

    actual_execute = d.execute
    monkeypatch.setattr(serial, 'Serial', EmulatedSerial)
    monkeypatch.setattr(native.subprocess, 'run', owner_inventory)
    monkeypatch.setattr(d, 'execute', lambda *args: actual_execute(
        *args, monotonic=lambda: owner.time, pause=owner.pause))
    operation = tmp_path/'operation.json'
    operation.write_text(json.dumps({'disconnect_check': {'seconds': 2}}))
    if conflict:
        with pytest.raises(ValueError, match='owner appeared'):
            native.run_session(owner.manifest, tmp_path, 5, operation)
        assert ports[0].open_count == 1
        assert json.loads((tmp_path/'titan-disconnect.jsonl').read_text().splitlines()[-1])['event'] == 'failure'
    else:
        result = native.run_session(owner.manifest, tmp_path, 5, operation)
        assert result['disconnect_check']['reconnected_live_source'] == 'A'
        assert result['runtime_boot_verified'] and not result['optical_verified']
        assert ports[0].open_count == 2
    assert len(ports) == 1 and len(lsof_calls) == 1
    assert not owner.opened
    assert sequences == list(range(1, len(sequences)+1)) and len(cookies) == 1
    raw = [json.loads(x) for x in (tmp_path/'titan-native.jsonl').read_text().splitlines()]
    for row in raw:
        native.response(base64.b64decode(row['response']), row['sequence'], next(iter(cookies)))


@pytest.mark.parametrize('operation', [
    {'disconnect_check': {'seconds': 0}},
    {'disconnect_check': {'seconds': 2}, 'save': True},
    {'disconnect_check': {'seconds': 2}, 'evaluation_drive': {}},
    {'disconnect_check': {'seconds': 2}, 'completion': {}},
])
def test_run_session_refuses_invalid_operation_before_serial(monkeypatch, tmp_path, operation):
    import serial
    def forbidden(**kwargs):
        raise AssertionError('Invalid operation reached serial creation')
    monkeypatch.setattr(serial, 'Serial', forbidden)
    path = tmp_path/'invalid.json'
    path.write_text(json.dumps(operation))
    with pytest.raises((Refusal, ValueError)):
        native.run_session(Owner().manifest, tmp_path, 5, path)
