"""Explicit development bench trials; never general product release admission.

Manifests are invocation inputs, not assignment registries or certificates.
Planning is offline. Writes require fresh independently obtained identity/owner
receipts, scoped Captain decisions and a bound recovery image before programming.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TARGETS = {
    'prism_rt1062_t40_bench128_diag': ('dualmcu', '20731830', 'teensy'),
    'prism_s3_ble_bench16_diag': ('dualmcu', '30:ED:A0:29:A1:C4', 's3'),
    'titan-replacement': ('titan', '545433931bd25436593630352d068363', 'titan'),
    'titan-native': ('titan', '545433931bd25436593630352d068363', 'titan'),
}
RFP_BACKEND = Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001/scripts/programme_rfp_swd.py')
PYTHON = '/Users/spectrasynq/.platformio/penv/bin/python'
TEENSY = '/Users/spectrasynq/.platformio/packages/tool-teensy/teensy_loader_cli'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bound_file(row):
    p = Path(row['path']).resolve()
    require(p.is_file() and sha(p) == row['sha256'], 'Missing or changed bound file: ' + str(p))
    return p


def hex_spans(path):
    base = 0
    spans = []
    eof = False
    for line in Path(path).read_text().splitlines():
        require(line.startswith(':'), 'Invalid Intel HEX')
        b = bytes.fromhex(line[1:])
        require(len(b) >= 5 and len(b) == b[0] + 5 and sum(b) % 256 == 0, 'HEX checksum/length')
        n, addr, kind = b[0], int.from_bytes(b[1:3], 'big'), b[3]
        require(not eof, 'HEX data after EOF')
        if kind == 0 and n:
            spans.append((base + addr, base + addr + n))
        elif kind in (2, 4):
            require(n == 2, 'Invalid HEX extended address')
            base = int.from_bytes(b[4:6], 'big') << (4 if kind == 2 else 16)
        elif kind == 1:
            require(n == 0, 'Invalid HEX EOF')
            eof = True
        elif kind not in (0, 3, 5):
            raise RuntimeError('Unsupported HEX record')
    require(eof and spans, 'Incomplete/empty HEX')
    return spans


def validate_manifest(cfg, facts):
    # Reuse the established AEL source/object/toolchain validator. Bench targets
    # retain BENCH_ONLY scope; this does not change their classification.
    from ael.adapters import prism_lane as lane
    p = Path(cfg['deployment_manifest']).resolve()
    m = json.loads(p.read_text())
    require(m.get('schema') == 'prism.bench-trial.v1', 'Wrong bench manifest schema')
    target = m.get('target')
    require(target in TARGETS and target == cfg['target'], 'Unsupported/mismatched bench target')
    kind, identity, backend = TARGETS[target]
    require(kind == cfg['lane'] and m.get('identity') == identity, 'Wrong UID/serial/MAC')
    source = Path(cfg['source']).resolve()
    require(lane.git(source, 'rev-parse', 'HEAD') == m['source_commit'], 'Candidate source commit mismatch')
    require(not lane.git(source, 'status', '--porcelain', '--untracked-files=no'), 'Dirty candidate source')
    lock = json.loads((source / 'deps/prism-core.lock.json').read_text())
    source_facts = {'root': str(source), 'commit': m['source_commit'],
                    'tracked_files': lane.git(source, 'ls-files').splitlines(),
                    'core_commit': lock['commit'], 'core_tag': lock['tag']}
    facts['source'] = source_facts
    build = bound_file(m['build_receipt'])
    record = json.loads(build.read_text())
    expected_binding = record.get('source_binding_hash') if kind == 'dualmcu' else record.get('source_profile_sha256')
    require(m.get('source_binding_hash') == expected_binding and expected_binding, 'Runtime source binding mismatch')
    lane.validate_product_receipt(record, build.parent, source, kind, facts, bench_trial=True)
    if target == 'titan-replacement':
        from ael.titan_replacement_observer import validate_profile
        validate_profile(m, record)
    image = bound_file(m['image'])
    relative = image.relative_to(build.parent).as_posix()
    require(record['artefacts'].get(relative) == m['image']['sha256'], 'Image absent from successful build binding')
    if backend == 's3':
        require(relative.endswith('/' + target + '/' + target + '/firmware.bin'), 'Image/target mismatch')
        require(m['offset'] == 0x10000, 'Only app0 app-only write supported')
        end = m['offset'] + image.stat().st_size
        erase_end = (end + 4095) & ~4095
        require(m['permitted_range'] == [0x10000, 0x650000] and erase_end <= 0x650000,
                'Write/erase escapes app0; protected boot/data range')
    else:
        expected = 'titan-native.hex' if backend == 'titan' else 'build/' + target + '/' + target + '/firmware.hex'
        require(relative == expected, 'Image/target mismatch')
        lo, hi = m['permitted_range']
        expected_range = [0x02000000, 0x02C9F020] if backend == 'titan' else [0x60000000, 0x601F0000]
        require([lo, hi] == expected_range, 'Unapproved programming range')
        require(all(lo <= a < b <= hi for a, b in hex_spans(image)), 'HEX outside permitted range')
    facts.update(deployment_manifest=str(p), deployment_manifest_sha256=sha(p),
                 target=target, identity=identity, image=str(image), image_sha256=sha(image),
                 classification='DEVELOPMENT_BENCH_TRIAL; no full-product admission')
    return m, source, image, backend


# Scope-locked recovery admitted by Captain's 8 October takeover: these are
# independently read actual bytes/receipts, not a candidate supplied as backup.
TITAN_RECOVERY_UID = '545433931bd25436593630352d068363'
TITAN_RECOVERY_HEX_SHA256 = 'df7a33785ac2a12b01e5065722ba9ce8bb758802e1bbd0d78e4bfc92007dd776'
TITAN_RECOVERY_DERIVATION_SHA256 = 'e1222369db2558dadfba215b1cde3a4756a230dcd3b995042e2c5130f1f2eb7e'
TITAN_RECOVERY_RECEIPT_SHA256 = 'ac4801e2666fe6fb03f47c438bcb32213d0cd978e4059b35da59589eee59294b'
TITAN_RECOVERY_BUILD = 'becb0186f0a66fbb04b0e0f4a79c0480b8b963db0fe3f518a91af9bb2dd2b5c7'



TITAN_CURRENT_RECOVERY_SOURCE_HEX_SHA256 = 'e28ccf18733a077c0cce86c723e2c073934d06e78d961004cdfb2b72a9aeb3e8'
TITAN_CURRENT_RECOVERY_HEX_SHA256 = 'ed2322e2fe376dfcd0ab28069bc9f86261138b83d4f5ab525ce87751268717d2'
TITAN_CURRENT_RECOVERY_DERIVATION_SHA256 = '922ac1d56343b99f29f673e65604e3126990007ccf665d4f0c31b9ebc6cadc41'
TITAN_CURRENT_RECOVERY_BUILD = 'a43e4842b3a7cf8b5150787f613b575551dc090d80779dae6474784de59cd606'
TITAN_CURRENT_RECOVERY_SOURCE = '7f86939bd7c16c4a6dd5789813e9d551246ed134'
TITAN_CURRENT_RECOVERY_BUILD_RECEIPT_SHA256 = '8f150784b1cae1836f137b15ab1ba8eabdc7f8984dc77914c22acd552f271a75'
TITAN_CURRENT_RECOVERY_RECEIPT_SHA256 = 'b5e240419ef1820e5e8f5ff5635f87dbd137a2b3c1672e10016f8dbf044a0c16'

def recovery_hex_bytes(path):
    """Validate records and retain unique absolute-address bytes."""
    base = 0
    memory = {}
    rows = []
    eof = False
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        require(line.startswith(':'), 'Invalid HEX line')
        try:
            row = bytes.fromhex(line[1:])
        except ValueError as exc:
            raise RuntimeError('Invalid HEX encoding') from exc
        require(len(row) >= 5 and len(row) == row[0] + 5 and sum(row) % 256 == 0,
                'HEX checksum/length')
        require(not eof, 'HEX record after EOF')
        count, address, kind = row[0], int.from_bytes(row[1:3], 'big'), row[3]
        require(address + count <= 0x10000, 'HEX record crosses address page')
        if kind == 0:
            for i, byte in enumerate(row[4:4+count]):
                absolute = base + address + i
                require(absolute not in memory, 'HEX overlap')
                memory[absolute] = byte
            rows.append((line, kind, base + address, count))
        elif kind in (2, 4):
            require(count == 2 and address == 0, 'Invalid HEX extended address')
            base = int.from_bytes(row[4:6], 'big') << (4 if kind == 2 else 16)
            rows.append((line, kind, None, count))
        elif kind == 1:
            require(count == 0 and address == 0, 'Invalid HEX EOF')
            eof = True
            rows.append((line, kind, None, count))
        elif kind in (3, 5):
            require(count == 4 and address == 0, 'Invalid HEX start address')
            rows.append((line, kind, None, count))
        else:
            raise RuntimeError('Unsupported HEX record')
    require(eof and memory, 'Incomplete/empty HEX')
    return memory, rows


def recovery_merged_spans(memory):
    ranges = []
    for address in sorted(memory):
        if ranges and ranges[-1][1] == address:
            ranges[-1][1] += 1
        else:
            ranges.append([address, address + 1])
    return ranges


def require_titan_current_recovery(m, image):
    """Admit derived recovery through exact source-byte/verified-range equivalence."""
    import re
    require(m.get('identity') == TITAN_RECOVERY_UID, 'Recovery wrong Titan UID')
    recovery = m['recovery']
    require(sha(image) == TITAN_CURRENT_RECOVERY_HEX_SHA256, 'Wrong derived current donor')
    source = bound_file(recovery['source_image'])
    require(sha(source) == TITAN_CURRENT_RECOVERY_SOURCE_HEX_SHA256, 'Wrong original donor image')
    derivation_file = bound_file(recovery['derivation'])
    require(sha(derivation_file) == TITAN_CURRENT_RECOVERY_DERIVATION_SHA256,
            'Unknown current donor derivation')
    d = json.loads(derivation_file.read_text())
    require(d.get('schema') == 'titan.recovery.inrange/1' and
            d.get('source_sha256') == sha(source) and d.get('derived_sha256') == sha(image) and
            d.get('build_id') == TITAN_CURRENT_RECOVERY_BUILD and
            d.get('uid') == TITAN_RECOVERY_UID and d.get('source_pin') == TITAN_CURRENT_RECOVERY_SOURCE and
            isinstance(d.get('source_hex'), str) and bool(d['source_hex']) and
            isinstance(d.get('derived_hex'), str) and bool(d['derived_hex']) and
            d.get('range') == '02000000-02C9F01F' and d.get('in_range_bytes') == 534304 and
            d.get('dropped_records') == [':04F04000FFFFFFFFD0'] and
            d.get('derived_image_programmed') is False and d.get('hardware_access') is False,
            'Wrong derivation identity/provenance')
    original, records = recovery_hex_bytes(source)
    actual, _ = recovery_hex_bytes(image)
    inside = {a:v for a,v in original.items() if 0x02000000 <= a < 0x02C9F020}
    outside = {a:v for a,v in original.items() if a not in inside}
    require(actual == inside and len(actual) == 534304 and
            recovery_merged_spans(actual) == [[0x02000000,0x02082720]],
            'Derived recovery must preserve every in-range byte')
    require(outside == {a:255 for a in range(0x02C9F040,0x02C9F044)} and
            [line for line,kind,a,n in records if kind == 0 and n and
             not (0x02000000 <= a and a+n <= 0x02C9F020)] == [':04F04000FFFFFFFFD0'],
            'Unexpected excluded source bytes')
    build_file = bound_file(recovery['build_receipt'])
    require(sha(build_file) == TITAN_CURRENT_RECOVERY_BUILD_RECEIPT_SHA256,
            'Unknown current donor build receipt')
    build = json.loads(build_file.read_text())
    require(build.get('pass') is True and build.get('label') == 'PRE-SILICON' and
            build.get('build_id') == TITAN_CURRENT_RECOVERY_BUILD and
            build.get('source_pin') == TITAN_CURRENT_RECOVERY_SOURCE and
            build.get('artifacts', {}).get('rtthread.hex') == sha(source),
            'Current donor build must bind original source image')
    receipt_file = bound_file(recovery['qualification_receipt'])
    require(sha(receipt_file) == TITAN_CURRENT_RECOVERY_RECEIPT_SHA256,
            'Unknown original source programming receipt')
    p = json.loads(receipt_file.read_text())
    require(p.get('label') == 'RFP-SWD' and p.get('pass') is True and p.get('execute') is True and
            p.get('dry_run') is False and type(p.get('returncode')) is int and p['returncode'] == 0,
            'Original ranged programming did not succeed')
    require(p.get('uid') == TITAN_RECOVERY_UID and p.get('build_id') == TITAN_CURRENT_RECOVERY_BUILD and
            p.get('source_pin') == TITAN_CURRENT_RECOVERY_SOURCE and p.get('hex_sha256') == sha(source),
            'Original programmed identity mismatch')
    require(p.get('probe') == 'e2l:5AS079228B' and p.get('interface') == 'swd' and
            p.get('speed_hz') == 1000000 and p.get('range') == '02000000,02c9f01f' and
            p.get('flags') == ['-noquery', '-run'] and p.get('debug_mode') == 'none',
            'Original programmer scope mismatch')
    argv = p.get('command', [])
    require(isinstance(argv, list) and len(argv) == 15 and Path(argv[0]).name == 'rfp-cli' and
            argv[1:-1] == ['-d','RA','-t','e2l:5AS079228B','-if','swd','-s','1000000',
                          '-noquery','-run','-range','02000000,02c9f01f','-pv'],
            'Original actual command mismatch')
    text = p.get('stdout', '')
    require(text.startswith('Renesas Flash Programmer CLI V1.17\n') and
            'Load: "'+argv[-1]+'"' in text and 'Emulator power supply: OFF' in text and
            'Connected to R7KA8P1KFLCAC' in text and 'Tool: E2 emulator Lite (5AS079228B)' in text and
            text.count('Writing data to the target device') == 1 and
            text.count('Verifying data on the target device') == 1 and
            text.rstrip().endswith('Operation successful') and
            not re.search(r'\b(error|failed|failure)\b',text,re.I),
            'Original programmer evidence mismatch')
    verified = [[int(a,16),int(b,16)+1] for a,b in re.findall(
        r'\[Code MRAM [12]\]\s+([0-9A-F]{8}) - ([0-9A-F]{8})',
        text.split('Verifying data on the target device',1)[1])]
    require(verified == [[0x02000000,0x02082720]] and
            all(any(a <= lo < hi <= b for a,b in verified) for lo,hi in hex_spans(image)),
            'Historical verified ranges do not cover derived recovery')
    require(d.get('historical_source_programming_receipt_sha256') == sha(receipt_file) and
            d.get('historical_verified_ranges') == verified and
            d.get('derived_spans') == recovery_merged_spans(actual),
            'Derivation historical coverage provenance mismatch')
    return {'image_sha256':sha(image),'source_image_sha256':sha(source),
            'derivation_sha256':sha(derivation_file),'build_receipt_sha256':sha(build_file),
            'execution_receipt_sha256':sha(receipt_file),'build_source_sha256':TITAN_CURRENT_RECOVERY_BUILD,
            'historical_source_verified_ranges':verified,'recovery_byte_equivalence_verified':True,
            'derived_image_programmed':False,
            'scope':'derived current donor recovery admission via original ranged-byte equivalence; no new device proof'}

TITAN_HOST009_RECOVERY_SOURCE_HEX_SHA256 = 'c2e927d986ccac7f58f16d88e10cfb7837e45c2547e0c88a3eebf6b05ab039f3'
TITAN_HOST009_RECOVERY_HEX_SHA256 = '715156513a4ebcccdcd72c50c460378a37d7bd979b2478a10fb4f5d3aa86649b'
TITAN_HOST009_RECOVERY_DERIVATION_SHA256 = '3c436c9ef346c433b422e1a51b38c2f799a07457220913c9d6befb046a681e67'
TITAN_HOST009_RECOVERY_BUILD = 'fe4bf14a8a8e674f2962ad13e9b42b332da95208c2c4864b4ca9c92b6f4cfa9d'
TITAN_HOST009_RECOVERY_SOURCE = '7f86939bd7c16c4a6dd5789813e9d551246ed134'
TITAN_HOST009_RECOVERY_BUILD_RECEIPT_SHA256 = '5585fbfd9129d6c307851afb1ef6f2c052c72a90dc5aebcac5c5246f10e90441'
TITAN_HOST009_RECOVERY_RECEIPT_SHA256 = 'ad150a1dc29d5b924a972d5fe16756e87a1e77a928105d1fa023f6e6bdb3aa49'

def require_titan_host009_recovery(m, image):
    """Admit derived recovery through exact source-byte/verified-range equivalence."""
    import re
    require(m.get('identity') == TITAN_RECOVERY_UID, 'Recovery wrong Titan UID')
    recovery = m['recovery']
    require(sha(image) == TITAN_HOST009_RECOVERY_HEX_SHA256, 'Wrong derived current donor')
    source = bound_file(recovery['source_image'])
    require(sha(source) == TITAN_HOST009_RECOVERY_SOURCE_HEX_SHA256, 'Wrong original donor image')
    derivation_file = bound_file(recovery['derivation'])
    require(sha(derivation_file) == TITAN_HOST009_RECOVERY_DERIVATION_SHA256,
            'Unknown current donor derivation')
    d = json.loads(derivation_file.read_text())
    require(d.get('schema') == 'titan.recovery.inrange/1' and
            d.get('source_sha256') == sha(source) and d.get('derived_sha256') == sha(image) and
            d.get('build_id') == TITAN_HOST009_RECOVERY_BUILD and
            d.get('uid') == TITAN_RECOVERY_UID and d.get('source_pin') == TITAN_HOST009_RECOVERY_SOURCE and
            isinstance(d.get('source_hex'), str) and bool(d['source_hex']) and
            isinstance(d.get('derived_hex'), str) and bool(d['derived_hex']) and
            d.get('range') == '02000000-02C9F01F' and d.get('in_range_bytes') == 648792 and
            d.get('dropped_records') == [':04F04000FFFFFFFFD0'] and
            d.get('derived_image_programmed') is False and d.get('hardware_access') is False,
            'Wrong derivation identity/provenance')
    original, records = recovery_hex_bytes(source)
    actual, _ = recovery_hex_bytes(image)
    inside = {a:v for a,v in original.items() if 0x02000000 <= a < 0x02C9F020}
    outside = {a:v for a,v in original.items() if a not in inside}
    require(actual == inside and len(actual) == 648792 and
            recovery_merged_spans(actual) == [[0x02000000,0x0209e658]],
            'Derived recovery must preserve every in-range byte')
    require(outside == {a:255 for a in range(0x02C9F040,0x02C9F044)} and
            [line for line,kind,a,n in records if kind == 0 and n and
             not (0x02000000 <= a and a+n <= 0x02C9F020)] == [':04F04000FFFFFFFFD0'],
            'Unexpected excluded source bytes')
    build_file = bound_file(recovery['build_receipt'])
    require(sha(build_file) == TITAN_HOST009_RECOVERY_BUILD_RECEIPT_SHA256,
            'Unknown current donor build receipt')
    build = json.loads(build_file.read_text())
    require(build.get('pass') is True and build.get('label') == 'PRE-SILICON' and
            build.get('build_id') == TITAN_HOST009_RECOVERY_BUILD and
            build.get('source_pin') == TITAN_HOST009_RECOVERY_SOURCE and
            build.get('artifacts', {}).get('rtthread.hex') == sha(source),
            'Current donor build must bind original source image')
    receipt_file = bound_file(recovery['qualification_receipt'])
    require(sha(receipt_file) == TITAN_HOST009_RECOVERY_RECEIPT_SHA256,
            'Unknown original source programming receipt')
    p = json.loads(receipt_file.read_text())
    require(p.get('label') == 'RFP-SWD' and p.get('pass') is True and p.get('execute') is True and
            p.get('dry_run') is False and type(p.get('returncode')) is int and p['returncode'] == 0,
            'Original ranged programming did not succeed')
    require(p.get('uid') == TITAN_RECOVERY_UID and p.get('build_id') == TITAN_HOST009_RECOVERY_BUILD and
            p.get('source_pin') == TITAN_HOST009_RECOVERY_SOURCE and p.get('hex_sha256') == sha(source),
            'Original programmed identity mismatch')
    require(p.get('probe') == 'e2l:5AS079228B' and p.get('interface') == 'swd' and
            p.get('speed_hz') == 1000000 and p.get('range') == '02000000,02c9f01f' and
            p.get('flags') == ['-noquery', '-run'] and p.get('debug_mode') == 'none',
            'Original programmer scope mismatch')
    argv = p.get('command', [])
    require(isinstance(argv, list) and len(argv) == 15 and Path(argv[0]).name == 'rfp-cli' and
            argv[1:-1] == ['-d','RA','-t','e2l:5AS079228B','-if','swd','-s','1000000',
                          '-noquery','-run','-range','02000000,02c9f01f','-pv'],
            'Original actual command mismatch')
    text = p.get('stdout', '')
    require(text.startswith('Renesas Flash Programmer CLI V1.17\n') and
            'Load: "'+argv[-1]+'"' in text and 'Emulator power supply: OFF' in text and
            'Connected to R7KA8P1KFLCAC' in text and 'Tool: E2 emulator Lite (5AS079228B)' in text and
            text.count('Writing data to the target device') == 1 and
            text.count('Verifying data on the target device') == 1 and
            text.rstrip().endswith('Operation successful') and
            not re.search(r'\b(error|failed|failure)\b',text,re.I),
            'Original programmer evidence mismatch')
    verified = [[int(a,16),int(b,16)+1] for a,b in re.findall(
        r'\[Code MRAM [12]\]\s+([0-9A-F]{8}) - ([0-9A-F]{8})',
        text.split('Verifying data on the target device',1)[1])]
    require(verified == [[0x02000000,0x0209e660]] and
            all(any(a <= lo < hi <= b for a,b in verified) for lo,hi in hex_spans(image)),
            'Historical verified ranges do not cover derived recovery')
    require(d.get('historical_source_programming_receipt_sha256') == sha(receipt_file) and
            d.get('historical_verified_ranges') == verified and
            d.get('derived_spans') == recovery_merged_spans(actual),
            'Derivation historical coverage provenance mismatch')
    return {'image_sha256':sha(image),'source_image_sha256':sha(source),
            'derivation_sha256':sha(derivation_file),'build_receipt_sha256':sha(build_file),
            'execution_receipt_sha256':sha(receipt_file),'build_source_sha256':TITAN_HOST009_RECOVERY_BUILD,
            'historical_source_verified_ranges':verified,'recovery_byte_equivalence_verified':True,
            'derived_image_programmed':False,
            'scope':'derived current donor recovery admission via original ranged-byte equivalence; no new device proof'}

# Exact installed June19 show for normal broker-present return only. This is
# deliberately separate from the gateway's absent-USB recovery allowlist.
TITAN_INSTALLED_SHOW_RECOVERY = {
    'build': 'aadd38b2f452393a3105b3307c345487cc54b8f7dabd6dc1cacbdf5ab2fd2030',
    'image': '5d8c45d9c358506e7e19de89f33eaf23cba549035f206e26f765f0bef15d8d3d',
    'elf': '1aeb20e7af4b39074f3ac82b6e3a12a7c742823c28e240071d26d25ca0fe6d7e',
    'source': '7f86939bd7c16c4a6dd5789813e9d551246ed134',
    'schema': 'e99c1ec147288a7beaed728fc91e42530efc91c26f223164e03d07745b68c2da',
    'admission': 'd49f29cab4b225d0963bcc3f7feda2fc2e0a77929383eb0c5685bdbbfdb0ca36',
    'build_receipt': 'b937b5b69b5842b69fbbf5a31391240f0a52a7d2c84925740399deb05fa79f3b',
    'qualification_receipt': '3e0394c5c54495f05c5d270e38d2fe834c58d29601fd4376053b41ad48a55996',
}


def require_titan_installed_show_recovery(m, image):
    """Validate the exact already-programmed show; never grant absent-USB recovery."""
    import re
    pins = TITAN_INSTALLED_SHOW_RECOVERY
    recovery = m['recovery']
    require(m.get('identity') == TITAN_RECOVERY_UID and sha(image) == pins['image'],
            'Installed show recovery target/image mismatch')
    build_file = bound_file(recovery['build_receipt'])
    receipt_file = bound_file(recovery['qualification_receipt'])
    deployment = recovery['deployment']
    build_dir = Path(deployment['build_dir']).resolve()
    admission_file = Path(deployment['admission']).resolve()
    require(build_file == build_dir / 'receipt.json' and image.resolve() == build_dir / 'rtthread.hex',
            'Installed show recovery deployment differs from bound build/image')
    for key, path in [('build_receipt', build_file), ('qualification_receipt', receipt_file), ('admission', admission_file)]:
        require(sha(path) == pins[key], 'Installed show recovery changed ' + key)
    helper = Path('/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts/deploy_admission.py')
    spec = importlib.util.spec_from_file_location('deploy_admission', helper)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    build = json.loads(build_file.read_text())
    binding = checker.legacy_binding(build_dir, build)
    expected = (pins['build'], pins['image'], pins['elf'], pins['source'], pins['schema'])
    require(tuple(binding[k] for k in ('build_id','hex_sha256','elf_sha256','source','schema')) == expected
            and checker.CURRENT_SHOW_RECOVERY == expected, 'Installed show differs from normal gateway return binding')
    checker.check_admission(json.loads(admission_file.read_text()), binding)
    data, _ = recovery_hex_bytes(image)
    inside = {a:v for a,v in data.items() if 0x02000000 <= a < 0x02C9F020}
    outside = {a:v for a,v in data.items() if a not in inside}
    spans = recovery_merged_spans(inside)
    require(spans == [[0x02000000, 0x020A6300]] and len(inside) == 680704
            and outside == {a:255 for a in range(0x02C9F040,0x02C9F044)},
            'Installed show bytes differ from verified programming range')
    receipt = json.loads(receipt_file.read_text())
    require(receipt.get('pass') is True and receipt.get('execute') is True and receipt.get('dry_run') is False
            and type(receipt.get('returncode')) is int and receipt['returncode'] == 0,
            'Installed show programming did not succeed')
    require(receipt.get('uid') == TITAN_RECOVERY_UID and receipt.get('build_id') == pins['build']
            and receipt.get('source_pin') == pins['source'] and receipt.get('hex_sha256') == pins['image']
            and receipt.get('elf_sha256') == pins['elf'], 'Installed show programming identity mismatch')
    command = receipt.get('command', [])
    require(isinstance(command,list) and len(command) == 15 and Path(command[0]).name == 'rfp-cli'
            and command[1:-1] == ['-d','RA','-t','e2l:5AS079228B','-if','swd','-s','1000000',
                                  '-noquery','-run','-range','02000000,02c9f01f','-pv']
            and receipt.get('probe') == 'e2l:5AS079228B' and receipt.get('interface') == 'swd'
            and receipt.get('speed_hz') == 1000000 and receipt.get('range') == '02000000,02c9f01f'
            and receipt.get('flags') == ['-noquery','-run'] and receipt.get('debug_mode') == 'none',
            'Installed show programming scope mismatch')
    text = receipt.get('stdout','')
    require(text.startswith('Renesas Flash Programmer CLI V1.17\n') and 'Load: "'+command[-1]+'"' in text
            and 'Emulator power supply: OFF' in text and 'Connected to R7KA8P1KFLCAC' in text
            and 'Tool: E2 emulator Lite (5AS079228B)' in text
            and text.count('Writing data to the target device') == 1
            and text.count('Verifying data on the target device') == 1
            and text.rstrip().endswith('Operation successful') and not re.search(r'\b(error|failed|failure)\b',text,re.I),
            'Installed show programming evidence mismatch')
    verified = [[int(a,16),int(b,16)+1] for a,b in re.findall(
        r'\[Code MRAM [12]\]\s+([0-9A-F]{8}) - ([0-9A-F]{8})',text.split('Verifying data on the target device',1)[1])]
    require(verified == spans, 'Installed show verified ranges mismatch')
    return {'image_sha256':pins['image'], 'build_source_sha256':pins['build'],
            'build_receipt_sha256':sha(build_file), 'execution_receipt_sha256':sha(receipt_file),
            'admission_sha256':sha(admission_file), 'programmed_spans':spans,
            'scope':'exact installed show normal return; absent-USB recovery not admitted'}


def recovery_programmed_spans(m, image):
    """Only this exact normal return excludes the writer's out-of-range FF record."""
    if sha(image) == TITAN_INSTALLED_SHOW_RECOVERY['image']:
        return require_titan_installed_show_recovery(m, image)['programmed_spans']
    return hex_spans(image)


