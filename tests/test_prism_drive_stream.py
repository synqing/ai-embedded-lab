"""Host-only emulated endpoint tests. No serial, audio device or hardware."""
import copy
import json
import struct
import zlib

import pytest
from ael import prism_drive as d
from ael import prism_native as wire


SOURCE = 'ab' * 32


def emulated_budget(prepared):
    """Explicit no-playback test dependency; never selectable from a request."""
    class Reservation:
        def complete(self, success, player_log):
            assert type(success) is bool
    return Reservation()


def test_stream_refuses_missing_budget_before_player_start(bundle,tmp_path):
    clock=VirtualTime();endpoint=EmulatedEndpoint(clock)
    def forbidden(*args,**kwargs):raise AssertionError('Player started without budget')
    with pytest.raises(ValueError,match='durable campaign budget'):
        d.stream(endpoint.exchange,{'source_binding_hash':SOURCE},d.prepare_request(bundle),tmp_path,
                 player_factory=forbidden,now=clock.now,wait=clock.wait)


def test_stream_reserves_before_player_and_keeps_failed_start_charged(bundle,tmp_path):
    clock=VirtualTime();endpoint=EmulatedEndpoint(clock);events=[]
    class Reservation:
        def complete(self,success,log):events.append(('complete',success))
    def budget(prepared):events.append('reserved');return Reservation()
    def player(*args,**kwargs):
        assert events==['reserved'];events.append('player');raise RuntimeError('deliberate failed player')
    with pytest.raises(RuntimeError,match='failed player'):
        d.stream(endpoint.exchange,{'source_binding_hash':SOURCE},d.prepare_request(bundle),tmp_path,
                 player_factory=player,now=clock.now,wait=clock.wait,budget_factory=budget)
    assert events==['reserved','player',('complete',False)]


def write_bound(path, value):
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return {'path': str(path), 'sha256': d.file_hash(path)}


def rehash(value, key):
    value[key] = d.canonical_hash({k: v for k, v in value.items() if k != key})


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    player = write_bound(tmp_path / 'media_clock_player', 'explicit emulated player')
    monkeypatch.setattr(d, 'PLAYER', __import__('pathlib').Path(player['path']))
    media = write_bound(tmp_path / 'mixture.wav', 'SOURCE-PCM-RAMP')
    tool = write_bound(tmp_path / 'level_trace', 'explicit emulated level tool')
    verifier = write_bound(tmp_path / 'verifier.py', 'explicit source-recomputation fixture')
    words = [struct.unpack('<I', struct.pack('<f', .25))[0]] * 8 + [0] * 10
    words[14] = 100
    mapping = {'settings_words': words, 'g': 1, 'input_audio_gain': .5}
    physical = {'logical_pixels': 160, 'split': 80, 'centres': [79, 80],
                'channels': [{'pin': 'P601', 'logical_start': 0, 'count': 80},
                             {'pin': 'P604', 'logical_start': 80, 'count': 80}]}
    freeze = {'schema': 'titan.music_value.experiment/2', 'tool': tool,
              'passages': [{'id': 'fixture', 'mixture': media}],
              'display_mapping': mapping, 'physical_mapping': physical}
    rehash(freeze, 'freeze_sha256')
    source_identity = {'mixture': {'path': media['path'], 'file_sha256': media['sha256'],
                                  'pcm12800_sha256': 'cd' * 32, 'source_rate': 12800, 'hops': 40,
                                  'playback_gain': 1, 'input_gain': .5,
                                  'playback_file_sha256': media['sha256'],
                                  'playback_pcm_float32_sha256': 'ef' * 32}}
    trace = {'schema': 'titan.music_value.trace/2', 'rate': 12800, 'hop_samples': 64,
             'hops': 40, 'passage': 'fixture', 'freeze_sha256': freeze['freeze_sha256'],
             'source_identity': source_identity, 'teacher_status': d.HOLD,
             'display_mapping': mapping, 'physical_mapping': physical, 'arms': {}}
    for arm in ('A', 'C', 'D'):
        causal = arm != 'C'
        trace['arms'][arm] = {'level': [round(h / 40, 6) for h in range(40)],
             'valid': [True] * 40, 'sequence': list(range(40)), 'media_hop': list(range(40)),
             'event_sample': [(h + 1) * 64 for h in range(40)],
             'flags': [1 if causal else 5] * 40, 'causal': causal,
             'latest_input_sample': [(h + 1) * 64 if causal else 2560 for h in range(40)],
             'availability_sample': [(h + 1) * 64 if causal else 2560 for h in range(40)]}
    rehash(trace, 'trace_sha256')
    verification = {'schema': 'titan.music_value.trace-verification/1', 'verified': True,
         'method': 'recomputed-bound-source', 'trace_sha256': trace['trace_sha256'],
         'freeze_sha256': freeze['freeze_sha256'], 'source_identity': source_identity,
         'tool_sha256': tool['sha256'], 'verifier_source_sha256': verifier['sha256']}
    spec = {'arm': 'A', 'media': media, 'player': player, 'trace': write_bound(tmp_path / 'trace.json', trace),
            'freeze': write_bound(tmp_path / 'freeze.json', freeze), 'verifier': verifier,
            'verification': write_bound(tmp_path / 'verification.json', verification),
            'timing': {'extra_s': 0, 'uncertainty_s': .002, 'basis': 'render-only-unqualified'}}
    return spec


