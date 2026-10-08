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


def require_titan_recovery(m):
    recovery = m.get('recovery', {})
    require(m.get('identity') == TITAN_RECOVERY_UID, 'Recovery wrong Titan UID')
    image = bound_file(recovery['image'])
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
        if 'evaluation_drive' in operation:
            from ael.prism_drive import prepare_request, validate_scene_fields
            require(action == 'bench-trial-control' and backend == 'titan', 'Drive replay requires explicit Titan control operation')
            require(not operation.get('save'), 'Experimental drive is never saved')
            prepared = prepare_request(operation['evaluation_drive'])
            validate_scene_fields(operation.get('fields', {}), prepared)
    write = action in ('bench-trial-flash', 'bench-trial-recover')
    if backend == 'titan' and action == 'bench-trial-flash':
        facts['output_qualification'] = require_output_qualification(m)
    if backend == 'titan' and write:
        facts['known_donor_recovery'] = require_titan_recovery(m)
    observed = authorise(m, backend, write=write)
    lockpath = Path(__file__).resolve().parents[2] / '_scratch/prism-hardware.lock'
    lockpath.parent.mkdir(exist_ok=True)
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if backend != 'teensy' or not write:
            require(isinstance(m.get('port'), str) and m['port'].startswith('/dev/cu.') and '*' not in m['port'], 'Explicit interface required')
            owner = subprocess.run(['lsof', '-t', m['port']], capture_output=True, text=True, check=False)
            require(owner.returncode == 1 and not owner.stdout.strip(), 'Interface owner exists or ownership check failed')
        if action == 'bench-trial-control':
            require(backend == 'titan' and m.get('authority', {}).get('native_control_authorised') is True and cfg.get('native_request'), 'Explicit Titan native control authority/request required')
        if write:
            if backend == 'titan':
                require(os.environ.get('K1_RFP_SWD_EXECUTE_OK') == '1', 'Existing RFP root-owner execution gate K1_RFP_SWD_EXECUTE_OK=1 required')
            if action == 'bench-trial-recover':
                image = bound_file(m['recovery']['image'])
                lo, hi = m['permitted_range']
                if backend != 's3': require(all(lo <= a < b <= hi for a, b in hex_spans(image)), 'Recovery HEX range')
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
