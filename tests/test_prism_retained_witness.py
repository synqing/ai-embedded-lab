"""Actual run_session seam with a serial test double; no physical claims."""
import base64
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import zlib

import pytest

from ael import prism_native as native
from ael.adapters import prism_bench_trial as adapter
from tests.test_prism_completion_measure import MeasureBench, healthy
from ael import prism_completion as completion


class Wire:
    def __init__(self, monkeypatch, fault=None):
        self.bench = MeasureBench()
        self.fault = fault
        self.ports = []
        self.calls = []
        self.clock = 100.
        self.cancel = SimpleNamespace(is_set=lambda: self.fault == 'cancel-active')
        owner = self

        class Serial:
            def __init__(self, **kwargs):
                assert kwargs['port'] is None
                self.timeout = kwargs['timeout']; self.write_timeout = kwargs['write_timeout']
                self.data = b''; self.opens = 0; self.closes = 0
                owner.ports.append(self)
            def open(self):
                assert self.dtr is True and self.rts is False
                self.opens += 1
            def close(self):
                self.closes += 1
            def write(self, packet):
                opcode, seq, cookie, size, crc, version, hcrc = struct.unpack_from('<7I', packet, 4)
                assert version == 1 and zlib.crc32(packet[:28]) == hcrc
                assert size == len(packet[32:]) and crc == zlib.crc32(packet[32:])
                owner.calls.append(opcode)
                owner.bench.seconds = owner.clock - 100.
                if opcode == 1:
                    info = healthy(); info['persistence_errors'] = 0
                    if owner.fault == 'bind-refused': info['initialisation_failed'] = True
                    if owner.fault == 'uid': info['uid'] = '0' * 32
                    if owner.fault == 'source': info['build_source_sha256'] = 'a' * 64
                    if owner.fault == 'info-schema': info['schema_sha256'] = '0' * 64
                    if owner.fault == 'counter': info['capture_restart_attempts'] = -1
                    if owner.fault == 'bool-counter': info['capture_restart_attempts'] = False
                    if owner.fault == 'nan-counter': info['capture_restart_attempts'] = float('nan')
                    body = json.dumps(info).encode()
                elif opcode in (24, 26):
                    body = b'{}'
                else:
                    body = owner.bench.exchange(opcode, packet[32:])
                    if opcode == native.CAPTURE_QUEUE:
                        body = bytearray(body)
                        struct.pack_into('<Q', body, 152, 23)
                        if owner.fault == 'queue-schema': struct.pack_into('<I', body, 4, 9)
                        if owner.fault == 'queue-loss': struct.pack_into('<Q', body, 48, 1)
                        body = bytes(body)
                    if opcode == 0x50524C02:
                        tx = json.loads(body)
                        if owner.fault == 'tx-schema': tx['schema'] = 'other'
                        if owner.fault == 'tx-counter': tx['wire_reset_completions'] = -1
                        if owner.fault == 'tx-bool': tx['wire_reset_completions'] = True
                        if owner.fault == 'tx-nan': tx['wire_reset_completions'] = float('nan')
                        body = json.dumps(tx).encode()
                refused = opcode == 0x50520001 and owner.fault == 'bind-refused'
                if refused:
                    body = b''
                header = b'K1R1' + struct.pack('<6I', 3 if refused else 0, seq, cookie, len(body), 0, zlib.crc32(body))
                self.data = header + struct.pack('<I', zlib.crc32(header)) + body
                if owner.fault == 'partial' and opcode == native.CAPTURE_QUEUE:
                    self.data = self.data[:42]
                if owner.fault == 'late' and opcode == native.CAPTURE_QUEUE:
                    owner.clock = 121.
                if owner.fault == 'cancel' and opcode == native.CAPTURE_QUEUE:
                    owner.fault = 'cancel-active'
                return len(packet)
            def read(self, size):
                part, self.data = self.data[:size], self.data[size:]
                if not part: owner.clock += 1.
                return part

        import serial
        monkeypatch.setattr(serial, 'Serial', Serial)
        monkeypatch.setattr(native.time, 'monotonic', lambda: owner.clock)
        monkeypatch.setattr(native.time, 'sleep', lambda seconds: setattr(owner, 'clock', owner.clock + seconds))
        monkeypatch.setattr(completion, 'uptime_ns', lambda: int(owner.clock * 1e9))

    def run(self, tmp_path, operation=None, deadline=120.):
        path = None
        if operation is not None:
            path = tmp_path / 'operation.json'; path.write_text(json.dumps(operation))
        return native.run_session({'port': '/dev/explicit-test-double', 'source_binding_hash': 'b' * 64},
                                  tmp_path, .5 if operation is None else 20, path,
                                  deadline=deadline, cancel_event=self.cancel)


