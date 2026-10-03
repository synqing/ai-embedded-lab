"""PRISM lane inspection and native-owner observation through AEL evidence.

Scaffold host checks are never promoted to firmware or device qualification.
Titan observations read the existing sole USB owner's atomic publication.
"""
import fcntl
import hashlib
import json
import os
import plistlib
from pathlib import Path
import shutil
import shlex
import signal
import subprocess
import sys
import time

from ael import evidence
from ael.adapters.emotiscope import git, require, sha

TITAN_UID = '545433931bd25436593630352d068363'
LANES = {'dualmcu': 'K1-DualMCU', 'titan': 'Kx-Titan'}
DUAL_TARGETS = ('rt1062_production', 'rt1062_k1_migration_t40_ws2812_128', 's3_radio_bridge_ble')
TITAN_FLAGS = ['--optimisation', 'o2', '--dcache', 'disabled', '--pdm-target', '--palette-runtime',
               '--palette-autostart', '--palette-morph', '--palette-ws2816-gpt-pair',
               '--dmac-priority', 'fixed', '--dmac-lane-map', 'led-first', '--emotiscope-port',
               '--tempo-field', '--live-runtime', '--live-emit', '--live-defaults',
               'docs/contracts/titan-emotiscope-spectrum-defaults-v1.json']


def donor_identity(source):
    source = Path(source)
    diff = subprocess.check_output(['git', 'diff', 'HEAD', '--binary'], cwd=source)
    paths = set(git(source, 'ls-files').splitlines())
    # PlatformIO and the Titan builder can consume local, even ignored headers.
    # Include source/configuration roots while excluding generated evidence.
    roots = {'firmware', 'core', 'include', 'contract', 'contracts', 'bridge', 'src', 'platform',
             'scripts', 'harness', 'configs', 'boards', 'deps', 'tests', 'test', 'lib'}
    for p in git(source, 'ls-files', '--others').splitlines():
        if len(Path(p).parts) == 1 or Path(p).parts[0] in roots or p.startswith('docs/contracts/'):
            if Path(p).suffix in ('.h', '.hpp', '.c', '.cpp', '.cc', '.S', '.inc', '.ini', '.py', '.json', '.ld', '.yaml'):
                paths.add(p)
    return {'root': str(source.resolve()), 'commit': git(source, 'rev-parse', 'HEAD'),
            'diff_sha256': hashlib.sha256(diff).hexdigest(),
            'inputs': {p: sha(source / p) for p in sorted(paths) if (source / p).is_file()}}