def require_titan_recovery(m):
    recovery = m.get('recovery', {})
    require(m.get('identity') == TITAN_RECOVERY_UID, 'Recovery wrong Titan UID')
    image = bound_file(recovery['image'])
    if sha(image) == TITAN_INSTALLED_SHOW_RECOVERY['image']:
        return require_titan_installed_show_recovery(m, image)
    if sha(image) == TITAN_HOST009_RECOVERY_HEX_SHA256:
        return require_titan_host009_recovery(m, image)
    if sha(image) == TITAN_CURRENT_RECOVERY_HEX_SHA256:
        return require_titan_current_recovery(m, image)
    require(sha(image) == TITAN_RECOVERY_HEX_SHA256, 'Recovery must be exact known donor; candidate cannot bypass output HOLD')
    derivation_file = bound_file(recovery['derivation'])
    require(sha(derivation_file) == TITAN_RECOVERY_DERIVATION_SHA256, 'Unknown donor recovery derivation')
    derivation = json.loads(derivation_file.read_text())
    require(derivation.get('schema') == 'titan.recovery.inrange/1' and
            derivation.get('derived_sha256') == TITAN_RECOVERY_HEX_SHA256 and
            derivation.get('build_id') == TITAN_RECOVERY_BUILD, 'Wrong donor derivation identity')
    receipt_file = bound_file(recovery['qualification_receipt'])
    require(sha(receipt_file) == TITAN_RECOVERY_RECEIPT_SHA256, 'Unknown donor recovery execution receipt')
    receipt = json.loads(receipt_file.read_text())
    require(receipt.get('ok') is True, 'Donor recovery receipt was not successful')
    facts = [item.get('facts', {}) for step in receipt.get('steps', [])
             for item in step.get('result', {}).get('evidence', [])]
    require(any(f.get('identity') == TITAN_RECOVERY_UID and
                f.get('invoked_image_sha256') == TITAN_RECOVERY_HEX_SHA256 and
                f.get('programmed') is True and f.get('tool_exit_verified') is True for f in facts),
            'Receipt does not bind actual successful donor programming')
    return {'image_sha256': sha(image), 'derivation_sha256': sha(derivation_file),
            'execution_receipt_sha256': sha(receipt_file), 'build_source_sha256': TITAN_RECOVERY_BUILD,
            'scope': 'known donor recovery only; no native candidate output qualification'}


