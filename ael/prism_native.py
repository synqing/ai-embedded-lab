"""Titan native CDC binding, derived from platform/titan/transport/control.h.

No donor telemetry, scanning, reset, retry or implicit serial-owner takeover.
"""
import base64
import json
from pathlib import Path
import struct
import time
import secrets
import zlib

SCHEMA = '82cf001c2e21da98ac7047c8c594f9d3de8bfa57c607f3e136c143e5c9ce2be6'
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
    if len(body) != 160 or struct.unpack_from('<I', body)[0] != 0x454D5354: raise ValueError('Wrong control state')
    if body[108:140].hex() != SCHEMA: raise ValueError('Wrong control schema')
    return {'boot': struct.unpack_from('<I', body, 12)[0], 'revision': struct.unpack_from('<I', body, 16)[0],
            'request': struct.unpack_from('<I', body, 20)[0], 'mode': struct.unpack_from('<I', body, 60)[0],
            'brightness': struct.unpack_from('<I', body, 68)[0], 'accepted': struct.unpack_from('<I', body, 76)[0],
            'rendered': struct.unpack_from('<I', body, 80)[0], 'emitted': struct.unpack_from('<I', body, 84)[0]}


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


def read_exact(port, n):
    deadline = time.monotonic() + 3; output = bytearray()
    while len(output) < n and time.monotonic() < deadline:
        b = port.read(n - len(output))
        if b: output.extend(b)
    if len(output) != n: raise TimeoutError('Native response deadline; no automatic retry')
    return bytes(output)


def run_session(manifest, out, seconds, operation=None):
    import serial
    # Caller holds AEL's hardware transaction lock and validates sole ownership.
    port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=1)
    port.dtr = False; port.rts = False; port.port = manifest['port']
    sequence = 0; cookie = 0x50524953
    raw = Path(out) / 'titan-native.jsonl'
    with raw.open('x') as log:
        def exchange(opcode, payload=b''):
            nonlocal sequence
            sequence += 1
            q = request(opcode, payload, sequence, cookie)
            if port.write(q) != len(q): raise IOError('Incomplete native request write')
            header = read_exact(port, 32)
            length = struct.unpack_from('<I', header, 16)[0]
            if length > 4096: raise ValueError('Oversized native response')
            packet = header + read_exact(port, length)
            log.write(json.dumps({'opcode': opcode, 'sequence': sequence,
                                 'request': base64.b64encode(q).decode(), 'response': base64.b64encode(packet).decode()}) + '\n')
            log.flush()
            return response(packet, sequence, cookie)
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
                op = json.loads(Path(operation).read_text())
                exchange(0x50520001, bind_payload(boot))
                command = secrets.randbelow(0xFFFFFFFD) + 1
                initial = state(exchange(25, struct.pack('<4I', 0x454D0101, command, boot, 0)))
                applied = state(exchange(25, patch_payload(op['fields'], boot, initial['revision'], command + 1)))
                if applied['boot'] != boot or applied['request'] != command + 1: raise ValueError('Wrong applied control identity')
                result['controls'].append(applied)
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
