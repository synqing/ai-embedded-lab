"""Titan native CDC binding, derived from platform/titan/transport/control.h.

No donor telemetry, scanning, reset, retry or implicit serial-owner takeover.
"""
import base64
import json
import math
from pathlib import Path
import struct
import subprocess
import time
import secrets
import zlib

SCHEMA = '5dda123060c60de0ff6777b63ab6c3cdc96ddd2ab4298b2501d781c8ab20c0b1'
UID = '545433931bd25436593630352d068363'


def request(opcode, payload=b'', sequence=1, cookie=1):
    if len(payload) > 2048: raise ValueError('Oversized request')
    header = b'K1S1' + struct.pack('<6I', opcode, sequence, cookie, len(payload), zlib.crc32(payload), 1)
    return header + struct.pack('<I', zlib.crc32(header)) + payload


def response(packet, sequence=1, cookie=1):
    if len(packet) < 32 or packet[:4] != b'K1R1': raise ValueError('Wrong native response header')
    status, seq, observed_cookie, n, reserved, crc, hcrc = struct.unpack_from('<7I', packet, 4)
    if n > 4096 or len(packet) != 32 + n: raise ValueError('Response length')
    if seq != sequence or observed_cookie != cookie or reserved != 0: raise ValueError('Stale/wrong response identity')
    if zlib.crc32(packet[:28]) != hcrc or zlib.crc32(packet[32:]) != crc: raise ValueError('Response CRC')
    if status: raise ValueError('Native rejection status ' + str(status))
    return packet[32:]


def bind_payload(boot):
    if boot <= 0: raise ValueError('Invalid boot')
    return UID.encode() + bytes.fromhex(SCHEMA) + struct.pack('<I', boot)


def patch_payload(fields, boot, revision, command):
    rows = sorted((int(k), v) for k, v in fields.items())
    if not rows or len(rows) > 18 or len({k for k, _ in rows}) != len(rows): raise ValueError('Invalid field set')
    mask = 0; entries = b''
    for field, value in rows:
        if not 1 <= field <= 18: raise ValueError('Unsupported field')
        index = field - 1
        kind = 1 if index < 8 else 3 if index == 8 else 4 if index in (14, 17) else 2
        encoded = struct.pack('<f', float(value)) if kind == 1 else struct.pack('<I', value)
        entries += struct.pack('<HH', field, kind) + encoded
        mask |= 1 << index
    return struct.pack('<6I', 0x454D0102, revision, command, boot, mask, len(rows)) + entries


def state(body):
    from ael.prism_control_checks import decode_state
    return decode_state(body, SCHEMA)


def snapshot(body, source_binding):
    if len(body) != 1184 or struct.unpack_from('<I', body)[0] != 0x53564C54: raise ValueError('Wrong native snapshot')
    version, flags = struct.unpack_from('<HH', body, 4)
    # Observation::snapshot/flags encode this fixed schema. Bit0 qualifies the
    # native source; bit1 is warming, bit2 is stale, bit3 marks unqualified
    # physical timestamps and bit4 is the current output setting. Time alone
    # cannot make capture metadata valid.
    if version != 1 or flags & ~31 or bool(flags & 1) == bool(flags & 2):
        raise ValueError('Unsupported native snapshot version/flags')
    if body[728:744].hex() != UID or body[744:776].hex() != source_binding or body[776:808].hex() != SCHEMA:
        raise ValueError('Snapshot UID/source/schema mismatch')
    u32 = lambda p: struct.unpack_from('<I', body, p)[0]
    u64 = lambda p: struct.unpack_from('<Q', body, p)[0]
    reasons = {0:'None', 0x50520001:'HostRecovery', 0x50520002:'DriverError',
               0x50520003:'Stall', 0x50520004:'SequenceWrap',
               0x50520005:'RingOverwrite', 0x50520006:'Restart'}
    reason = u32(616)
    return {'snapshot_version':version, 'flags':flags, 'capture_valid':bool(flags & 1),
            'warming':bool(flags & 2), 'stale':bool(flags & 4),
            'physical_timestamp_valid':not bool(flags & 8),
            'uid':body[728:744].hex(), 'source_binding':body[744:776].hex(),
            'schema_sha256':body[776:808].hex(),
            'last_invalidate_reason':reason, 'last_invalidate_reason_name':reasons.get(reason, 'Unknown'),
            'generation':u64(8), 'epoch':u64(16), 'capture_time_us':u64(32), 'publish_time_us':u64(40),
            'sample_end':u64(48), 'pcm_peak':struct.unpack_from('<f',body,96)[0],
            'revision':u32(604), 'hops':u32(608), 'rejected_hops':u32(612),
            'source_rate':u32(624), 'ap_cycles':u32(632), 'vp_cycles':u32(636),
            'rendered_request':u32(812), 'rendered_revision':u32(816), 'logical_frame':u32(820),
            'accepted_request':u32(832), 'emitted_request':u32(840)}