class VirtualTime:
    def __init__(self):
        self.ns = 1000000000

    def now(self):
        return self.ns

    def wait(self, seconds):
        self.ns += round(seconds * 1e9)


class EmulatedEndpoint:
    """Explicit model: CRC framed wire; 64 FIFO, monotonic trial/seq, AP ticks,
    250ms lease and 150ms fade. It makes no physical output claims.
    """
    def __init__(self, clock):
        self.clock = clock
        self.info = {'uid': d.UID, 'schema_sha256': d.SCHEMA, 'build_source_sha256': SOURCE,
                     'boot_id': 7, 'initialisation_failed': False,
                     'capabilities': {'evaluation_drive': d.CAPABILITY}}
        self.bound = False
        self.phase, self.end = 'idle', 'none'
        self.trial, self.seq, self.arm = 0, 0, 0
        self.resets = 0
        self.header = '00' * 32
        self.queue = []
        self.records = []
        self.arrivals = []
        self.frames = []
        self.fault = None
        self.last_arrival = clock.ns
        self.fade_end = 0
        self.last_tick = clock.ns
        self.suppress_consumption = False
        self.wire_sequence = 0
        self.traffic = []

    def tick(self):
        while self.last_tick + 5000000 <= self.clock.ns:
            self.last_tick += 5000000
            if self.queue and not self.suppress_consumption:
                self.frames.append((self.last_tick, self.queue[-1]))
                self.queue.clear()
            if self.phase == 'open' and self.last_tick - self.last_arrival > 250000000:
                self.phase, self.end = 'fading', 'expired'
                self.fade_end = self.last_tick + 150000000
                self.queue.clear()
            if self.phase == 'fading' and self.last_tick >= self.fade_end:
                self.phase = 'idle'

    def disconnect(self):
        self.bound = False
        self.phase, self.end = 'fading', 'disconnected'
        self.fade_end = self.clock.ns + 150000000
        self.queue.clear()

    def exchange(self, opcode, payload=b''):
        self.wire_sequence += 1
        packet = wire.request(opcode, payload, self.wire_sequence, 99)
        assert packet[:4] == b'K1S1'
        op, seq, cookie, size, crc, version, header_crc = struct.unpack_from('<7I', packet, 4)
        assert version == 1 and size == len(payload)
        assert zlib.crc32(packet[:28]) == header_crc and zlib.crc32(payload) == crc
        self.traffic.append(op)
        self.clock.ns += 20000
        self.tick()
        body, status = self.handle(op, payload)
        if self.fault == 'clientloss' and opcode == d.RECORD:
            self.disconnect()
            raise TimeoutError('Explicit emulated client loss')
        header = b'K1R1' + struct.pack('<6I', status, seq, cookie, len(body), 0, zlib.crc32(body))
        packet = header + struct.pack('<I', zlib.crc32(header)) + body
        if self.fault == 'wire-seq':
            packet = packet[:8] + struct.pack('<I', seq - 1) + packet[12:]
        return wire.response(packet, seq, cookie)

    def handle(self, opcode, payload):
        if opcode == 1:
            return json.dumps(self.info).encode(), 0
        if opcode == 0x50520001:
            self.bound = payload == wire.bind_payload(self.info['boot_id'])
            return b'', 0 if self.bound else 6
        boot = struct.unpack_from('<I', payload)[0]
        if boot != self.info['boot_id'] or not self.bound:
            return b'', 6
        if opcode == d.OPEN:
            boot, trial, self.arm = struct.unpack_from('<3I', payload)
            if self.phase != 'idle' or trial <= self.trial:
                return b'', 11
            self.trial, self.seq, self.header = trial, 0, payload[12:].hex()
            self.resets += 1
            self.phase, self.end, self.last_arrival = 'open', 'none', self.clock.ns
        elif opcode == d.RECORD:
            boot, trial, seq, hop, level, flags, latest, available = struct.unpack('<4If3I', payload)
            if self.phase != 'open' or trial != self.trial or seq != self.seq or len(self.queue) == 64:
                return b'', 11
            if available < latest or (not flags & 4 and latest > (hop + 1) * 64):
                return b'', 11
            self.seq += 1
            row = (seq, hop, level, flags, latest, available)
            self.queue.append(row)
            self.records.append(row)
            self.arrivals.append([len(self.arrivals), trial, seq, hop, self.clock.ns // 1000])
            self.last_arrival = self.clock.ns
        elif opcode == d.CLOSE:
            if self.phase != 'open':
                return b'', 11
            self.phase, self.end = 'fading', 'closed'
            self.fade_end = self.clock.ns + 150000000
            self.queue.clear()
        elif opcode == d.STATUS:
            cursor = struct.unpack_from('<Q', payload, 4)[0] if len(payload) == 12 else max(0, len(self.arrivals) - 32)
            rows = self.arrivals[cursor:cursor+32]
            status = {'capability': d.CAPABILITY, 'boot_id': boot, 'now_us': self.clock.ns // 1000,
             'initial_state_contract': 'programme-and-precision-reset-on-open-v1', 'initial_state_resets': self.resets,
             'capacity': 64, 'high_mark': 48, 'lease_us': 250000, 'crossfade_us': 150000,
             'queue_depth': len(self.queue), 'phase': self.phase, 'end_reason': self.end,
             'trial': self.trial, 'arm': self.arm, 'header_hash': self.header,
             'arrivals': {'lost': 0, 'next_cursor': cursor + len(rows), 'entries': rows},
             'accepted': len(self.records), 'completed': 0}
            return json.dumps(status).encode(), 0
        return b'', 0


class EmulatedPlayer:
    def __init__(self, clock, media_path, log_path):
        self.virtual = clock
        self.origin = clock.ns
        self.start = {'file_rate': 12800, 'input_gain': 1, 'frames': 2560}
        self.clock = d.MediaClock(12800)
        self.error = None
        self.aborted = False
        self.done = False
        log_path.write_text('explicit emulated audio endpoint\n')

    def update(self):
        sample = (self.virtual.ns - self.origin) * 12800 / 1e9
        self.clock.update({'event': 'clock', 'render_uptime_ns': self.virtual.ns,
                           'render_sample': sample, 'latency_s': 0})
        self.done = sample >= 2560 + 6400

    def close(self):
        return 0

    def abort(self):
        self.aborted = True


def test_stream_uses_actual_wire_and_media_clock_not_process_start(bundle, tmp_path):
    prepared = d.prepare_request(bundle)
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    players = []
    def factory(media, log, **kwargs):
        assert kwargs['input_gain'] == 1
        player = EmulatedPlayer(clock, media, log)
        players.append(player)
        player.update()
        return player
    def wait(seconds):
        clock.wait(seconds)
        for player in players:
            player.update()
    result = d.stream(endpoint.exchange, {'source_binding_hash': SOURCE}, prepared, tmp_path,
                      player_factory=factory, now=clock.now, wait=wait, budget_factory=emulated_budget)
    assert result['completed_stream'] and result['records'] == 40
    assert result['final_status']['phase'] == 'idle'
    assert result['final_status']['completed'] == 0
    assert not result['hardware_scheduled'] and not result['optical_verified']
    assert result['clock_fit']['span_us'] > 100000
    assert [r[0] for r in endpoint.records] == list(range(40))
    assert [r[2] for r in endpoint.records] == pytest.approx(prepared['rows']['level'], abs=1e-7)
    # Every wire row arrived after its own input hop had left the emulated
    # speaker, despite clock-calibration work before playback started.
    for row, arrival in zip(endpoint.records, endpoint.arrivals):
        event_ns = players[0].origin + (row[1] + 1) * 5000000
        assert 0 <= arrival[4] * 1000 - event_ns < 2000000


@pytest.mark.parametrize('field,value', [('uid', '00' * 16), ('schema_sha256', '00' * 32),
        ('build_source_sha256', '00' * 32), ('boot_id', 0)])
def test_wrong_device_identity_never_opens_or_sends(bundle, field, value):
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    endpoint.info[field] = value
    session = d.DriveSession(endpoint.exchange, SOURCE, clock.now)
    with pytest.raises(d.Refusal):
        session.bind()
    assert d.OPEN not in endpoint.traffic and d.RECORD not in endpoint.traffic


def opened(bundle):
    prepared = d.prepare_request(bundle)
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    session = d.DriveSession(endpoint.exchange, SOURCE, clock.now)
    session.bind()
    session.open(prepared)
    return prepared, clock, endpoint, session


@pytest.mark.parametrize('fault', ['boot', 'expired', 'wire-seq', 'clientloss'])
def test_boot_expiry_wire_identity_and_clientloss_do_not_retry(bundle, fault):
    prepared, clock, endpoint, session = opened(bundle)
    if fault == 'boot':
        endpoint.info['boot_id'] += 1
    elif fault == 'expired':
        clock.wait(.3)
    else:
        endpoint.fault = fault
    with pytest.raises((ValueError, TimeoutError)):
        if fault == 'clientloss':
            session.record(prepared, 0, clock.now(), clock.now())
        else:
            session.status()
    before = len(endpoint.traffic)
    session.close()
    assert len(endpoint.traffic) == before


def test_duplicate_out_of_order_and_early_expired_records_never_transmit(bundle):
    prepared, clock, endpoint, session = opened(bundle)
    session.record(prepared, 0, clock.now(), clock.now())
    count = len(endpoint.records)
    for h, event in [(0, clock.now()), (2, clock.now()),
                     (1, clock.now() + 10000), (1, clock.now() - 21000000)]:
        with pytest.raises(d.Refusal):
            session.record(prepared, h, clock.now(), event)
    assert len(endpoint.records) == count


def test_native_queue_capacity_and_spent_trial_identity(bundle):
    prepared, clock, endpoint, session = opened(bundle)
    endpoint.suppress_consumption = True
    for h in range(64):
        payload = struct.pack('<4If3I', session.boot, session.trial, h, h, .5, 1, (h+1)*64, (h+1)*64)
        endpoint.exchange(d.RECORD, payload)
    with pytest.raises(ValueError, match='rejection'):
        endpoint.exchange(d.RECORD, struct.pack('<4If3I', session.boot, session.trial, 64, 64, .5, 1, 4160, 4160))
    session.close()
    clock.wait(.16)
    session.status(check_session=False)
    with pytest.raises(d.Refusal, match='Spent'):
        session.open(prepared, session.trial)


def test_client_disconnect_has_finite_fallback_and_old_trial_cannot_return(bundle):
    prepared, clock, endpoint, session = opened(bundle)
    endpoint.disconnect()
    clock.wait(.16)
    endpoint.tick()
    assert endpoint.phase == 'idle'
    with pytest.raises(ValueError):
        endpoint.exchange(d.RECORD, struct.pack('<4If3I', 7, session.trial, 0, 0, .5, 1, 64, 64))


@pytest.mark.parametrize('mutation', ['shift-level', 'shift-event', 'swap-halves', 'wrong-audio'])
def test_source_alignment_mutations_rejected_even_after_rehash(bundle, mutation):
    spec = copy.deepcopy(bundle)
    trace = json.loads(open(spec['trace']['path']).read())
    if mutation == 'wrong-audio':
        spec['media'] = write_bound(__import__('pathlib').Path(spec['media']['path']).with_name('other.wav'), 'OTHER')
    else:
        if mutation == 'shift-level':
            trace['arms']['A']['level'] = [0] + trace['arms']['A']['level'][:-1]
        elif mutation == 'shift-event':
            trace['arms']['A']['event_sample'] = [s + 64 for s in trace['arms']['A']['event_sample']]
        else:
            trace['physical_mapping']['channels'].reverse()
        rehash(trace, 'trace_sha256')
        spec['trace'] = write_bound(__import__('pathlib').Path(spec['trace']['path']), trace)
    with pytest.raises(d.Refusal):
        d.prepare_request(spec)


def test_offline_unavailable_and_scene_controls_preserve_scope(bundle):
    spec = copy.deepcopy(bundle)
    spec['arm'] = 'C'
    assert d.prepare_request(spec)['rows']['flags'] == [5] * 40
    spec['arm'] = 'B'
    with pytest.raises(d.Refusal, match='unavailable'):
        d.prepare_request(spec)
    p = d.prepare_request(bundle)
    fields = {str(i+1): struct.unpack('<f', struct.pack('<I', w))[0] if i < 8 else w
              for i, w in enumerate(p['trace']['display_mapping']['settings_words']) if i != 12}
    d.validate_scene_fields(fields, p)
    fields['15'] = 255
    with pytest.raises(d.Refusal):
        d.validate_scene_fields(fields, p)


def test_clock_offset_drift_and_uncertainty_are_measured_not_physical():
    fit = d.ClockFit()
    for i in range(10):
        host_ns = 5000000000 + i * 50000000
        midpoint_us = host_ns / 1000 + 50
        fit.observe(host_ns, host_ns + 100000, round(midpoint_us * 1.0001 + 4200))
    assert fit.report()['drift_ppm'] == pytest.approx(100, abs=2)
    assert fit.device_us(5200000000) == pytest.approx(5200000 * 1.0001 + 4200, abs=2)
    assert fit.report()['uncertainty_estimate_us'] >= 52
    assert fit.report()['qualified'] is False
    with pytest.raises(d.Refusal, match='reset'):
        fit.observe(5600000000, 5600100000, 1)


def test_media_clock_seek_requires_rebind_and_shifted_latency_changes_due_time():
    clock = d.MediaClock(12800)
    clock.update({'event': 'clock', 'render_uptime_ns': 1000000000, 'render_sample': 1280, 'latency_s': .02})
    assert clock.event_host_ns(1280) == 1020000000
    assert list(d.due_hops(clock.speaker_sample(1000000000), 12800, 0, 40)) == list(range(16))
    with pytest.raises(d.Refusal, match='seek'):
        clock.update({'event': 'clock', 'render_uptime_ns': 1001000000, 'render_sample': 10, 'latency_s': .02})


@pytest.mark.parametrize('fault,match', [('stale', 'Stale'), ('backlog', 'chunk'),
        ('gain', 'gain'), ('highwater', 'watermark'), ('late-ack', 'ACK')])
def test_stream_faults_end_own_player_and_never_dump_backlog(bundle, tmp_path, fault, match):
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    players = []
    def factory(media, log, **kwargs):
        player = EmulatedPlayer(clock, media, log)
        player.update()
        if fault == 'gain':
            player.start['input_gain'] = .5
        players.append(player)
        return player
    def wait(seconds):
        clock.wait(.05 if players and fault == 'backlog' else seconds)
        if fault != 'stale':
            for player in players:
                player.update()
    original_handle = endpoint.handle
    def handle(op, payload):
        body, status = original_handle(op, payload)
        if players and fault == 'highwater' and op == d.STATUS:
            row = json.loads(body)
            row['queue_depth'] = 48
            body = json.dumps(row).encode()
        return body, status
    endpoint.handle = handle
    original_exchange = endpoint.exchange
    def exchange(op, payload=b''):
        if fault == 'late-ack' and op == d.RECORD:
            clock.wait(.021)
        return original_exchange(op, payload)
    with pytest.raises(d.Refusal, match=match):
        d.stream(exchange, {'source_binding_hash': SOURCE}, d.prepare_request(bundle), tmp_path,
                 player_factory=factory, now=clock.now, wait=wait, budget_factory=emulated_budget)
    assert players and players[0].aborted
    assert endpoint.traffic.count(d.CLOSE) == 1
    assert not endpoint.queue


def test_subsequent_trial_seeds_arrival_cursor_instead_of_replaying_old_history(bundle):
    prepared = d.prepare_request(bundle)
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    endpoint.trial = 9
    endpoint.arrivals = [[i, 9, i, i, 900000] for i in range(100)]
    session = d.DriveSession(endpoint.exchange, SOURCE, clock.now)
    session.bind()
    session.open(prepared)
    assert session.trial == 10 and session.cursor == 100
    session.record(prepared, 0, clock.now(), clock.now())
    session.status()
    assert not session.pending and session.arrival_witnesses[-1]['sequence'] == 0


def test_native_wire_rejects_payload_crc_and_wrong_response_cookie():
    payload = b'bounded'
    header = b'K1R1' + struct.pack('<6I', 0, 5, 7, len(payload), 0, zlib.crc32(payload))
    packet = header + struct.pack('<I', zlib.crc32(header)) + payload
    with pytest.raises(ValueError, match='identity'):
        wire.response(packet, 5, 8)
    with pytest.raises(ValueError, match='CRC'):
        wire.response(packet[:-1] + b'!', 5, 7)


def test_existing_native_owner_session_routes_actual_framed_drive_without_second_writer(bundle, tmp_path, monkeypatch):
    import serial
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    players = []
    ports = []
    prepared = d.prepare_request(bundle)
    fields = {str(i+1): struct.unpack('<f', struct.pack('<I', w))[0] if i < 8 else w
              for i, w in enumerate(prepared['trace']['display_mapping']['settings_words']) if i != 12}
    operation = tmp_path / 'operation.json'
    operation.write_text(json.dumps({'fields': fields, 'evaluation_drive': bundle}))

    original_handle = endpoint.handle
    control_words = [0] * 18
    control_revision = 1
    control_accepted = 0
    def handle(opcode, payload):
        nonlocal control_revision, control_accepted
        if opcode == 25:
            body = bytearray(160)
            magic, command, boot, _ = struct.unpack_from('<4I', payload)
            changed = transitioned = 0
            if magic == 0x454D0102:
                command, boot = struct.unpack_from('<2I', payload, 8)
                old = list(control_words)
                for offset in range(24, len(payload), 8):
                    field, kind, word = struct.unpack_from('<HHI', payload, offset)
                    control_words[field-1] = word
                changed = int(old != control_words)
                transitioned = int(old[8] != control_words[8])
                if changed:
                    control_revision += 1
                    control_accepted = command
            struct.pack_into('<6I', body, 0, 0x454D5354, 1, 1, boot, control_revision, command)
            struct.pack_into('<9I', body, 24, *control_words[:8], control_words[2])
            flags = sum(control_words[field-1] << bit for bit, field in enumerate((10,11,12,13,14,16,17)))
            available = 0xffff & ~(0 if control_words[8] == 0 else 1<<5) & ~(0 if control_words[4] else 1<<13)
            struct.pack_into('<12I', body, 60, control_words[8], flags, control_words[14], available,
                             control_accepted, 0, 0, 0, 0, 0, changed, transitioned)
            body[108:140] = bytes.fromhex(d.SCHEMA)
            struct.pack_into('<I', body, 140, control_words[17])
            return bytes(body), 0
        return original_handle(opcode, payload)
    endpoint.handle = handle

    class EmulatedSerialPort:
        def __init__(self, **kwargs):
            self.data = b''
            self.closed = False
            ports.append(self)
        def open(self):
            pass
        def close(self):
            self.closed = True
        def write(self, packet):
            opcode, sequence, cookie, size, crc, version, hcrc = struct.unpack_from('<7I', packet, 4)
            assert packet[:4] == b'K1S1' and version == 1
            assert zlib.crc32(packet[:28]) == hcrc
            assert size == len(packet[32:]) and zlib.crc32(packet[32:]) == crc
            endpoint.traffic.append(opcode)
            clock.ns += 20000
            endpoint.tick()
            body, status = endpoint.handle(opcode, packet[32:])
            header = b'K1R1' + struct.pack('<6I', status, sequence, cookie, len(body), 0, zlib.crc32(body))
            self.data = header + struct.pack('<I', zlib.crc32(header)) + body
            return len(packet)
        def read(self, size):
            output, self.data = self.data[:size], self.data[size:]
            return output

    def factory(media, log, **kwargs):
        player = EmulatedPlayer(clock, media, log)
        player.update()
        players.append(player)
        return player
    def wait(seconds):
        clock.wait(seconds)
        for player in players:
            player.update()
    actual_stream = d.stream
    monkeypatch.setattr(serial, 'Serial', EmulatedSerialPort)
    monkeypatch.setattr(d, 'uptime_ns', clock.now)
    monkeypatch.setattr(d, 'stream', lambda exchange, manifest, prepared, out:
        actual_stream(exchange, manifest, prepared, out, player_factory=factory, now=clock.now, wait=wait, budget_factory=emulated_budget))
    out = tmp_path / 'session'
    out.mkdir()
    result = wire.run_session({'port': 'EMULATED-NO-HARDWARE', 'source_binding_hash': SOURCE}, out, 10, operation)
    assert result['evaluation_drive']['records'] == 40
    assert result['evaluation_drive']['arrival_records'] == 40
    assert len(ports) == 1 and ports[0].closed
    assert result['runtime_boot_verified'] and not result['optical_verified']
    packets = [json.loads(line) for line in (out / 'titan-native.jsonl').read_text().splitlines()]
    assert sum(row['opcode'] == d.RECORD for row in packets) == 40
    assert all('before_uptime_ns' in row and 'after_uptime_ns' in row for row in packets)


def test_initial_scene_reset_is_required_before_replay(bundle):
    prepared = d.prepare_request(bundle)
    clock = VirtualTime()
    endpoint = EmulatedEndpoint(clock)
    original_handle = endpoint.handle
    def handle(op, payload):
        body, status = original_handle(op, payload)
        if op == d.STATUS:
            row = json.loads(body)
            row['initial_state_resets'] = 0
            body = json.dumps(row).encode()
        return body, status
    endpoint.handle = handle
    session = d.DriveSession(endpoint.exchange, SOURCE, clock.now)
    session.bind()
    with pytest.raises(d.Refusal, match='reset'):
        session.open(prepared)
    session.close()
    assert d.RECORD not in endpoint.traffic