def raw_rows(path):
    return [json.loads(line) for line in (path / 'titan-native.jsonl').read_text().splitlines()]


def test_generic_observation_misses_retained_queue_and_transmitter(monkeypatch, tmp_path):
    wire = Wire(monkeypatch)
    wire.run(tmp_path)
    assert 23 in wire.calls
    assert native.CAPTURE_QUEUE not in wire.calls and 0x50524C02 not in wire.calls
    assert not (tmp_path / 'titan-retained-witness.json').exists()


def test_supported_readout_keeps_first_witness_before_any_music_mutation(monkeypatch, tmp_path):
    wire = Wire(monkeypatch)
    result = wire.run(tmp_path, {'retained_witness': {}})
    assert wire.calls == [1, 23, 0x50520001, native.CAPTURE_QUEUE, 0x50524C02]
    assert len(wire.ports) == 1 and wire.ports[0].opens == wire.ports[0].closes == 1
    witness = result['retained_witness']
    assert witness['complete'] and witness['capture_queue']['preroll_blocks'] == 23
    assert not witness['host_absence_verified'] and not witness['optical_verified']
    rows = raw_rows(tmp_path)
    assert all(row['response_complete'] for row in rows)
    assert [row['sequence'] for row in rows] == [1, 2, 3, 4, 5]
    assert json.loads((tmp_path / 'titan-retained-witness.json').read_text()) == witness


def test_failed_initialisation_bind_refusal_keeps_available_first_witness(monkeypatch, tmp_path):
    # native.cpp refuses BIND status 3 after initialisation failure. Queue and
    # transmitter are then unavailable; identity/snapshot/refusal still survive.
    wire = Wire(monkeypatch, 'bind-refused')
    with pytest.raises(ValueError, match='rejection'):
        wire.run(tmp_path, {'retained_witness': {}})
    assert wire.calls == [1, 23, 0x50520001]
    assert len(wire.ports) == 1 and wire.ports[0].closes == 1
    summary = json.loads((tmp_path / 'titan-retained-witness.json').read_text())
    assert summary['identity']['initialisation_failed'] is True
    assert not summary['complete'] and summary['error']
    assert set(summary['raw_replies']) == {'snapshot'}
    assert 'snapshot' in summary and 'capture_queue' not in summary
    assert 'transmitter' not in summary
    rows = raw_rows(tmp_path)
    assert [row['opcode'] for row in rows] == wire.calls
    refused = rows[-1]
    packet = base64.b64decode(refused['response'])
    assert refused['response_complete'] and refused['error']
    assert len(packet) == 32 and struct.unpack_from('<I', packet, 4)[0] == 3


@pytest.mark.parametrize('fault', ['uid', 'source', 'info-schema', 'counter', 'bool-counter',
                                 'queue-schema', 'queue-loss', 'tx-schema', 'tx-counter', 'tx-bool', 'nan-counter', 'tx-nan'])
