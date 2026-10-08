"""Bounded Titan evaluation-drive streaming through the existing native owner.

Host pacing is based on the audio player's device render clock. Device clock
correlation uses measured request/response brackets; it is not acoustic or
optical timing. Native v1 accepts FIFO records, not future hardware deadlines.
"""
import hashlib
import json
import math
import struct
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from ael.prism_native import UID, SCHEMA, bind_payload

HOP, RATE = 64, 12800
CAPABILITY = 'titan.evaluation-drive.v1-experimental'
OPEN, RECORD, STATUS, CLOSE, LIVE = range(0x50524401, 0x50524406)
PLAYER = Path(__file__).resolve().parents[1] / 'tools/media_clock_player/media_clock_player'
HOLD = 'AUTOMATIC_TEACHER_PROMOTION_HELD'


class Refusal(ValueError):
    pass


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    if not isinstance(value, str) or len(value) != 64:
        raise Refusal('Missing SHA256 identity')
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise Refusal('Invalid SHA256 identity') from exc
    return value


def uint(value, positive=False):
    if type(value) is not int or not (int(positive) <= value <= 0xffffffff):
        raise Refusal('Invalid uint32')
    return value


def bound_file(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get('path'), str):
        raise Refusal('Explicit bound file required')
    path = Path(spec['path'])
    if not path.is_absolute() or not path.is_file() or file_hash(path) != digest(spec.get('sha256')):
        raise Refusal('Bound file changed or unavailable')
    return path


def uptime_ns():
    return time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)


class MediaClock:
    """Speaker-position estimate from render reports, with no guessed offset."""
    def __init__(self, file_rate, extra_s=0.0):
        self.file_rate = float(file_rate)
        self.extra_s = float(extra_s)
        if not math.isfinite(self.file_rate) or self.file_rate <= 0 or not math.isfinite(self.extra_s):
            raise Refusal('Invalid media clock configuration')
        self.anchor = None
        self.lock = threading.Lock()
        self.reports = 0

    def update(self, row):
        if row.get('event') != 'clock' or row['render_sample'] < 0:
            return
        values = row['render_uptime_ns'], row['render_sample'], row['latency_s']
        if any(not math.isfinite(v) for v in values) or values[0] < 0 or values[2] < 0:
            raise Refusal('Invalid render clock report')
        with self.lock:
            if self.anchor and (values[0] < self.anchor[0] or values[1] < self.anchor[1]):
                raise Refusal('Playback seek/reset requires a new trial')
            self.anchor = values
            self.reports += 1

    def speaker_sample(self, now_ns):
        with self.lock:
            anchor = self.anchor
        if anchor is None:
            return None
        t, s, latency = anchor
        return s + (now_ns - t) * self.file_rate / 1e9 - (latency + self.extra_s) * self.file_rate

    def event_host_ns(self, sample):
        with self.lock:
            if self.anchor is None:
                raise Refusal('Media clock unavailable')
            t, s, latency = self.anchor
        return t + ((sample - s) / self.file_rate + latency + self.extra_s) * 1e9

    def age_ns(self, now_ns):
        with self.lock:
            return None if self.anchor is None else now_ns - self.anchor[0]


def due_hops(speaker_sample, file_rate, sent, total):
    """Only completed 64-sample windows may leave the host."""
    if speaker_sample is None or speaker_sample < 0:
        return range(sent, sent)
    completed = int(math.floor(speaker_sample * RATE / file_rate / HOP))
    return range(sent, min(max(sent, completed), total))