CAPTURE_QUEUE = 0x50524C04
CAPTURE_STAGES = ('none', 'coefficients', 'resample_excluding_hops', 'runtime',
                  'source', 'bank', 'observer', 'proxy', 'render', 'usb', 'hop')


def capture_queue(body):
    """Decode the additive boot-bound capture witness; snapshot stays1184bytes."""
    if len(body) != 1536:
        raise ValueError('Unsupported capture queue witness length/schema')
    magic, version, size = struct.unpack_from('<3I', body)
    if magic != 0x51544C54 or version not in (1, 2) or size != 1536:
        raise ValueError('Unsupported capture queue witness length/schema')
    u32 = lambda p: struct.unpack_from('<I', body, p)[0]
    u64 = lambda p: struct.unpack_from('<Q', body, p)[0]
    result = dict(schema=f'prism.titan.capture-queue.v{version}', clock_hz=u32(12),
        producer=u32(16), consumer=u32(20), unread=u32(24), max_unread=u32(28),
        source_rate=u32(32), coefficient_builds=u32(36), overwrite_events=u64(40),
        dropped_blocks=u64(48), copy_races=u64(56), consumed_blocks=u64(64),
        longest_consumption_gap_us=u64(72), longest_gap_end_visit_backlog=u32(80),
        current_stage=u32(84), last_stage=u32(88), history_count=u32(92),
        history_overwritten=u32(96), first_fault_valid=u32(100),
        first_time_us=u64(104), first_cycles=u32(112), first_producer=u32(116),
        first_consumer=u32(120), first_rate=u32(124), first_coefficient_builds=u32(128),
        first_stage=u32(132), first_last_stage=u32(136), first_history_count=u32(140),
        first_history_overwritten=u32(144), preroll_blocks=u64(152),
        valid_stream_boundary_us=u64(160), overhead_last_cycles=u32(168),
        overhead_max_cycles=u32(172), overhead_count=u64(176),
        overhead_sum_cycles=u64(184), interval_overflow=u32(192),
        irq_overhead_max_cycles=u32(196), first_history_copy_race=u32(200))
    if not result['clock_hz'] or result['first_fault_valid'] not in (0, 1):
        raise ValueError('Invalid capture queue witness clock/first fault')
    if result['unread'] != ((result['producer']-result['consumer']) & 0xFFFFFFFF) or result['max_unread'] < result['unread']:
        raise ValueError('Inconsistent capture queue witness backlog')
    if result['longest_gap_end_visit_backlog'] > result['max_unread']:
        raise ValueError('Capture gap backlog exceeds recorded maximum')
    for key in ('current_stage','last_stage','first_stage','first_last_stage'):
        if result[key] >= len(CAPTURE_STAGES): raise ValueError('Unknown capture queue stage')
    if result['history_count'] > 16 or result['first_history_count'] > 16:
        raise ValueError('Oversized bounded capture queue history')
    if result['first_history_copy_race'] not in (0, 1):
        raise ValueError('Invalid capture queue first-history copy-race flag')
    result['stages'] = []
    for stage in range(len(CAPTURE_STAGES)):
        count, total, maximum, overflow = struct.unpack_from('<QQII', body, 208+stage*24)
        result['stages'].append(dict(stage=CAPTURE_STAGES[stage], count=count,
                                    sum_cycles=total, maximum_cycles=maximum, overflow=overflow))
    def history(offset, count):
        rows=[]
        for i in range(count):
            start, wall, exclusive, stage, producer, consumer, backlog = struct.unpack_from('<Q6I', body, offset+i*32)
            if stage >= len(CAPTURE_STAGES) or exclusive > wall:
                raise ValueError('Invalid capture queue stage history')
            rows.append(dict(start_us=start, wall_cycles=wall, exclusive_cycles=exclusive,
                stage=CAPTURE_STAGES[stage], producer=producer, consumer=consumer, start_backlog=backlog))
        return rows
    result['history'] = history(472, result['history_count'])
    result['first_history'] = history(984, result['first_history_count'])
    result['longest_gap_observation'] = None
    result['gap_time_scope'] = 'AFTER_PROCESSING_CONSUMED_CALLS; VISIT_BACKLOG_SAMPLED_BEFORE_COPY; DMA_PHASE_UNMEASURED'
    if version == 2:
        if result['longest_consumption_gap_us']:
            if u32(1496) != 0x47415031:
                raise ValueError('Missing version-2 capture gap endpoint witness')
            previous, ending = u64(1500), u64(1508)
            if ending <= previous or ending-previous != result['longest_consumption_gap_us']:
                raise ValueError('Inconsistent capture gap endpoint times')
            if u32(1516) > result['max_unread']:
                raise ValueError('Capture gap backlog exceeds recorded maximum')
            result['longest_gap_observation'] = dict(previous_consumed_us=previous,
                ending_consumed_us=ending, previous_visit_backlog=u32(1516),
                ending_visit_backlog=u32(80), previous_producer=u32(1520),
                ending_producer=u32(1524), previous_consumer=u32(1528), ending_consumer=u32(1532))
        elif any(body[1496:]):
            raise ValueError('Unexpected endpoint witness without a consumption gap')
    return result