def run_command(argv, *, cwd, stdout, timeout, env=None):
    """A timeout ends the entire build process group, including compiler children."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: pass
        # The launcher may have exited while a compiler ignored SIGTERM.
        # Kill the remaining group even when the leader has already exited.
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.wait(timeout=5)
        raise
    return proc


def donor_build(cfg, ctx, facts):
    source = Path(cfg['donor_source']).resolve()
    identity = donor_identity(source)
    facts['donor_source'] = identity
    stage = ctx.run_dir.resolve() / 'build'
    require(not stage.exists(), 'Fresh build output required')
    env = dict(os.environ)
    if cfg['lane'] == 'dualmcu':
        target = cfg['target']
        require(target in DUAL_TARGETS, 'Unsupported DualMCU target')
        require('[env:' + target + ']' in (source / 'platformio.ini').read_text(), 'Donor target missing')
        cmd = [sys.executable, '-m', 'platformio', 'run', '-e', target]
        env.update(PLATFORMIO_BUILD_DIR=str(stage), PLATFORMIO_WORKSPACE_DIR=str(stage.parent / 'pio-workspace'),
                   PLATFORMIO_LIBDEPS_DIR=str(stage.parent / 'pio-libdeps'))
    else:
        require((source / 'platform/ra8p1').is_dir() and (source / 'docs/contracts/titan-emotiscope-v1.json').exists(), 'Titan Emotiscope donor source missing')
        cmd = [sys.executable, '-B', 'scripts/build_scalar.py', '--output', str(stage)] + TITAN_FLAGS
    log = ctx.logs_dir / 'donor-build.log'
    facts.update(argv=cmd, cwd=str(source))
    with log.open('w') as out:
        proc = run_command(cmd, cwd=source, env=env, stdout=out, timeout=1200)
    facts.update(returncode=proc.returncode, log=str(log), log_sha256=sha(log))
    require(proc.returncode == 0, 'Donor build failed; ' + str(log))
    require(donor_identity(source) == identity, 'Donor source changed during build')
    artifacts = [p for p in stage.rglob('*') if p.suffix in ('.elf', '.hex', '.bin') and p.is_file()]
    require(artifacts, 'Build emitted no firmware')
    facts['binaries'] = [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in artifacts]
    facts['qualification'] = 'Fresh donor compilation; not PRISM lane firmware or hardware qualification'


def source_facts(source, lane):
    source = Path(source).resolve()
    require(lane in LANES and source.name == LANES[lane], 'Lane/source mismatch')
    require(not git(source, 'status', '--porcelain', '--untracked-files=no'), 'Tracked lane changes require reconciliation')
    lock = json.loads((source / 'deps/prism-core.lock.json').read_text())
    require(lock['status'] == 'pinned', 'Core is not pinned')
    files = git(source, 'ls-files').splitlines()
    native = [p for p in files if not p.startswith('deps/') and
              (Path(p).suffix in ('.cpp', '.c', '.ino') or Path(p).name in ('platformio.ini', 'CMakeLists.txt', 'SConstruct'))]
    return {'root': str(source), 'commit': git(source, 'rev-parse', 'HEAD'),
            'tracked_files': files, 'native_build_or_source': native,
            'state': 'SCAFFOLD' if not native else 'REQUIRES_NATIVE_PROFILE',
            'core_commit': lock['commit'], 'core_tag': lock['tag'],
            'lock_sha256': sha(source / 'deps/prism-core.lock.json')}


def validate_titan(row, expected_build, now):
    identity = row['identity']
    require(identity.get('identified') is True and identity.get('uid') == TITAN_UID, 'Titan UID unidentified/mismatched')
    require(identity.get('build') == expected_build, 'Titan build mismatch')
    require(identity.get('runtime_kind') == 'live' and identity.get('contract') == 'sr12800.hop64.bins64.emotiscope', 'Wrong Titan execution path')
    require(row.get('quiesced') is False, 'Titan owner is quiesced')
    for key in ('identity', 'pdm', 'palette'):
        age = now - row['topic_mono'][key]
        require(0 <= age <= 5, 'Stale Titan ' + key)
    require(0 <= now - row['host_mono'] <= 2, 'Stale Titan owner')
    pdm, led = row['pdm'], row['palette']
    require(pdm.get('running') is True and pdm.get('rate_locked') == 1, 'Titan audio not running/locked')
    require(led.get('emit_enabled') is True and led.get('renderer') == 'emotiscope_v1.1', 'Titan show not running')
    require(led.get('host_pixel_stream_required') is False, 'Titan requires host pixels')
    require(led.get('din_a') == 'P601' and led.get('din_b') == 'P604' and led.get('pixels_per_din') == 80, 'Titan output mapping mismatch')
    require(led['pair_fault'] == 0 and led['emit_errors'] == 0, 'Titan LED fault')
    require(len(pdm['lanes']) == 2, 'Titan microphone lanes missing')
    for lane in pdm['lanes']:
        require(lane['error_flags'] == 0 and lane['overflow_events'] == 0 and lane['drop_events'] == 0, 'Titan capture fault')
    return row


def titan_progress(rows):
    require(len(rows) >= 3, 'Insufficient Titan observations')
    first, last = rows[0], rows[-1]
    for row in rows:
        require(row['pid'] == first['pid'] and row['serial_opens'] == first['serial_opens'] and
                row['epoch'] == first['epoch'] and row['identity'] == first['identity'], 'Titan identity/owner changed during observation')
        for key in ('stream_epoch', 'rearm_denied', 'asrc_starved', 'pair_skew_drops', 'push_rejected', 'stale_discards'):
            require(row['pdm'][key] == first['pdm'][key], 'Titan audio fault increased: ' + key)
        for a, b in zip(first['pdm']['lanes'], row['pdm']['lanes']):
            require(a['recovery_count'] == b['recovery_count'], 'Titan capture recovered during observation')
    require(last['pdm']['ap_hops'] > first['pdm']['ap_hops'], 'Titan audio counter frozen')
    require(last['palette']['completed_generation'] > first['palette']['completed_generation'], 'Titan LED counter frozen')
    require(len({r['palette']['pair_frame_crc'] for r in rows}) > 1, 'Titan LED content frozen')
    require(max(r['pdm']['last_hop_peak'] for r in rows) > 0, 'Titan microphone has no activity')
    elapsed = last['host_mono'] - first['host_mono']
    require(elapsed > 0, 'Titan observation clock did not advance')
    palette_elapsed = last['topic_mono']['palette'] - first['topic_mono']['palette']
    audio_elapsed = last['topic_mono']['pdm'] - first['topic_mono']['pdm']
    require(palette_elapsed > 0 and audio_elapsed > 0, 'Device topic timestamps did not advance')
    return {'seconds': elapsed, 'audio_hops_delta': last['pdm']['ap_hops'] - first['pdm']['ap_hops'],
            'completed_frames_delta': last['palette']['completed_generation'] - first['palette']['completed_generation'],
            'completed_frames_per_second': (last['palette']['completed_generation'] - first['palette']['completed_generation']) / palette_elapsed,
            'audio_hops_per_second': (last['pdm']['ap_hops'] - first['pdm']['ap_hops']) / audio_elapsed,
            'palette_topic_seconds': palette_elapsed, 'audio_topic_seconds': audio_elapsed,
            'mic_peak_max': max(r['pdm']['last_hop_peak'] for r in rows),
            'brightness_observed': sorted({r['palette']['brightness'] for r in rows}),
            'qualification': 'Live M85 audio and LED completion telemetry; not wire/optical proof; not PRISM firmware',
            'historical_audio_rearms': first['pdm']['rearm_denied']}


def titan_build_binding(cfg):
    donor = Path(cfg['donor_source']).resolve()
    receipt = Path(cfg['build_receipt']).resolve()
    build = json.loads(receipt.read_text())
    require(build.get('pass') is True and build.get('emotiscope_port', {}).get('enabled') is True, 'No successful Emotiscope port build receipt')
    require(build.get('sources'), 'Build source manifest missing')
    for rel, digest in build['sources'].items():
        path = donor / rel
        if rel == 'external/live_defaults.json':
            path = Path(build['live_defaults'])
            if not path.is_absolute(): path = donor / path
        require(sha(path) == digest, 'Titan build source drift: ' + rel)
    for name in ('rtthread.hex', 'rtthread.elf'):
        require(sha(receipt.parent / name) == build['artifacts'][name], 'Titan build artifact drift: ' + name)
    return build


def require_titan_owner(command, donor, owner):
    args = shlex.split(command)
    expected = Path(donor).resolve() / 'tools/serial-studio/titan_broker.py'
    scripts = [Path(a).resolve() for a in args if a.endswith('.py') or '.py.' in a]
    require(scripts == [expected] and args.count('--evidence') == 1 and
            args.index('--evidence') + 1 < len(args) and
            Path(args[args.index('--evidence') + 1]).resolve() == Path(owner).resolve() and
            '--continuous-output' in args, 'Wrong Titan serial owner')


def require_titan_binding(identity, build):
    require(identity.get('identified') is True and identity.get('uid') == TITAN_UID and
            identity.get('build') == build['build_id'] and identity.get('source') == build['source_pin'] and
            identity.get('schema_sha256') == build['live_schema']['sha256'], 'Titan source/schema/identity mismatch')


def observe_titan(cfg, ctx, facts):
    from serial.tools import list_ports
    ports = [p for p in list_ports.comports() if (p.vid, p.pid, p.serial_number) == (0x045b, 0x5310, '0000000000001')]
    require(len(ports) == 1, 'Exactly one Titan CDC device required; Emotiscope S3 cannot substitute')
    facts['usb'] = {'port': ports[0].device, 'vid': ports[0].vid, 'pid': ports[0].pid, 'serial': ports[0].serial_number}
    owner = Path(cfg['owner_dir']).resolve()
    donor = Path(cfg['donor_source']).resolve()
    receipt = Path(cfg['build_receipt']).resolve()
    build = titan_build_binding(cfg)
    facts.update(build_receipt=str(receipt), build_receipt_sha256=sha(receipt), build_id=build['build_id'],
                 donor_commit=git(donor, 'rev-parse', 'HEAD'), sources_checked=len(build['sources']))
    rows = []
    raw = ctx.logs_dir / 'titan-owner.jsonl'
    end = time.monotonic() + cfg['seconds']
    with raw.open('w') as out:
        while time.monotonic() < end:
            row = json.loads((owner / 'live-stats.json').read_text())
            out.write(json.dumps(row) + '\n'); out.flush()
            if not rows:
                cmd = subprocess.check_output(['ps', '-p', str(row['pid']), '-o', 'command='], text=True, timeout=3).strip()
                require_titan_owner(cmd, donor, owner)
                facts['owner_command'] = cmd
            validate_titan(row, build['build_id'], time.monotonic())
            require_titan_binding(row['identity'], build)
            rows.append(row)
            time.sleep(1)
    facts['measurements'] = titan_progress(rows)
    require(titan_build_binding(cfg) == build, 'Titan build binding changed during observation')
    facts.update(raw_log=str(raw), raw_sha256=sha(raw), samples=len(rows))


def recover_titan_owner(cfg, ctx, facts):
    """Restart the existing host owner once; never reset or programme silicon."""
    require(cfg['lane'] == 'titan', 'No DualMCU recovery without both identified devices')
    owner = Path(cfg['owner_dir']).resolve()
    donor = Path(cfg['donor_source']).resolve()
    before = json.loads((owner / 'live-stats.json').read_text())
    build = titan_build_binding(cfg)
    require_titan_binding(before['identity'], build)
    label = 'com.spectrasynq.titan-broker'
    service = 'gui/' + str(os.getuid()) + '/' + label
    plist_path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    with plist_path.open('rb') as f: plist = plistlib.load(f)
    require(plist['Label'] == label and Path(plist['WorkingDirectory']).resolve() == donor, 'Wrong owner service')
    require(Path(plist['EnvironmentVariables']['TITAN_BROKER_EVIDENCE']).resolve() == owner, 'Wrong owner evidence directory')
    service_info = subprocess.check_output(['launchctl', 'print', service], text=True, timeout=5)
    require(('pid = ' + str(before['pid']) + '\n') in service_info, 'Service does not own observed PID')
    cmd = subprocess.check_output(['ps', '-p', str(before['pid']), '-o', 'command='], text=True, timeout=3)
    require_titan_owner(cmd, donor, owner)
    facts['before'] = before
    cmd = ['launchctl', 'kickstart', '-k', service]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    facts.update(recovery_argv=cmd, recovery_returncode=proc.returncode, recovery_stderr=proc.stderr)
    require(proc.returncode == 0, 'Owner restart failed')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        after = json.loads((owner / 'live-stats.json').read_text())
        if after['pid'] != before['pid']:
            try:
                validate_titan(after, build['build_id'], time.monotonic())
                break
            except (KeyError, RuntimeError): pass
        time.sleep(.25)
    else: raise RuntimeError('Owner did not return with fresh identified telemetry')
    for key in ('brightness', 'mode_a', 'mode_b', 'palette_a', 'palette_b', 'emit_enabled'):
        require(before['palette'][key] == after['palette'][key], 'Recovery changed ' + key)
    require(after['palette']['completed_generation'] >= before['palette']['completed_generation'], 'Device restarted during host recovery')
    facts['after_restart'] = after
    observe_titan(cfg, ctx, facts)


class PrismLaneAdapter:
    def execute(self, step, plan, ctx):
        cfg = step['inputs']; facts = {}; ok = False; error = ''
        try:
            lane, action = cfg['lane'], cfg['action']
            facts['source'] = source_facts(cfg['source'], lane)
            source = Path(cfg['source']).resolve()
            if action in ('flash', 'build', 'recover'):
                raise RuntimeError('No native firmware/deployment profile in this PRISM scaffold; donor observation and core-test are separate capabilities')
            elif action == 'discover':
                from serial.tools import list_ports
                facts['ports'] = [{'port': p.device, 'vid': p.vid, 'pid': p.pid, 'serial': p.serial_number} for p in list_ports.comports()]
            elif action == 'core-test':
                core = Path(cfg['core_source']).resolve()
                log = ctx.logs_dir / 'core-test.log'
                commands = [[sys.executable, str(core / 'tools/prism_core_pin.py'), '--core', str(core), 'verify']]
                with log.open('w') as out:
                    proc = run_command(commands[0], cwd=source, stdout=out, timeout=60)
                    require(proc.returncode == 0, 'Core pin verification failed; ' + str(log))
                    # Host script installs Acorn. Run a copy; vendor remains byte-identical.
                    stage = ctx.run_dir.resolve() / 'core-stage'
                    shutil.copytree(source / 'deps/PRISM-Core', stage)
                    commands.append(['bash', 'live/test/run_host.sh'])
                    # Upstream v0.2.0 writes shared /tmp/k1live_cases. Serialise AEL runs.
                    lock = Path.home() / '.cache/ael/locks/prism-core.lock'
                    lock.parent.mkdir(parents=True, exist_ok=True)
                    with lock.open('a') as handle:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        proc = run_command(commands[1], cwd=stage, stdout=out, timeout=300)
                    facts.update(argv=commands, returncode=proc.returncode, log=str(log), log_sha256=sha(log))
                    require(proc.returncode == 0, 'Portable core host test failed; ' + str(log))
                facts['qualification'] = 'Fresh host C++ compilation and JS parity only; no native firmware exists'
            elif action == 'observe':
                require(lane == 'titan', 'DualMCU requires identified RT1062 plus S3 and wired SPI; single Emotiscope S3 is insufficient')
                observe_titan(cfg, ctx, facts)
            elif action == 'donor-build':
                donor_build(cfg, ctx, facts)
            elif action == 'donor-recover':
                recover_titan_owner(cfg, ctx, facts)
            else:
                raise ValueError('Unknown lane action')
            require(source_facts(source, lane) == facts['source'], 'Lane source changed during operation')
            ok = True
        except Exception as exc:
            error = str(exc)
        finally:
            raw = ctx.logs_dir / 'titan-owner.jsonl'
            if raw.exists(): facts.update(raw_log=str(raw), raw_sha256=sha(raw))
            path = evidence.write_evidence(ctx.run_dir, 'prism-lane.json', {'ok': ok, 'error': error, 'facts': facts})
        item = evidence.make_item(kind='prism.lane', source='ael.adapters.prism_lane', ok=ok,
                                  summary=error or 'Completed declared lane check', facts=facts, artifacts={'result': path})
        return {'ok': ok, 'retryable': False, 'error_summary': error, 'evidence': [item]}