def authorise(m, backend, *, write):
    required = ['exclusive_owner', 'identity_verified', 'serial_open_reset_accounted']
    if write:
        required += ['replacement_authorised', 'recovery_verified']
        if backend == 'teensy': required += ['settings_loss_accepted', 'exclusive_loader_target']
        if backend == 's3': required += ['retained_bootloader_compatible', 'security_compatible', 'peer_isolation']
        if backend == 'titan': required += ['continuity_window', 'settings_backup_verified', 'probe_power_off', 'run_on_return']
    a = m.get('authority', {})
    missing = [k for k in required if a.get(k) is not True]
    require(not missing, 'Held prerequisites: ' + ', '.join(missing))
    preflight = bound_file(m['preflight'])
    observed = json.loads(preflight.read_text())
    age = time.time() - observed['observed_unix']
    require(0 <= age <= 120, 'Stale preflight; re-identify immediately before use')
    require(observed.get('identity') == m['identity'] and observed.get('target') == m['target'], 'Preflight wrong UID/serial')
    require(observed.get('owner_clear') is True and observed.get('method') and observed.get('raw_evidence'), 'Missing identity/owner witness')
    require(sha(bound_file(observed['raw_evidence'])) == observed['raw_evidence']['sha256'], 'Identity witness changed')
    if backend == 'teensy':
        require(observed.get('loader_targets') == ['20731830'], 'Teensy loader cannot select an ambiguous target')
    if write:
        bound_file(m['recovery']['image'])
        require(m['recovery'].get('restore_method') and m['recovery'].get('provenance'), 'Missing scoped recovery recipe/provenance')
    require(observed.get('port') == m.get('port'), 'Preflight interface mismatch')
    return observed