def window(first, last):
    for snap in (first, last):
        if 'capture_valid' in snap and (snap['capture_valid'] is not True or snap.get('warming') is not False or snap.get('stale') is not False):
            raise ValueError('Invalid native capture metadata in window')
    if first['epoch'] != last['epoch']: raise ValueError('Capture epoch changed in settled window')
    for key in ('uid','source_binding','schema_sha256','source_rate'):
        if key in first and first.get(key) != last.get(key): raise ValueError('Capture source identity changed: '+key)
    dt = last['capture_time_us'] - first['capture_time_us']
    samples = last['sample_end'] - first['sample_end']; hops = last['hops'] - first['hops']
    if dt <= 0 or samples <= 0 or hops <= 0: raise ValueError('Native capture did not advance')
    for key in ('rejected_hops', 'logical_frame'):
        if type(first[key]) is not int or type(last[key]) is not int or last[key] < first[key]:
            raise ValueError('Native counter reset/wrap: '+key)
    return {'device_window_us':dt, 'analysis_samples':samples, 'analysis_hops':hops,
            'analysis_sample_rate_hz':samples*1000000/dt, 'analysis_hop_rate_hz':hops*1000000/dt,
            'rejected_hop_delta':last['rejected_hops']-first['rejected_hops'],
            'logical_frame_delta':last['logical_frame']-first['logical_frame'],
            'physical_output_rate_measured':False, 'host_arrival_cadence_used':False}


def read_exact(port, n, timeout=3, *, progress=None, absolute_deadline=None,
               cancel_event=None, monotonic=None):
    now = monotonic or time.monotonic
    deadline = now() + timeout
    if absolute_deadline is not None:
        if type(absolute_deadline) not in (int, float) or not math.isfinite(absolute_deadline):
            raise ValueError('Invalid native absolute deadline')
        deadline = min(deadline, absolute_deadline)
    output = bytearray()
    original_timeout = getattr(port, 'timeout', None)
    try:
        while len(output) < n and now() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError('Native response cancelled; no automatic retry')
            if hasattr(port, 'timeout'):
                remaining = max(0, deadline-now())
                port.timeout = min(.2,original_timeout,remaining) if original_timeout is not None else min(.2,remaining)
            started = now()
            b = port.read(n - len(output))
            if b: output.extend(b)
            if progress is not None:
                progress.append({'started_monotonic':started,
                                 'ended_monotonic':now(),
                                 'bytes':len(b), 'total_bytes':len(output)})
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError('Native response cancelled; no automatic retry')
            if now() > deadline:
                raise TimeoutError('Native read returned after absolute deadline; no automatic retry')
    except BaseException as exc:
        exc.partial = bytes(output)
        raise
    finally:
        if hasattr(port, 'timeout'): port.timeout = original_timeout
    if len(output) != n:
        error = TimeoutError('Native response deadline; no automatic retry')
        error.partial = bytes(output)
        raise error
    return bytes(output)



