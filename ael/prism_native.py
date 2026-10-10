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
    if body[728:744].hex() != UID or body[744:776].hex() != source_binding or body[776:808].hex() != SCHEMA:
        raise ValueError('Snapshot UID/source/schema mismatch')
    u32 = lambda p: struct.unpack_from('<I', body, p)[0]
    u64 = lambda p: struct.unpack_from('<Q', body, p)[0]
    return {'generation':u64(8), 'epoch':u64(16), 'capture_time_us':u64(32), 'publish_time_us':u64(40),
            'sample_end':u64(48), 'pcm_peak':struct.unpack_from('<f',body,96)[0],
            'revision':u32(604), 'hops':u32(608), 'rejected_hops':u32(612),
            'source_rate':u32(624), 'ap_cycles':u32(632), 'vp_cycles':u32(636),
            'rendered_request':u32(812), 'rendered_revision':u32(816), 'logical_frame':u32(820),
            'accepted_request':u32(832), 'emitted_request':u32(840)}


def window(first, last):
    if first['epoch'] != last['epoch']: raise ValueError('Capture epoch changed in settled window')
    dt = last['capture_time_us'] - first['capture_time_us']
    samples = last['sample_end'] - first['sample_end']; hops = last['hops'] - first['hops']
    if dt <= 0 or samples <= 0 or hops <= 0: raise ValueError('Native capture did not advance')
    return {'device_window_us':dt, 'analysis_samples':samples, 'analysis_hops':hops,
            'analysis_sample_rate_hz':samples*1000000/dt, 'analysis_hop_rate_hz':hops*1000000/dt,
            'rejected_hop_delta':last['rejected_hops']-first['rejected_hops'],
            'logical_frame_delta':last['logical_frame']-first['logical_frame'],
            'physical_output_rate_measured':False, 'host_arrival_cadence_used':False}


def read_exact(port, n, timeout=3, *, progress=None):
    deadline = time.monotonic() + timeout; output = bytearray()
    original_timeout = getattr(port, 'timeout', None)
    try:
        while len(output) < n and time.monotonic() < deadline:
            if hasattr(port, 'timeout'):
                remaining = max(0, deadline-time.monotonic())
                port.timeout = min(original_timeout,remaining) if original_timeout is not None else remaining
            started = time.monotonic()
            b = port.read(n - len(output))
            if b: output.extend(b)
            if progress is not None:
                progress.append({'started_monotonic':started,
                                 'ended_monotonic':time.monotonic(),
                                 'bytes':len(b), 'total_bytes':len(output)})
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


def run_session(manifest, out, seconds, operation=None, *, deadline=None, operation_sha256=None):
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
    if op and 'isolated_capture' in op:
        from ael.titan_isolated import preflight
        if set(op) != {'isolated_capture'}:
            raise ValueError('Isolated capture cannot combine with control, replay, completion or SAVE')
        if not isolated: preflight(manifest, consume=False)
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= time.monotonic():
            raise ValueError('Isolated session requires the transaction absolute deadline')
    import serial
    # Caller holds AEL's hardware transaction lock and validates sole ownership.
    port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=1)
    # Every admitted native CDC owner asserts DTR. Its actual falling edge on
    # close is the device's client-loss signal; RTS never requests a reset.
    port.dtr = True; port.rts = False; port.port = manifest['port']
    sequence = 0; cookie = 0x50524953
    raw = Path(out) / 'titan-native.jsonl'
    with raw.open('x') as log:
        def exchange(opcode, payload=b''):
            nonlocal sequence
            sequence += 1
            q = request(opcode, payload, sequence, cookie)
            from ael.prism_drive import uptime_ns
            before_ns = uptime_ns()
            header=packet=b''; written=None; error=None; complete=False
            header_reads=[]; body_reads=[]
            try:
                deadline_s = .02 if opcode == 0x50524402 else 1 if opcode == 0x50524606 else 3
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TimeoutError('Isolated transaction deadline before native write')
                    port.write_timeout = min(1, remaining)
                    deadline_s = min(deadline_s, remaining)
                written=port.write(q)
                if written != len(q): raise IOError('Incomplete native request write')
                read_budget = max(0, deadline_s - (uptime_ns() - before_ns) / 1e9)
                if deadline is not None:
                    read_budget = min(read_budget, max(0, deadline - time.monotonic()))
                    port.timeout = min(.2, read_budget)
                header = read_exact(port, 32, read_budget, progress=header_reads)
                packet=header
                length = struct.unpack_from('<I', header, 16)[0]
                if length > 4096: raise ValueError('Oversized native response')
                remaining_s = max(0, deadline_s - (uptime_ns() - before_ns) / 1e9)
                if deadline is not None:
                    remaining_s = min(remaining_s, max(0, deadline - time.monotonic()))
                    port.timeout = min(.2, remaining_s)
                packet = header + read_exact(port, length, remaining_s, progress=body_reads)
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
            if info.get('initialisation_failed') is True: raise ValueError('Native initialisation failed')
            boot = info['boot_id']
            if not isinstance(boot, int) or boot <= 0: raise ValueError('Invalid native boot identity')
            result = {'identity': info, 'controls': [], 'records': 0}
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
                                                   **({'deadline': deadline} if deadline is not None else {}))
                    measured = result['completion']
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