OUTPUT_PROOF_METHODS = ('pin-loopback', 'logic-capture', 'dummy-load-bench')


def require_output_qualification(m):
    """Titan native images may drive the owner's LED strip only after their output
    path completed frames off-product (8 Oct 2026: three host-qualified native images
    stuck dark, then drove half and then the whole strip full white). The proof must be
    for this exact image hash and both lanes; the owner's strip is never the detector."""
    row = m.get('output_qualification')
    require(isinstance(row, dict), 'Titan native flash requires output_qualification (off-product LED proof)')
    proof = json.loads(bound_file(row).read_text())
    if proof.get('schema') == 'prism.titan.output-qualification.v2':
        from ael.titan_capture import consume_output_proof
        return consume_output_proof(m, proof)
    require(proof.get('schema') == 'prism.titan.output-qualification.v1', 'Wrong output qualification schema')
    require(proof.get('image_sha256') == m['image']['sha256'], 'Output proof is for a different image')
    require(proof.get('off_product') is True, 'Output proof must not use the owner strip as detector')
    require(proof.get('method') in OUTPUT_PROOF_METHODS, 'Unsupported output proof method')
    require(sorted(proof.get('lanes_verified') or []) == ['A', 'B'], 'Both LED lanes must be verified')
    frames = proof.get('frames_completed')
    require(isinstance(frames, int) and frames >= 100, 'Output proof needs at least 100 completed frames')
    require(proof.get('stuck_high_detected') is False, 'Output proof records a held-high data line')
    bound_file(proof['raw_evidence'])
    # v1 assertions plus a raw-file hash cannot establish complete waveform,
    # resident-image, per-lane timing or terminal-low acquisition. None of these
    # methods has an implemented independent acquisition verifier in AEL.
    # Keep the real output HOLD rather than admitting paperwork as device proof.
    require(False, 'OUTPUT_QUALIFICATION_UNAVAILABLE: no supported independent off-product acquisition verifier; native flash HOLD')