def prepare_retained_witness(spec):
    """Read-only operation: no source selection, preamble, settings or SAVE."""
    if type(spec) is not dict or spec:
        raise ValueError('Retained witness requires an empty explicit specification')


def retained_witness(exchange, manifest, out, initial):
    """Consume the existing sole-owner exchange; its raw log precedes decoding.

    BIND sets only ControlOwner's host binding in native.cpp/control.h. It does
    not clear capture/output history, select source or change settings. Snapshot
    is read before BIND; queue and transmitter require that actual boot binding.
    This readout does not prove power loss, host absence or continuous light.
    """
    from ael.prism_completion import require_healthy
    boot = initial['boot_id']
    if type(boot) is not int or not 0 < boot <= 0xFFFFFFFF:
        raise ValueError('Invalid retained witness boot identity')
    row = {'schema': 'titan.retained-witness.v1', 'identity': initial,
           'raw_replies': {}, 'complete': False, 'optical_verified': False,
           'host_absence_verified': False, 'physical_latency': 'UNMEASURED'}
    try:
        raw = exchange(23)
        row['raw_replies']['snapshot'] = raw.hex()
        row['snapshot'] = snapshot(raw, manifest['source_binding_hash'])
        exchange(0x50520001, bind_payload(boot))
        raw = exchange(CAPTURE_QUEUE, struct.pack('<I', boot))
        row['raw_replies']['capture_queue'] = raw.hex()
        row['capture_queue'] = capture_queue(raw)
        raw = exchange(0x50524C02, struct.pack('<I', boot))
        row['raw_replies']['transmitter'] = raw.hex()
        row['transmitter'] = json.loads(raw)
        require_healthy(initial)
        for key in ('capture_clock_rejections', 'capture_restart_attempts',
                    'output_recovery_attempts', 'persistence_errors'):
            if type(initial.get(key)) is not int or initial[key] != 0:
                raise ValueError('Retained witness startup counter fault: ' + key)
        snap, queue, tx = row['snapshot'], row['capture_queue'], row['transmitter']
        if (snap['capture_valid'] is not True or snap['warming'] is not False or
                snap['stale'] is not False or snap['last_invalidate_reason'] != 0 or
                snap['rejected_hops'] != 0 or not all(snap[k] > 0 for k in
                ('epoch', 'capture_time_us', 'sample_end', 'hops', 'logical_frame'))):
            raise ValueError('Retained witness capture is not healthy and ready')
        if (queue['clock_hz'] != initial['clock_hz'] or
                queue['source_rate'] != snap['source_rate'] or
                not 14000 <= snap['source_rate'] <= 64000 or
                not queue['consumed_blocks'] or not queue['valid_stream_boundary_us'] or
                any(queue[k] != 0 for k in ('overwrite_events', 'dropped_blocks',
                    'copy_races', 'first_fault_valid', 'interval_overflow')) or
                any(s['overflow'] for s in queue['stages'])):
            raise ValueError('Retained witness capture queue fault')
        if (tx.get('schema') != 'prism.titan.transmitter.v2' or
                any(type(tx.get(k)) is not int or tx[k] != 0 for k in
                    ('first_fault', 'failures', 'last_fsp_error', 'pattern_requested')) or
                type(tx.get('wire_reset_completions')) is not int or
                tx['wire_reset_completions'] <= 0):
            raise ValueError('Retained witness transmitter fault')
        row['complete'] = True
        return row
    except BaseException as exc:
        row['error'] = str(exc)
        raise
    finally:
        # Even malformed/failed/partial replies survive in titan-native.jsonl;
        # this decoded summary is additional evidence, never a physical PASS.
        try:
            summary = json.dumps(row, indent=2, allow_nan=False)
        except ValueError:
            # Malformed non-finite JSON must not mask the primary rejection.
            # Original bytes are already durable in the native exchange log.
            summary = json.dumps({'schema': row['schema'], 'complete': False,
                'error': row.get('error', 'Non-finite decoded witness'),
                'raw_replies': row['raw_replies'], 'raw_identity_log': 'titan-native.jsonl',
                'host_absence_verified': False, 'optical_verified': False}, indent=2)
        with (Path(out) / 'titan-retained-witness.json').open('x') as log:
            log.write(summary + '\n')