class Player:
    def __init__(self, wav, log_path, binary=PLAYER, input_gain=1.0):
        self.log = open(log_path, 'x')
        self.proc = subprocess.Popen([str(binary), '--wav', str(wav), '--gain', str(input_gain)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.start = json.loads(self.proc.stdout.readline())
            if (self.start.get('event') != 'start' or self.start.get('clock') != 'CLOCK_UPTIME_RAW' or
                    self.start.get('input_gain') != input_gain):
                raise Refusal('Media clock player did not start with required clock')
        except Exception:
            self.abort()
            raise
        self.clock = MediaClock(self.start['file_rate'])
        self.done = False
        self.error = None
        self.log.write(json.dumps(self.start) + '\n')
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                row = json.loads(line)
                self.log.write(line)
                self.log.flush()
                if row.get('event') == 'end':
                    self.done = True
                self.clock.update(row)
            if not self.done:
                raise Refusal('Player exited without end report')
        except Exception as exc:
            self.error = exc

    def close(self):
        code = self.proc.wait(timeout=5)
        self.thread.join(timeout=2)
        self.log.close()
        if self.error:
            raise self.error
        if code:
            raise Refusal('Media player failed')
        return code

    def abort(self):
        # Only this session's own player is stopped; no existing music owner.
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        if hasattr(self, 'thread'):
            self.thread.join(timeout=2)
        self.log.close()


class ClockFit:
    """Bounded affine device-us fit from exchange midpoint and RTT brackets.

    The estimate assumes device stamping occurred somewhere inside the host
    exchange bracket. Residual + half RTT is a declared estimate, not qualified
    capture/physical uncertainty.
    """
    def __init__(self, max_drift_ppm=2000):
        self.points = deque(maxlen=32)
        self.max_drift_ppm = max_drift_ppm
        self.slope = 1.0
        self.offset_us = None
        self.uncertainty_us = None
        self.span_us = 0

    def observe(self, before_ns, after_ns, device_us):
        if after_ns < before_ns or type(device_us) is not int or device_us < 0:
            raise Refusal('Invalid device clock bracket')
        x, half = (before_ns + after_ns) / 2000, (after_ns - before_ns) / 2000
        if self.points and (x <= self.points[-1][0] or device_us <= self.points[-1][1]):
            raise Refusal('Device clock reset/nonmonotonic')
        self.points.append((x, device_us, half))
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        self.span_us = xs[-1] - xs[0]
        denominator = sum((v - mx) ** 2 for v in xs)
        self.slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator if denominator else 1.0
        if self.span_us >= 100000 and abs(self.slope - 1) * 1e6 > self.max_drift_ppm:
            raise Refusal('Device/host clock drift exceeds explicit trial bound')
        self.offset_us = my - self.slope * mx
        self.uncertainty_us = max(abs(y - (self.slope * x + self.offset_us)) + half + 2 for x, y, half in self.points)

    def device_us(self, host_ns):
        if self.offset_us is None:
            raise Refusal('Device clock fit unavailable')
        return host_ns / 1000 * self.slope + self.offset_us

    def report(self):
        return {'points': len(self.points), 'span_us': self.span_us, 'slope': self.slope,
                'drift_ppm': (self.slope - 1) * 1e6, 'offset_us': self.offset_us,
                'uncertainty_estimate_us': self.uncertainty_us, 'qualified': False,
                'kind': 'exchange-midpoint-affine-fit-plus-residual-half-RTT-and-2us-resolution'}


def prepare_request(spec):
    """Validate complete trace/media/freeze identity before hardware or playback."""
    trace_path = bound_file(spec['trace'])
    freeze_path = bound_file(spec['freeze'])
    media_path = bound_file(spec['media'])
    trace = json.loads(trace_path.read_text())
    freeze = json.loads(freeze_path.read_text())
    for value, key in ((trace, 'trace_sha256'), (freeze, 'freeze_sha256')):
        if canonical_hash({k: v for k, v in value.items() if k != key}) != digest(value.get(key)):
            raise Refusal('Canonical content identity mismatch: ' + key)
    if trace.get('schema') != 'titan.music_value.trace/2' or trace.get('rate') != RATE or trace.get('hop_samples') != HOP:
        raise Refusal('Unsupported trace schema/rate/hop')
    if trace.get('freeze_sha256') != freeze['freeze_sha256'] or trace.get('teacher_status') != HOLD:
        raise Refusal('Freeze/teacher identity mismatch')
    source = trace['source_identity']['mixture']
    if (source.get('playback_gain') != 1 or file_hash(media_path) != source.get('playback_file_sha256') or
            file_hash(source['path']) != source['file_sha256']):
        raise Refusal('Playback is not the source-bound once-attenuated mixture')
    digest(source['playback_pcm_float32_sha256'])
    digest(source['pcm12800_sha256'])
    for identity in trace['source_identity'].values():
        if isinstance(identity, dict) and 'pcm12800_sha256' in identity:
            if file_hash(identity['path']) != identity['file_sha256']:
                raise Refusal('Trace source file changed after recomputation')
    passage = next((p for p in freeze['passages'] if p['id'] == trace['passage']), None)
    if not passage or passage['mixture']['sha256'] != source['file_sha256']:
        raise Refusal('Passage/source mismatch')
    if file_hash(freeze['tool']['path']) != freeze['tool']['sha256']:
        raise Refusal('Frozen trace tool changed')
    verification = json.loads(bound_file(spec['verification']).read_text())
    verifier = bound_file(spec['verifier'])
    if (verification.get('schema') != 'titan.music_value.trace-verification/1' or
            verification.get('verified') is not True or verification.get('method') != 'recomputed-bound-source' or
            verification.get('trace_sha256') != trace['trace_sha256'] or
            verification.get('freeze_sha256') != freeze['freeze_sha256'] or
            verification.get('source_identity') != trace['source_identity'] or
            verification.get('tool_sha256') != freeze['tool']['sha256'] or
            verification.get('verifier_source_sha256') != file_hash(verifier)):
        raise Refusal('Trace lacks matching source-recomputation verification')
    for key in ('display_mapping', 'physical_mapping'):
        if trace.get(key) != freeze.get(key) or not isinstance(trace.get(key), dict):
            raise Refusal('Trace display/half mapping differs from freeze')
    input_gain = trace['display_mapping'].get('input_audio_gain')
    if input_gain != .5 or any(s.get('input_gain') != input_gain for s in trace['source_identity'].values()
                                if isinstance(s, dict) and 'pcm12800_sha256' in s):
        raise Refusal('All source conversions/playback require common frozen halfscale')
    player_path = bound_file(spec['player'])
    if player_path.resolve() != PLAYER.resolve():
        raise Refusal('Only the existing media-clock player is supported')
    arm = spec['arm']
    if arm not in ('A', 'B', 'C', 'D') or arm not in trace['arms']:
        raise Refusal('Arm unavailable; never substitute another source')
    rows, n = trace['arms'][arm], uint(trace['hops'], positive=True)
    if n * HOP / RATE > 120:
        raise Refusal('Trace exceeds existing 120-second bench window')
    required = ('level', 'valid', 'sequence', 'media_hop', 'event_sample', 'flags', 'latest_input_sample', 'availability_sample')
    if any(len(rows.get(k, [])) != n for k in required):
        raise Refusal('Incomplete per-hop trace')
    if rows.get('causal') is not (arm != 'C'):
        raise Refusal('Offline/causal arm label mismatch')
    for h in range(n):
        level = rows['level'][h]
        if not isinstance(level, (int, float)) or not math.isfinite(level) or not 0 <= level <= 1:
            raise Refusal('Nonfinite/out-of-range level')
        if type(rows['valid'][h]) is not bool:
            raise Refusal('Invalid validity flag')
        if rows['sequence'][h] != h or rows['media_hop'][h] != h or rows['event_sample'][h] != (h + 1) * HOP:
            raise Refusal('Shifted/replayed trace timing')
        flags = uint(rows['flags'][h])
        if flags != int(rows['valid'][h]) | (4 if arm == 'C' else 0):
            raise Refusal('Invalid offline/valid flags')
        latest, available = uint(rows['latest_input_sample'][h]), uint(rows['availability_sample'][h])
        if available < latest or (arm != 'C' and latest > (h + 1) * HOP):
            raise Refusal('Impossible causal availability')
    timing = spec['timing']
    # Reported audio latency is not measured acoustic latency. Require declared
    # route uncertainty even when the experiment intentionally uses render-only.
    if not isinstance(timing.get('extra_s'), (int, float)) or not math.isfinite(timing['extra_s']):
        raise Refusal('Explicit finite clock offset required')
    uncertainty = timing.get('uncertainty_s')
    if uncertainty is not None and (not isinstance(uncertainty, (int, float)) or
                                    not math.isfinite(uncertainty) or uncertainty < 0):
        raise Refusal('Invalid route uncertainty')
    if timing.get('basis') not in ('measured-route', 'render-only-unqualified'):
        raise Refusal('Invalid route timing basis')
    if timing['basis'] == 'render-only-unqualified' and timing['extra_s'] != 0:
        raise Refusal('Unmeasured route offset cannot be invented')
    if timing['basis'] == 'measured-route':
        if uncertainty is None:
            raise Refusal('Measured route requires finite measured uncertainty')
        bound_file(timing['evidence'])
    max_lateness = spec.get('max_lateness_us', 20000)
    if type(max_lateness) is not int or not 1000 <= max_lateness < 250000:
        raise Refusal('Lateness bound must be positive and below lease')
    chunk = spec.get('max_chunk', 4)
    if type(chunk) is not int or not 1 <= chunk <= 8:
        raise Refusal('Chunk must be 1..8, below native watermarks')
    return {'spec': spec, 'trace': trace, 'freeze': freeze, 'media': media_path,
            'rows': rows, 'arm': arm, 'hops': n, 'input_gain': source['playback_gain'],
            'player': player_path, 'max_lateness_us': max_lateness, 'max_chunk': chunk}


def validate_scene_fields(fields, prepared):
    words = prepared['trace']['display_mapping']['settings_words']
    supported = set(range(1, 19)) - {13}  # native field13 is unsupported
    if len(words) != 18 or {int(k) for k in fields} != supported:
        raise Refusal('Full frozen native scene controls required')
    if words[8] != 0 or words[14] != 100:
        raise Refusal('Experiment requires frozen Analog mode and normal brightness100')
    for key, value in fields.items():
        field = int(key)
        if field <= 8:
            encoded = struct.unpack('<I', struct.pack('<f', value))[0]
        else:
            encoded = uint(value)
        if encoded != words[field - 1]:
            raise Refusal('Control differs from frozen shared scene')


class DriveSession:
    """Actual native wire contract. exchange owns framing, logging and deadlines."""
    def __init__(self, exchange, source_binding, now=uptime_ns):
        self.exchange, self.source_binding, self.now = exchange, digest(source_binding), now
        self.boot = None
        self.trial = None
        self.header = None
        self.sequence = 0
        self.cursor = None
        self.pending = {}
        self.arrival_witnesses = []
        self.arrival_records = 0
        self.witness_sink = None
        self.clock = ClockFit()
        self.last_status = None
        self.opened = False
        self.failed = False

    def bind(self):
        info = json.loads(self.exchange(1))
        if (info.get('uid') != UID or info.get('schema_sha256') != SCHEMA or
                info.get('build_source_sha256') != self.source_binding or
                info.get('capabilities', {}).get('evaluation_drive') != CAPABILITY or
                info.get('initialisation_failed') is not False):
            raise Refusal('Unsupported/wrong native UID/schema/source/capability')
        self.boot = uint(info['boot_id'], positive=True)
        self.exchange(0x50520001, bind_payload(self.boot))
        return info

    def status(self, check_session=True):
        before = self.now()
        try:
            payload = struct.pack('<I', self.boot) if self.cursor is None else struct.pack('<IQ', self.boot, self.cursor)
            status = json.loads(self.exchange(STATUS, payload))
        except Exception:
            self.failed = True
            raise
        after = self.now()
        if status.get('capability') != CAPABILITY or status.get('boot_id') != self.boot:
            self.failed = True
            raise Refusal('Device boot/capability changed; never reconnect automatically')
        try:
            self.clock.observe(before, after, status['now_us'])
        except Exception:
            self.failed = True
            raise
        if status.get('initial_state_contract') != 'programme-and-precision-reset-on-open-v1':
            raise Refusal('Unsupported/unavailable equal initial scene contract')
        if status.get('capacity') != 64 or status.get('high_mark') != 48 or status.get('lease_us') != 250000 or status.get('crossfade_us') != 150000:
            raise Refusal('Unsupported drive queue/lease contract')
        if check_session and self.opened:
            if (status.get('trial') != self.trial or status.get('header_hash') != self.header or
                    status.get('phase') != 'open' or status.get('end_reason') != 'none'):
                self.failed = True
                raise Refusal('Drive session lost, expired or replaced')
        arrivals = status['arrivals']
        if arrivals['lost'] or (self.cursor is not None and arrivals['next_cursor'] < self.cursor):
            raise Refusal('Arrival evidence overwritten or regressed')
        if self.opened:
            if status.get('arm') != ord(self.arm):
                raise Refusal('Wrong arm status')
            for index, trial, sequence, hop, device_us in arrivals['entries']:
                if trial != self.trial or sequence not in self.pending or self.pending[sequence]['media_hop'] != hop:
                    raise Refusal('Arrival witness is not this accepted source generation')
                row = self.pending.pop(sequence)
                row.update(arrival_device_us=device_us, arrival_index=index,
                           arrival_minus_event_estimate_us=device_us - row['event_device_us_estimate'])
                self.arrival_records += 1
                if self.witness_sink:
                    self.witness_sink(row)
                else:
                    self.arrival_witnesses.append(row)
        self.cursor = arrivals['next_cursor']
        self.last_status = status
        return status

    def open(self, prepared, trial=None):
        if self.boot is None:
            raise Refusal('Bind before open')
        initial = self.status(check_session=False)
        if initial['phase'] != 'idle':
            raise Refusal('Existing trial/fade still owns drive')
        # Native trial IDs are monotonic in this boot; no reopening old identity.
        self.trial = uint(trial if trial is not None else initial['trial'] + 1, positive=True)
        if self.trial <= initial['trial']:
            raise Refusal('Spent trial identity')
        metadata = {'capability': CAPABILITY, 'uid': UID, 'schema_sha256': SCHEMA,
                    'source_binding_sha256': self.source_binding, 'boot': self.boot, 'trial': self.trial,
                    'arm': prepared['arm'], 'trace_sha256': prepared['trace']['trace_sha256'],
                    'freeze_sha256': prepared['freeze']['freeze_sha256'],
                    'media_file_sha256': file_hash(prepared['media']), 'timing': prepared['spec']['timing'],
                    'source_identity': prepared['trace']['source_identity'],
                    'input_audio_gain': prepared['trace']['display_mapping']['input_audio_gain'],
                    'playback_gain': prepared['input_gain'],
                    'player_sha256': file_hash(prepared['player'])}
        self.header = canonical_hash(metadata)
        self.arm = prepared['arm']
        try:
            self.exchange(OPEN, struct.pack('<3I', self.boot, self.trial, ord(prepared['arm'])) + bytes.fromhex(self.header))
        except Exception:
            self.failed = True
            raise
        self.opened = True
        opened = self.status()
        if opened.get('initial_state_resets') != initial['initial_state_resets'] + 1:
            raise Refusal('Successful trial did not reset equal initial scene')
        return metadata

    def record(self, prepared, h, now_ns, event_ns):
        if not self.opened or self.failed or h != self.sequence:
            raise Refusal('Drive sequence/session not writable')
        lateness = (now_ns - event_ns) / 1000
        if lateness < -2 or lateness > prepared['max_lateness_us']:
            raise Refusal('Early/expired media record; no backlog dump')
        rows = prepared['rows']
        payload = struct.pack('<4If3I', self.boot, self.trial, self.sequence, rows['media_hop'][h],
                              rows['level'][h], rows['flags'][h], rows['latest_input_sample'][h], rows['availability_sample'][h])
        try:
            self.exchange(RECORD, payload)
        except Exception:
            self.failed = True
            raise
        self.sequence += 1
        row = {'sequence': h, 'media_hop': rows['media_hop'][h], 'event_host_ns': event_ns,
                'send_host_ns': now_ns, 'ack_host_ns': self.now(), 'lateness_us': lateness,
                'event_device_us_estimate': self.clock.device_us(event_ns),
                'clock_uncertainty_estimate_us': self.clock.uncertainty_us}
        if len(self.pending) >= 32:
            raise Refusal('Pending arrival evidence exceeds bounded status chunk')
        self.pending[h] = row
        return row

    def close(self):
        if self.opened and not self.failed:
            self.opened = False  # an ambiguous close is never retried
            self.exchange(CLOSE, struct.pack('<2I', self.boot, self.trial))
        self.opened = False


def stream(exchange, manifest, prepared, out, *, player_factory=Player, now=uptime_ns, wait=None):
    """Run one admitted source-bound trial; all injected tests use an emulator."""
    # Revalidate files at the actual playback boundary, after admission.
    prepared = prepare_request(prepared['spec'])
    wait = wait or (lambda seconds: threading.Event().wait(seconds))
    session = DriveSession(exchange, manifest['source_binding_hash'], now)
    player = None
    result = {'classification': 'HOST_PACED_NATIVE_FIFO_EXPERIMENT',
              'hardware_scheduled': False, 'physical_timing_qualified': False,
              'optical_verified': False, 'teacher_status': HOLD, 'records': 0}
    log_path = Path(out) / 'drive-pacing.jsonl'
    with log_path.open('x') as log, (Path(out) / 'drive-arrivals.jsonl').open('x') as arrivals_log:
        def arrival_sink(row):
            arrivals_log.write(json.dumps(row) + '\n')
            arrivals_log.flush()
        session.witness_sink = arrival_sink
        try:
            result['identity'] = session.bind()
            # Establish a nonzero fit span before opening the finite lease.
            for _ in range(3):
                session.status(check_session=False)
                wait(.05)
            result['session_header'] = session.open(prepared, prepared['spec'].get('trial'))
            player = player_factory(prepared['media'], Path(out) / 'media-clock.jsonl',
                                    binary=prepared['player'], input_gain=prepared['input_gain'])
            if player.start.get('input_gain') != prepared['input_gain']:
                raise Refusal('Playback gain differs from frozen source conversion')
            rate = prepared['trace']['source_identity']['mixture']['source_rate']
            expected_frames = prepared['hops'] * HOP / RATE * rate
            if (player.start['file_rate'] != rate or player.start.get('frames', -1) < expected_frames or
                    player.start['frames'] >= expected_frames + HOP / RATE * rate):
                raise Refusal('Player media rate/length differs from bound source')
            player.clock.extra_s = prepared['spec']['timing']['extra_s']
            started = now()
            last_status = started
            last_record = started
            maximum_ns = int((prepared['hops'] * HOP / RATE + 2) * 1e9)
            while session.sequence < prepared['hops']:
                current = now()
                if player.error:
                    raise player.error
                if current - started > maximum_ns:
                    raise Refusal('Playback/stream deadline; no automatic restart')
                age = player.clock.age_ns(current)
                if age is not None and age > 100000000:
                    raise Refusal('Stale playback clock/paused track')
                if current - last_record > 200000000:
                    raise Refusal('Client would exceed native lease; end trial')
                if current - last_status >= 20000000:
                    status = session.status()
                    last_status = now()
                    if status['queue_depth'] >= 48:
                        raise Refusal('Native FIFO reached high watermark')
                due = list(due_hops(player.clock.speaker_sample(current), player.clock.file_rate,
                                    session.sequence, prepared['hops']))
                if len(due) > prepared['max_chunk']:
                    raise Refusal('Media backlog exceeds bounded chunk')
                if due and session.last_status['queue_depth'] + len(due) >= 48:
                    raise Refusal('Insufficient native queue headroom')
                for h in due:
                    event = player.clock.event_host_ns(prepared['rows']['event_sample'][h] * player.clock.file_rate / RATE)
                    row = session.record(prepared, h, now(), event)
                    if row['ack_host_ns'] - event > prepared['max_lateness_us'] * 1000:
                        raise Refusal('Record ACK missed host media deadline')
                    log.write(json.dumps(row) + '\n')
                    log.flush()
                    last_record = now()
                if not due:
                    if player.done:
                        raise Refusal('Playback ended before complete trace')
                    wait(.001)
            result['records'] = session.sequence
            result['final_open_status'] = session.status()
            session.close()
            # Observe finite recovery on the same port, no reconnect/reset.
            deadline = now() + 200000000
            while True:
                final = session.status(check_session=False)
                if final['phase'] == 'idle':
                    break
                if now() >= deadline:
                    raise Refusal('Bounded native crossfade did not return idle')
                wait(.01)
            result['final_status'] = final
            if session.pending:
                raise Refusal('Accepted records lack arrival witnesses')
            result['arrival_records'] = session.arrival_records
            result['clock_fit'] = session.clock.report()
            result['media_route'] = prepared['spec']['timing']
            player.close()
            player = None
            result['completed_stream'] = True
            result['limits'] = 'FIFO arrival pacing; audio render-position estimate only. Native physical_timestamp_valid remains false. No optical or acoustic claim.'
            return result
        except Exception as exc:
            (Path(out) / 'drive-abort.json').write_text(json.dumps({
                'reason': str(exc), 'boot': session.boot, 'trial': session.trial,
                'records_acked': session.sequence, 'arrival_records': session.arrival_records,
                'exchange_failed_or_ambiguous': session.failed, 'clock_fit': session.clock.report(),
                'physical_timing_qualified': False, 'optical_verified': False}, indent=2))
            raise
        finally:
            # A failed exchange is ambiguous: no retry/late close over that link.
            # Closing the owner port triggers native disconnect; otherwise close
            # valid session and retain native finite 250ms lease/150ms fallback.
            try:
                session.close()
            finally:
                if player is not None:
                    player.abort()


def main():
    """Offline request preparation only; hardware stays in AEL bench-trial-control."""
    import argparse
    parser = argparse.ArgumentParser(description=main.__doc__)
    for name in ('trace', 'freeze', 'verification', 'verifier', 'media', 'timing'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--arm', choices=('A', 'B', 'C', 'D'), required=True)
    parser.add_argument('--max-lateness-us', type=int, default=20000)
    parser.add_argument('--max-chunk', type=int, default=4)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('out must be new')
    def binding(path):
        return {'path': str(path.resolve()), 'sha256': file_hash(path)}
    spec = {key: binding(getattr(args, key)) for key in ('trace', 'freeze', 'verification', 'verifier', 'media')}
    spec.update(player=binding(PLAYER), arm=args.arm, timing=json.loads(args.timing.read_text()),
                max_lateness_us=args.max_lateness_us, max_chunk=args.max_chunk)
    prepared = prepare_request(spec)
    words = prepared['trace']['display_mapping']['settings_words']
    fields = {str(index + 1): struct.unpack('<f', struct.pack('<I', word))[0] if index < 8 else word
              for index, word in enumerate(words) if index != 12}
    validate_scene_fields(fields, prepared)
    operation = {'schema': 'prism.titan.evaluation-drive-request.v1', 'fields': fields, 'save': False,
                 'evaluation_drive': spec}
    with args.out.open('x') as output:
        output.write(json.dumps(operation, indent=2) + '\n')
    print('DRIVE_REQUEST_PREPARED HOST_ONLY arm=' + args.arm + ' trace=' + prepared['trace']['trace_sha256'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