def test_actual_consumer_rejects_fault_and_preserves_raw(monkeypatch, tmp_path, fault):
    wire = Wire(monkeypatch, fault)
    with pytest.raises((ValueError, RuntimeError)):
        wire.run(tmp_path, {'retained_witness': {}})
    assert len(wire.ports) == 1 and wire.ports[0].closes == 1
    rows = raw_rows(tmp_path)
    assert rows and rows[-1]['response_complete']
    if fault not in ('uid', 'source', 'info-schema'):
        value = json.loads((tmp_path / 'titan-retained-witness.json').read_text())
        assert not value['complete'] and value['error']


@pytest.mark.parametrize('fault', ['partial', 'late', 'cancel'])
def test_cutoff_cancellation_and_partial_wire_evidence(monkeypatch, tmp_path, fault):
    wire = Wire(monkeypatch, fault)
    with pytest.raises((TimeoutError, InterruptedError)):
        wire.run(tmp_path, {'retained_witness': {}})
    rows = raw_rows(tmp_path)
    assert rows[-1]['opcode'] == native.CAPTURE_QUEUE and rows[-1]['error']
    assert not rows[-1]['response_complete']
    if fault == 'partial': assert len(base64.b64decode(rows[-1]['response'])) == 42
    assert len(wire.ports) == 1 and wire.ports[0].closes == 1
    value = json.loads((tmp_path / 'titan-retained-witness.json').read_text())
    assert not value['complete'] and value['error']


@pytest.mark.parametrize('operation', [
    {'retained_witness': {'seconds': 1}}, {'retained_witness': True},
    {'retained_witness': {}, 'save': False}, {'retained_witness': {}, 'fields': {}},
    {'retained_witness': {}, 'completion': {}},
])
def test_invalid_operation_refused_before_existing_owner(monkeypatch, tmp_path, operation):
    wire = Wire(monkeypatch)
    with pytest.raises(ValueError): wire.run(tmp_path, operation)
    assert not wire.ports


@pytest.mark.parametrize('deadline', [99., float('nan'), float('inf'), True, '120'])
def test_expired_absolute_deadline_refused_before_owner(monkeypatch, tmp_path, deadline):
    wire = Wire(monkeypatch)
    with pytest.raises(ValueError): wire.run(tmp_path, {'retained_witness': {}}, deadline=deadline)
    assert not wire.ports


@pytest.mark.parametrize('action,backend,operation,accepted', [
    ('bench-trial-control', 'titan', {'retained_witness': {}}, True),
    ('bench-trial-observe', 'titan', {'retained_witness': {}}, False),
    ('bench-trial-control', 's3', {'retained_witness': {}}, False),
    ('bench-trial-control', 'titan', {'retained_witness': {}, 'save': False}, False),
    ('bench-trial-control', 'titan', {'retained_witness': {'seconds': 1}}, False),
])
def test_public_adapter_validates_operation_before_authorisation(monkeypatch, tmp_path, action, backend, operation, accepted):
    monkeypatch.setattr(adapter, 'validate_manifest', lambda cfg, facts: ({}, tmp_path, tmp_path, backend))
    reached_authorisation = []
    class AuthorisationBoundary(RuntimeError): pass
    def stop_at_authorisation(*args, **kwargs):
        reached_authorisation.append(True)
        raise AuthorisationBoundary('Test boundary; no owner or hardware acquisition')
    monkeypatch.setattr(adapter, 'authorise', stop_at_authorisation)
    request_path = tmp_path / 'public-request.json'; request_path.write_text(json.dumps(operation))
    cfg = {'action': action, 'native_request': str(request_path)}
    if accepted:
        with pytest.raises(AuthorisationBoundary): adapter.execute(cfg, None, {})
        assert reached_authorisation == [True]
    else:
        with pytest.raises((ValueError, RuntimeError)) as caught: adapter.execute(cfg, None, {})
        assert not isinstance(caught.value, AuthorisationBoundary)
        assert not reached_authorisation