def run_session(manifest, out, seconds, operation=None, *, deadline=None, operation_sha256=None, cancel_event=None):
    isolated = bool(manifest.get('isolated_qualification'))
    if isolated:
        from ael.titan_isolated import preflight, completion_request
        from ael.titan_waveform import bound
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= time.monotonic():
            raise ValueError('Isolated session requires the transaction absolute deadline')
        if not operation or not operation_sha256:
            raise ValueError('Isolated operation requires its immutable sha256')
        op = json.loads(bound({'path':str(operation), 'sha256':operation_sha256}))
        if not isinstance(op, dict) or set(op) not in ({'completion'}, {'isolated_capture'}):
            raise ValueError('Isolated operation must be exactly completion or isolated_capture')
        preflight(manifest, consume=False)
        admitted = completion_request(manifest)
        if admitted is not None:
            if op != {'completion':admitted}:
                raise ValueError('Completion differs from the admitted immutable request')
        else:
            q = manifest['isolated_qualification']
            raw = op.get('isolated_capture', {})
            expected = {'frames':q['frames'], 'budget_seconds':raw.get('budget_seconds'),
                        **{k:q[k] for k in ('pattern','constant_timer_diagnostic') if k in q}}
            budget = raw.get('budget_seconds')
            if raw != expected or type(budget) not in (int,float) or not math.isfinite(budget) or not 0 < budget <= 60:
                raise ValueError('Raw capture differs from the admitted isolated scope')
    else:
        op = json.loads(Path(operation).read_text()) if operation else None
    if op and 'retained_witness' in op:
        if set(op) != {'retained_witness'}:
            raise ValueError('Retained witness cannot combine with control, replay, completion, capture or SAVE')
        prepare_retained_witness(op['retained_witness'])
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 120:
            raise ValueError('Retained witness requires a bounded 1..120 second readout')
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise ValueError('Invalid retained witness absolute deadline')
        witness_cutoff = time.monotonic() + seconds
        deadline = min(deadline, witness_cutoff) if deadline is not None else witness_cutoff
    if op and 'disconnect_check' in op:
        from ael.prism_disconnect import prepare
        if set(op) != {'disconnect_check'}:
            raise ValueError('Disconnect check cannot combine with control, replay, completion, capture or SAVE')
        prepare(op['disconnect_check'])
    if op and 'completion' in op:
        from ael.prism_completion import prepare
        if set(op) != {'completion'}:
            raise ValueError('Completion is session-only, mutually exclusive with drive and control PATCH')
        prepare(op['completion'])  # Before importing/opening a serial owner.
        if op['completion']['kind'] == 'endurance':
            # One collector cutoff includes initial identity/bind and all child windows.
            collector_deadline = time.monotonic() + 1100
            deadline = min(deadline, collector_deadline) if deadline is not None else collector_deadline
    if op and 'isolated_capture' in op:
        from ael.titan_isolated import preflight
        if set(op) != {'isolated_capture'}:
            raise ValueError('Isolated capture cannot combine with control, replay, completion or SAVE')
        if not isolated: preflight(manifest, consume=False)
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= time.monotonic():
            raise ValueError('Isolated session requires the transaction absolute deadline')
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError('Native session cancelled before opening owner')
    if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=time.monotonic()):
        raise ValueError('Native session requires a finite future absolute deadline')
    import serial
    # Caller holds AEL's hardware transaction lock and validates sole ownership.
    port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=1)
    # Every admitted native CDC owner asserts DTR. Its actual falling edge on
    # close is the device's client-loss signal; RTS never requests a reset.
    port.dtr = True; port.rts = False; port.port = manifest['port']
    sequence = 0; cookie = 0x50524953
    raw = Path(out) / 'titan-native.jsonl'
    with raw.open('x') as log:
        session_cancel = cancel_event
        def exchange(opcode, payload=b'', *, absolute_deadline=None, cancel_event=None):
            nonlocal sequence
            sequence += 1
            q = request(opcode, payload, sequence, cookie)
            from ael.prism_drive import uptime_ns
            before_ns = uptime_ns()
            header=packet=b''; written=None; error=None; complete=False
            header_reads=[]; body_reads=[]
            try:
                cancelled = cancel_event or session_cancel
                cutoff = deadline
                if absolute_deadline is not None:
                    if type(absolute_deadline) not in (int,float) or not math.isfinite(absolute_deadline):
                        raise ValueError('Invalid native exchange absolute deadline')
                    cutoff = min(cutoff,absolute_deadline) if cutoff is not None else absolute_deadline
                if cancelled is not None and cancelled.is_set():
                    raise InterruptedError('Native request cancelled; no automatic retry')
                deadline_s = .02 if opcode == 0x50524402 else 1 if opcode == 0x50524606 else 3
                if cutoff is not None:
                    remaining = cutoff - time.monotonic()
                    if remaining <= 0: raise TimeoutError('Native transaction deadline before write')
                    port.write_timeout = min(1, remaining)
                    deadline_s = min(deadline_s, remaining)
                port.write_timeout = min(1, deadline_s)
                written=port.write(q)
                if cancelled is not None and cancelled.is_set():
                    raise InterruptedError('Native write cancelled; no automatic retry')
                if written != len(q): raise IOError('Incomplete native request write')
                read_budget = max(0, deadline_s - (uptime_ns() - before_ns) / 1e9)
                if cutoff is not None:
                    read_budget = min(read_budget, max(0, cutoff - time.monotonic()))
                    port.timeout = min(.2, read_budget)
                header = read_exact(port, 32, read_budget, progress=header_reads, absolute_deadline=cutoff, cancel_event=cancelled)
                packet=header
                length = struct.unpack_from('<I', header, 16)[0]
                if length > 4096: raise ValueError('Oversized native response')
                remaining_s = max(0, deadline_s - (uptime_ns() - before_ns) / 1e9)
                if cutoff is not None:
                    remaining_s = min(remaining_s, max(0, cutoff - time.monotonic()))
                    port.timeout = min(.2, remaining_s)
                packet = header + read_exact(port, length, remaining_s, progress=body_reads, absolute_deadline=cutoff, cancel_event=cancelled)
                complete=True
                return response(packet, sequence, cookie)
            except BaseException as exc:
                if hasattr(exc,'partial'): packet=header+exc.partial
                error=str(exc)
                raise
            finally:
                log.write(json.dumps({'opcode': opcode, 'sequence': sequence,
                    'before_uptime_ns': before_ns, 'after_uptime_ns': uptime_ns(),
                    'request':base64.b64encode(q).decode(),'write_bytes':written,
                    'response':base64.b64encode(packet).decode(),'response_complete':complete,
                    'error':error, 'header_reads':header_reads,'body_reads':body_reads})+'\n')
                log.flush()
        try:
            port.open()
            info = json.loads(exchange(1))
            if info.get('uid') != UID or info.get('schema_sha256') != SCHEMA:
                raise ValueError('Wrong native UID/schema')
            if info.get('build_source_sha256') != manifest['source_binding_hash']:
                raise ValueError('Runtime source identity mismatch')
            if info.get('initialisation_failed') is True and not (op and 'retained_witness' in op):
                raise ValueError('Native initialisation failed')
            boot = info['boot_id']
            if not isinstance(boot, int) or boot <= 0: raise ValueError('Invalid native boot identity')
            result = {'identity': info, 'controls': [], 'records': 0}
            if op and 'retained_witness' in op:
                result['retained_witness'] = retained_witness(exchange, manifest, out, info)
                result['optical_verified'] = False
                result['host_absence_verified'] = False
                return result
            if operation:
                exchange(0x50520001, bind_payload(boot))
                if 'disconnect_check' in op:
                    from ael.prism_disconnect import execute
                    def owner_state():
                        return {'port':port.port,'is_open':port.is_open,'dtr':port.dtr,'rts':port.rts}
                    def close_owner():
                        port.close()
                        return owner_state()
                    def reopen_owner():
                        owner = subprocess.run(['lsof','-t',manifest['port']],capture_output=True,text=True,check=False,timeout=3)
                        if owner.returncode != 1 or owner.stdout.strip() or owner.stderr.strip():
                            raise ValueError('Interface owner appeared during disconnect; no takeover')
                        port.dtr=True;port.rts=False;port.open()
                        return owner_state()
                    result['disconnect_check']=execute(exchange,close_owner,reopen_owner,manifest,
                        op['disconnect_check'],out,info)
                    result['runtime_boot_verified']=True
                    result['optical_verified']=False
                    return result
                if 'isolated_capture' in op:
                    from ael.titan_loopback import acquire
                    result['isolated_capture'] = acquire(exchange, manifest, op['isolated_capture'], out, info,
                                                        absolute_deadline=deadline)
                    result['runtime_boot_verified'] = True
                    result['optical_verified'] = False
                    return result
                if 'completion' in op:
                    from ael.prism_completion import execute
                    result['completion'] = execute(exchange, manifest, op['completion'], out, info,
                                                   deadline=deadline, cancel_event=cancel_event)
                    measured = result['completion']
                    if measured.get('kind') == 'measure' and measured.get('startup', {}).get('status') != 'PASS':
                        raise ValueError('Native completion startup failed; boot-to-ready evidence preserved')
                    if measured.get('kind') == 'measure' and not all(measured.get(k) is True for k in
                            ('proxy_budget_met', 'hop_deadline_met', 'render_deadline_met')):
                        raise ValueError('Native completion measurement failed a required timing budget; evidence preserved')
                    result['runtime_boot_verified'] = True
                    result['optical_verified'] = False
                    return result
                command = secrets.randbelow(0xFFFFFFFD) + 1
                initial = state(exchange(25, struct.pack('<4I', 0x454D0101, command, boot, 0)))
                from ael.prism_drive import prepare_request, validate_scene_fields, stream
                prepared = prepare_request(op['evaluation_drive']) if 'evaluation_drive' in op else None
                if prepared:
                    validate_scene_fields(op['fields'], prepared)
                applied = state(exchange(25, patch_payload(op['fields'], boot, initial['revision'], command + 1)))
                from ael.prism_control_checks import verify_applied, verify_readback
                verify_applied(initial, applied, op['fields'], boot=boot, request=command + 1)
                result['controls'].append(applied)
                observed = state(exchange(25, struct.pack('<4I', 0x454D0101, command + 2, boot, 0)))
                verify_readback(applied, observed, boot=boot, request=command + 2)
                result['control_readback'] = observed
                if prepared:
                    if op.get('save'):
                        raise ValueError('Experimental drive/scene is session-only; no save')
                    port.timeout = .005
                    result['evaluation_drive'] = stream(exchange, manifest, prepared, out)
                    result['runtime_boot_verified'] = True
                    result['optical_verified'] = False
                    return result
                if op.get('save') is True:
                    exchange(0x50520002, struct.pack('<2I', boot, applied['revision']))
                    result['save_returned_success'] = True
            snapshots = []
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                latest = json.loads(exchange(1))
                if latest.get('boot_id') != boot: raise ValueError('Boot changed during native observation')
                exchange(21)
                snapshots.append(snapshot(exchange(23), manifest['source_binding_hash']))
                for opcode in (24, 26): exchange(opcode)
                result['records'] += 1
                time.sleep(.25)
            result['window'] = window(snapshots[0], snapshots[-1])
            result['final_identity'] = latest
            result['first_snapshot'] = snapshots[0]; result['last_snapshot'] = snapshots[-1]
            result['limits'] = 'Logical/render and emitted-request witnesses; no direct per-half completed-DMA rate or optical measurement'
            result['runtime_boot_verified'] = True
            result['optical_verified'] = False
            return result
        finally:
            port.close()