def rfp_backend(m):
    require(m['rfp_backend']['path'] == str(RFP_BACKEND), 'Unsupported RFP backend')
    bound_file(m['rfp_backend'])
    spec = importlib.util.spec_from_file_location('prism_existing_rfp', RFP_BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.require_uid(m['identity'])
    module.require_region('02000000', '02c9f01f')
    module.require_execution_flags(1000000, True, [])
    return module


def programmer_argv(m, image, backend, *, recover=False):
    if backend == 'titan':
        # Native receipt was validated by AEL above. Reuse the backend's sealed
        # range/UID/flags and argv builder directly, without donor metadata.
        return rfp_backend(m).build_argv(image, '02000000', '02c9f01f')
    if backend == 'teensy':
        # No global soft reboot, no auto reboot of unidentified Teensys. The
        # fresh preflight must establish the sole identified loader target.
        return [TEENSY, '--mcu=imxrt1062', '-v', str(image)]
    port = m['port']
    require(port.startswith('/dev/cu.') and '*' not in port, 'Explicit resolved interface required')
    if recover:
        require(m['recovery'].get('offset') == 0x10000 and m['recovery'].get('end_exclusive', 0) <= 0x650000,
                'Only covered app-slot recovery is allowed; no full-flash restore')
        require(image.stat().st_size + 0x10000 <= 0x650000, 'Recovery escapes permitted app0')
    return [PYTHON, '-m', 'esptool', '--chip', 'esp32s3', '--port', port,
            '--port-filter', 'serial=' + m['identity'], '--before', 'default_reset', '--after', 'hard_reset',
            'write_flash', '--flash_size', 'keep', '0x10000', str(image)]


DEPLOY_SCRIPT = Path('/Users/spectrasynq/.claude/skills/smc-titan-mixer/scripts/deploy_titan_image.sh')


def deployment_argv(m, image, name, programme_dir, *, restore_settings=None):
    """Return the guarded deploy command for a Titan candidate or recovery write.

    This does not call the sealed writer. Absent-USB recovery stays inside the
    gateway and is not requested from here, so an unpinned image cannot be
    forced through --recover-known-image.
    """
    selected = m['recovery']['deployment'] if name == 'donor-recovery' else m['deployment']
    build = Path(selected['build_dir']).resolve()
    admission = Path(selected['admission']).resolve()
    programme_dir = Path(programme_dir)
    require(build.is_dir() and (build / 'receipt.json').is_file(), 'deployment build receipt missing')
    require(admission.is_file(), 'deployment admission missing')
    require(not programme_dir.exists(), 'programme directory must not exist yet')
    require(Path(image).is_file(), 'programming image missing')
    helper = Path('/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts/deploy_admission.py')
    spec = importlib.util.spec_from_file_location('deploy_admission', helper)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    try:
        checker.image_matches_build(build, Path(image).resolve(), admission)
    except checker.Refusal as exc:
        raise RuntimeError(str(exc)) from exc
    argv = ['/bin/bash', str(DEPLOY_SCRIPT), str(build), str(admission), str(programme_dir)]
    checkpoint = m.get('isolated_qualification', {}).get('repair_checkpoint')
    if checkpoint is not None and name == 'candidate':
        require(m.get('target') == 'titan-replacement' and
                m.get('isolated_qualification', {}).get('repair_session'),
                'Retained candidate update requires the bound repair session')
        checkpoint_path = bound_file(checkpoint)
        argv += ['--repair-checkpoint', str(checkpoint_path),
                 '--repair-checkpoint-sha', checkpoint['sha256']]
    if restore_settings is None and name == 'donor-recovery':
        restore_settings = selected.get('restore_settings')
    if restore_settings is not None:
        settings_path = Path(restore_settings['path']).resolve()
        require(settings_path.is_file() and sha(settings_path) == restore_settings['sha256'], 'original settings capture changed or missing')
        argv += ['--restore-settings', str(settings_path), '--restore-settings-sha', restore_settings['sha256']]
    require(Path(argv[1]).name == 'deploy_titan_image.sh' , 'Titan write left the guarded gateway')
    require(not any(part.endswith('rfp-cli') or part.endswith('programme_rfp_swd.py') for part in argv),
            'Titan write leg invoked the sealed writer directly')
    return argv


def require_gateway_broker_owner(port, socket_path):
    """Verify one existing broker owns both endpoints; no stop or takeover."""
    def owners(path):
        got = subprocess.run(['lsof', '-t', path], capture_output=True, text=True, check=False, timeout=3)
        require(got.returncode == 0 and not got.stderr.strip(), 'Expected broker endpoint owner unavailable')
        values = set(got.stdout.split())
        require(len(values) == 1 and next(iter(values)).isdigit(), 'Expected exactly one broker owner')
        return next(iter(values))
    pid = owners(port)
    require(owners(socket_path) == pid, 'Serial and control socket have different owners')
    command = subprocess.run(['ps', '-p', pid, '-o', 'command='], capture_output=True, text=True, check=False, timeout=3)
    expected = '/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001/tools/serial-studio/titan_broker.py'
    require(command.returncode == 0 and not command.stderr.strip() and expected in command.stdout.split(),
            'Endpoint owner is not the existing Titan broker')
    return {'pid': int(pid), 'socket': socket_path, 'serial': port}


def execute(cfg, ctx, facts):
    m, source, image, backend = validate_manifest(cfg, facts)
    action = cfg['action']
    if action == 'bench-trial-plan':
        facts.update(hardware_access=False, programmed=False, authority=m.get('authority', {}),
                     prerequisites='Fresh identity/sole-owner and scoped recovery/decisions required; this plan is offline')
        facts['programmer_argv'] = None if backend == 's3' and not m.get('port') else programmer_argv(m, image, backend)
        if facts['programmer_argv'] is None: facts['interface_gate'] = 'Explicit freshly resolved S3 port required; no guessed argv'
        return
    # A malformed trace/media/scene request must fail before ownership checks,
    # serial opening or starting this session's audio player.
    if cfg.get('native_request'):
        operation = json.loads(Path(cfg['native_request']).read_text())
        require('isolated_capture' not in operation, 'Raw capture can run only through the isolated gateway transaction')
        if 'retained_witness' in operation:
            from ael.prism_native import prepare_retained_witness
            require(action == 'bench-trial-control' and backend == 'titan' and set(operation) == {'retained_witness'},
                    'Retained witness requires an exclusive Titan control operation')
            prepare_retained_witness(operation['retained_witness'])
        if 'disconnect_check' in operation:
            from ael.prism_disconnect import prepare
            require(action == 'bench-trial-control' and backend == 'titan' and set(operation) == {'disconnect_check'},
                    'Disconnect check requires an exclusive Titan control operation')
            prepare(operation['disconnect_check'])
        if 'completion' in operation:
            from ael.prism_completion import prepare
            require(action == 'bench-trial-control' and backend == 'titan', 'Completion requires explicit Titan control operation')
            require(not operation.get('save') and 'evaluation_drive' not in operation and 'fields' not in operation,
                    'Completion is session-only and mutually exclusive with drive/control PATCH')
            prepare(operation['completion'])
        if 'evaluation_drive' in operation:
            from ael.prism_drive import prepare_request, validate_scene_fields
            require(action == 'bench-trial-control' and backend == 'titan', 'Drive replay requires explicit Titan control operation')
            require(not operation.get('save'), 'Experimental drive is never saved')
            prepared = prepare_request(operation['evaluation_drive'])
            validate_scene_fields(operation.get('fields', {}), prepared)
    if action == 'bench-trial-qualify-isolated':
        require(backend == 'titan', 'Isolated waveform operation is Titan-only')
        from ael.titan_capture import isolated_preflight
        # Physical records and scoped bootstrap admission precede any owner or
        # programmer access. Ordinary deployment never shares this exception.
        facts['isolated_preflight'] = isolated_preflight(m)
    write = action in ('bench-trial-flash', 'bench-trial-recover', 'bench-trial-qualify-isolated')
    if backend == 'titan' and action == 'bench-trial-flash':
        facts['output_qualification'] = require_output_qualification(m)
    if backend == 'titan' and write:
        facts['known_donor_recovery'] = require_titan_recovery(m)
    observed = authorise(m, backend, write=write)
    lockpath = Path(__file__).resolve().parents[2] / '_scratch/prism-hardware.lock'
    lockpath.parent.mkdir(exist_ok=True)
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if backend == 'titan' and write:
            require(isinstance(m.get('port'), str) and m['port'].startswith('/dev/cu.') and '*' not in m['port'], 'Explicit interface required')
            facts['gateway_broker_owner'] = require_gateway_broker_owner(m['port'], m.get('broker_socket', '/tmp/titan-emotiscope-control/titan-control.sock'))
        elif backend != 'teensy' or not write:
            require(isinstance(m.get('port'), str) and m['port'].startswith('/dev/cu.') and '*' not in m['port'], 'Explicit interface required')
            owner = subprocess.run(['lsof', '-t', m['port']], capture_output=True, text=True, check=False, timeout=3)
            require(owner.returncode == 1 and not owner.stdout.strip() and not owner.stderr.strip(),
                    'Interface owner exists or ownership check failed')
        if action == 'bench-trial-control':
            require(backend == 'titan' and m.get('authority', {}).get('native_control_authorised') is True and cfg.get('native_request'), 'Explicit Titan native control authority/request required')
        if action == 'bench-trial-qualify-isolated':
            from ael.titan_isolated import execute as execute_isolated
            execute_isolated(m, source, image, ctx, facts)
            return
        if write:
            if backend == 'titan':
                require(os.environ.get('K1_RFP_SWD_EXECUTE_OK') == '1', 'Existing RFP root-owner execution gate K1_RFP_SWD_EXECUTE_OK=1 required')
            if action == 'bench-trial-recover':
                image = bound_file(m['recovery']['image'])
                lo, hi = m['permitted_range']
                if backend != 's3':
                    spans = recovery_programmed_spans(m, image) if backend == 'titan' else hex_spans(image)
                    require(all(lo <= a < b <= hi for a, b in spans), 'Recovery HEX range')
            if backend == 'titan':
                role = 'donor-recovery' if action.endswith('recover') else 'candidate'
                argv = deployment_argv(m, image, role, ctx.logs_dir / (role + '-programme'))
            else:
                argv = programmer_argv(m, image, backend, recover=action.endswith('recover'))
            # Invocation receipt is durable before any consequential action.
            facts.update(argv=argv, invoked_image_sha256=sha(image), hardware_access=True, programmed=False)
            (ctx.logs_dir / 'native-invocation.json').write_text(json.dumps(facts, indent=2))
            with (ctx.logs_dir / 'programmer.log').open('w') as log:
                result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=False)
            facts.update(returncode=result.returncode, tool_exit_verified=result.returncode == 0,
                         runtime_boot_verified=False)
            require(result.returncode == 0, 'Programmer failed; no automatic retry')
            facts['programmed'] = True
        elif backend == 'titan':
            from ael.prism_native import run_session
            if cfg.get('native_request'): facts['native_request_sha256'] = sha(cfg['native_request'])
            facts['native_session'] = run_session(m, ctx.logs_dir, cfg['seconds'], cfg.get('native_request'))
        else:
            require(action == 'bench-trial-observe', 'Dual controls remain real BLE-MIDI; no diagnostic control injection')
            binding = bound_file(m['diagnostic_binding'])
            script = source / 'scripts/collect_readiness.py'
            argv = [PYTHON, str(script), '--port', m['port'], '--binding', str(binding),
                    '--target', m['target'], '--source', m['source_binding_hash'], '--device', m['identity'],
                    '--seconds', str(cfg['seconds']), '--frames', '--acknowledge-open-may-reset',
                    '--output', str(ctx.run_dir / 'collector')]
            facts['argv'] = argv
            with (ctx.logs_dir / 'collector.log').open('w') as log:
                result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=cfg['seconds'] + 30)
            require(result.returncode == 0, 'Dual collector failed')
