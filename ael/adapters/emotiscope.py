"""Emotiscope bench integration. Host-only; no generated firmware or pin writes.

Uses the product's guarded PlatformIO deployment and authoritative frame decoder.
AEL supplies sequencing, failure propagation and evidence, not optical proof.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

from ael import evidence
from ael.adapters.observe_uart_log import _evaluate_capture, _default_patterns

USB_SERIAL = 'DC:54:75:EA:36:14'
ENV = 'k1_emotiscope_live'
CONTROLS = ('palette', 'position', 'brightness', 'saturation', 'mirror', 'speed', 'contrast')
MODES = {'live': 0, 'waveform_tempo': 18, 'waveform_hybrid': 11, 'waveform_hybrid_k1': 32}
UART_ERROR = re.compile('|'.join(_default_patterns('espidf')['errors']) + r'|\[E\]', re.IGNORECASE)
FATAL = re.compile(r'Guru Meditation|abort\(\)|assert failed|Brownout|Task watchdog|TWDT|KLV boot=fail|KLV fault=|LoadProhibited|StoreProhibited|IllegalInstruction')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()


def source_identity(source):
    source = Path(source).resolve()
    lane = (source / 'bench/emotiscope/platformio.ini').is_file()
    if lane:
        require((source / 'scripts/flash.py').is_file(), 'Missing lane flash guard')
        require(not git(source, 'status', '--porcelain'), 'Uncommitted lane inputs')
        profile = source / 'bench/emotiscope/platformio.ini'
    else:
        require((source / 'scripts/agent/k1-flash-verified.sh').is_file(), 'Missing product flash guard')
        guard = (source / 'scripts/agent/k1-flash-verified.sh').read_text()
        require('K1-S3' not in guard, 'Legacy Emotiscope owner retired; use PRISM/K1-S3')
        require(not git(source, 'status', '--porcelain', '--', 'SPECTRASYNQ_K1_FIRMWARE', 'platformio.ini'), 'Uncommitted firmware/configuration')
        profile = source / 'platformio.ini'
    return {'root': str(source), 'git': git(source, 'rev-parse', 'HEAD'),
            'branch': git(source, 'branch', '--show-current'), 'lane': lane,
            'platformio_sha256': sha(profile)}


def materialized_source(source):
    if not (Path(source) / 'bench/emotiscope/platformio.ini').is_file():
        return Path(source)
    out = subprocess.check_output([sys.executable, 'scripts/bench.py', 'prepare'], cwd=source, text=True, timeout=120)
    paths = re.findall(r'^K1-S3 BENCH (.+)$', out, re.MULTILINE)
    require(len(paths) == 1, 'Missing materialised lane source')
    return Path(paths[0])


def expected_firmware(cfg, identity):
    ref = cfg.get('expected_git')
    if not ref and identity['lane']:
        ref = json.loads((Path(cfg['source']) / 'docs/deployments/current.json').read_text())['firmware_commit']
    ref = git(cfg['source'], 'rev-parse', (ref or identity['git']) + '^{commit}')
    # Documentation-only HEAD changes do not change retained runtime inputs.
    paths = ['bench', 'deps', 'scripts', 'boards'] if identity['lane'] else ['SPECTRASYNQ_K1_FIRMWARE', 'platformio.ini']
    require(not git(cfg['source'], 'diff', ref, identity['git'], '--', *paths), 'Expected firmware differs from current build inputs')
    return ref


def identified_port(port, ports=None):
    if ports is None:
        from serial.tools import list_ports
        ports = list_ports.comports()
    requested = port.replace('/dev/tty.', '/dev/cu.')
    matches = [p for p in ports if p.device.replace('/dev/tty.', '/dev/cu.') == requested]
    require(len(matches) == 1, 'Requested USB port missing or ambiguous')
    p = matches[0]
    require((p.vid, p.pid, (p.serial_number or '').upper()) == (0x303A, 0x1001, USB_SERIAL), 'Wrong Emotiscope USB identity')
    return requested


@contextmanager
def ownership(port):
    # Canonical USB identity makes tty/cu aliases share one interprocess lock.
    base = Path.home() / '.cache/ael/locks'
    base.mkdir(parents=True, exist_ok=True)
    with (base / 'emotiscope-DC5475EA3614.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Emotiscope already owned by another AEL process') from exc
        try:
            aliases = [port.replace('/dev/tty.', '/dev/cu.'), port.replace('/dev/cu.', '/dev/tty.')]
            proc = subprocess.run(['lsof', '-t', *aliases], capture_output=True, text=True, timeout=5)
            require(proc.returncode in (0, 1) and not proc.stdout.strip() and not proc.stderr.strip(),
                    'Serial port owned or ownership check failed: ' + proc.stdout + proc.stderr)
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Link:
    def __init__(self, port, raw):
        import serial
        self.ser = serial.Serial(port=None, baudrate=115200, timeout=.03, write_timeout=1)
        self.ser.port = port
        self.ser.dtr, self.ser.rts = True, False
        self.raw = raw
        self.pending = b''
        self.commands = []
        self.allow_boot = False

    def __enter__(self):
        self.ser.open()
        return self

    def __exit__(self, *args):
        self.ser.close()

    def read(self, seconds):
        end = time.monotonic() + seconds
        lines = []
        while time.monotonic() < end:
            data = self.ser.read(min(self.ser.in_waiting or 1, 8192))
            self.raw.write(data)
            self.raw.flush()
            self.pending += data
            require(len(self.pending) < 65536, 'Unterminated serial data exceeds limit')
            while b'\n' in self.pending:
                line, self.pending = self.pending.split(b'\n', 1)
                line = line.decode('utf8', 'replace').strip()
                lines.append(line)
                require(not FATAL.search(line), 'Runtime fault: ' + line)
                require(self.allow_boot or 'ESP-ROM:' not in line, 'Unexpected reset: ' + line)
                require(self.allow_boot or not UART_ERROR.search(line), 'Unexpected UART error: ' + line)
        return lines

    def command(self, value, seconds=.45):
        self.ser.write((':' + value + '\n').encode('ascii'))
        self.ser.flush()
        lines = self.read(seconds)
        self.commands.append({'command': value, 'reply': lines})
        return lines

    def expect(self, value, reply):
        lines = self.command(value)
        if reply not in lines and value.startswith('klv_mode=') and not any(x.startswith('KLV err=') for x in lines):
            # Never resend a mutation after a missing ACK: reconcile its state.
            for _ in range(3):
                observed = self.command('klv_render_status', .8)
                if reply in observed:
                    return
        require(reply in lines, f'{value}: missing {reply!r}; replies={lines}')


def runtime(link, expected_git, saved):
    lines = link.command('build')
    builds = [re.search(r'BUILD: version=(\d+) git=([0-9a-f]+) epoch=(\d+) env=(\S+)', x) for x in lines]
    builds = [m for m in builds if m]
    require(len(builds) == 1, 'Missing/ambiguous BUILD response')
    build = builds[0]
    require(build[4] == ENV and len(build[2]) >= 7 and expected_git.startswith(build[2]), 'Firmware source identity mismatch')
    lines = link.command('klv_status')
    text = '\n'.join(lines)
    image = re.search(r'KLV image bytes=(\d+) crc=([0-9a-f]{8})', text)
    vm = re.search(r'KLV vm=up origin=(\w+) saved=1 err=0 px=128 frames=(\d+)', text)
    heap = re.search(r'KLV heap free=(\d+) big=(\d+)', text)
    mode = re.search(r'KLV renderer=\w+ mode=(\d+)', text)
    require(image and vm and heap and mode, 'Incomplete/failed application status: ' + text)
    require((int(image[1]), image[2]) == (saved['bytes'], saved['crc']), 'Saved program changed')
    return {'build': build[0], 'saved': {'bytes': int(image[1]), 'crc': image[2]},
            'frames': int(vm[2]), 'mode': int(mode[1]), 'heap_free': int(heap[1]), 'heap_largest': int(heap[2])}


def metrics(lines):
    fps, vu, frames, audio = [], [], [], []
    for line in lines:
        m = re.search(r'^KLV us=\d+ fps=(\d+) err=(\d+) vu=([\d.]+)', line)
        if m:
            require(int(m[2]) == 0, 'VM error in telemetry')
            fps.append(int(m[1])); vu.append(float(m[3]))
        m = re.search(r'^KLVT .*frm=(\d+)/(\d+)', line)
        if m: frames.append([int(m[1]), int(m[2])])
        m = re.search(r'^KLVA .*act=(\d+)/(\d+)', line)
        if m: audio.append([int(m[1]), int(m[2])])
    require(len(fps) >= 5 and frames and audio, 'Insufficient timing telemetry')
    return {'samples': len(fps), 'fps_median': statistics.median(fps), 'fps_min': min(fps),
            'vu_max': max(vu), 'frame_avg_us_median': statistics.median(x[0] for x in frames),
            'frame_max_us': max(x[1] for x in frames), 'audio_active_avg_us_median': statistics.median(x[0] for x in audio),
            'audio_active_max_us': max(x[1] for x in audio)}


def decoder(source):
    # Import the product's existing CRC/order/length oracle, do not fork it.
    sys.path.insert(0, str(Path(source) / 'tools/k1live'))
    return importlib.import_module('prove_waveform_extension').decode_frame


def native_status(link):
    """Retry incomplete read-only snapshots; never retry a reported fault."""
    attempts = []
    for _ in range(3):
        lines = link.command('klv_render_status', .8)
        attempts.append(lines)
        counters = [re.fullmatch(r'KLV native frames=(\d+) avg=(\d+) max=(\d+) invalid=(\d+)', x) for x in lines]
        counters = [m for m in counters if m]
        if counters:
            require(int(counters[0][4]) == 0, 'Native invalid audio inputs')
        if counters and any(re.fullmatch(r'KLV native ap=\d+ pcm=96 history=1', x) for x in lines):
            return {'snapshot': lines, 'attempts': attempts}
    raise RuntimeError('Incomplete native status after three read-only queries')


def boot_diagnostics(lines, port, raw_path):
    text = '\n'.join(lines)
    result = _evaluate_capture(text, text.encode(), port, 115200, str(raw_path),
                               'espidf', ['KLV boot=saved'], [], ['ESP-ROM:'])
    require(result['matched']['boot']['count'] == 1, 'Expected exactly one ROM boot')
    require(not result['missing_expect'] and not result['download_mode_detected'] and not result['crash_detected'],
            'Boot failed readiness/crash checks')
    # Retain the upstream FAIL and its errors. Only these diagnosed startup probes
    # and the optional show-state absence are known; every other error fails.
    arduino_errors = [line for line in lines if re.search(r'\[E\]', line)]
    known = (
        r'E \(\d+\) quad_psram: PSRAM ID read error: 0x00ffffff, PSRAM chip not found or not supported, or wrong PSRAM line mode',
        r'\[\s*\d+\]\[E\]\[esp32-hal-psram\.c:\d+\] psramAddToHeap\(\): PSRAM not initialized!',
        r'\[\s*\d+\]\[E\]\[vfs_api\.cpp:\d+\] open\(\): /littlefs/SHOW_STATE_V1\.BIN does not exist, no permits for creation',
    )
    error_lines = sorted(set([e['line'] for e in result['errors']] + arduino_errors))
    unknown = [line for line in error_lines if not any(re.fullmatch(p, line) for p in known)]
    require(not unknown, 'Uncharacterised boot errors: ' + str(unknown))
    result['arduino_error_lines'] = arduino_errors
    result['known_boot_diagnostics'] = error_lines
    result['known_absent_psram_probe_errors'] = sum('PSRAM' in line for line in error_lines)
    return result


def read_control(link, key):
    for _ in range(3):
        lines = link.command('klv_get=' + key)
        matches = [re.fullmatch(r'KLV value=' + key + r' n=(-?\d+)', x) for x in lines]
        values = [int(m[1]) for m in matches if m]
        if len(values) == 1:
            return values[0]
    raise RuntimeError('Missing control readback: ' + key)


def controls(link):
    return {key: read_control(link, key) for key in CONTROLS}


def set_control(link, key, value):
    lines = link.command(f'klv_set={key},{value}')
    if f'KLV value={key} n={value}' in lines:
        return
    require(not any(x.startswith('KLV err=') for x in lines), 'Control rejected: ' + str(lines))
    # A missing acknowledgement is ambiguous, not permission to repeat a write.
    require(read_control(link, key) == value, 'Control postcondition mismatch: ' + key)


def restore(link, original, mode):
    # Contrast is hybrid-only; speed/position require native mode.
    link.expect('klv_mode=waveform_hybrid', 'KLV mode=waveform_hybrid id=11')
    for key in CONTROLS:
        set_control(link, key, original[key])
    name = next(k for k, v in MODES.items() if v == mode)
    link.expect('klv_mode=' + name, f'KLV mode={name} id={mode}')
    require(controls(link) == original, 'Control restoration readback mismatch')


def hardware(cfg, ctx, facts):
    source = cfg['source']; expected = expected_firmware(cfg, facts['source']); saved = cfg['saved']
    facts['expected_firmware'] = expected
    port = identified_port(cfg['port'])
    raw_path = ctx.logs_dir / 'emotiscope.raw.log'
    original = None
    with ownership(port), raw_path.open('wb') as raw, Link(port, raw) as link:
        link.read(1)
        before = runtime(link, expected, saved)
        facts['before'] = before
        original = controls(link)
        facts['original_controls'] = original
        try:
            require(before['mode'] in MODES.values(), 'Unknown renderer mode; cannot guarantee restoration')
            # Capture baseline in the same Live state used for the after measurement.
            link.expect('klv_mode=live', 'KLV mode=live id=0')
            link.read(2)
            facts['baseline_metrics'] = metrics(link.read(cfg['seconds']))
            if cfg['action'] == 'observe':
                return
            require(cfg.get('real_music_confirmed') is True, 'Physical audio test requires confirmed real music')
            stage = materialized_source(source)
            decode = decoder(stage)
            facts['decoder_sha256'] = sha(stage / 'tools/k1live/prove_waveform_extension.py')
            facts['modes'] = {}
            set_control(link, 'brightness', min(original['brightness'], 600))
            for name, mid in list(MODES.items())[1:]:
                link.expect('klv_mode=' + name, f'KLV mode={name} id={mid}')
                set_control(link, 'position', 0); set_control(link, 'mirror', 1)
                snapshots = []
                for palette in (37, 38):
                    set_control(link, 'palette', palette)
                    link.read(2)
                    frame = decode(link.command('klv_frame', 1))
                    require(frame['mode'] == mid and frame['sum'] > 0 and frame['symmetric'], f'{name}: invalid/dark/asymmetric frame')
                    snapshots.append(frame)
                require(snapshots[0]['crc'] != snapshots[1]['crc'], name + ': palette/output unchanged')
                status = native_status(link)
                facts['modes'][name] = {'frames': snapshots, 'status': status}
                print('Emotiscope: physical mode passed:', name, flush=True)
            for value in (14, 17, 25, 32, 42):
                link.expect(f'klv_set=palette,{value}', 'KLV err=value')
            require(controls(link)['palette'] == 38, 'Rejected palette changed state')
            set_control(link, 'saturation', 0)
            frame = decode(link.command('klv_frame', 1))
            require(frame['sum'] > 0 and all(p[0] == p[1] == p[2] for p in frame['pixels']), 'Desaturation failed')
            facts['desaturation_frame'] = frame
            set_control(link, 'saturation', 1000)
            set_control(link, 'brightness', 0)
            require(decode(link.command('klv_frame', 1))['sum'] == 0, 'Brightness zero failed')
            set_control(link, 'brightness', min(original['brightness'], 600))
            link.read(1)
            require(decode(link.command('klv_frame', 1))['sum'] > 0, 'Brightness restoration failed')
            link.expect('klv_set=contrast,1500', 'KLV err=hybrid_required')
            link.expect('klv_mode=live', 'KLV mode=live id=0')
            link.expect('klv_set=speed,1000', 'KLV err=native_required')
            facts['controls_passed'] = True
            facts['boots'] = []
            for index in range(cfg['resets']):
                link.allow_boot = True
                boot_lines = link.command('reset', 10)
                link.allow_boot = False
                boot = runtime(link, expected, saved)
                require(boot['mode'] == 0, 'Reset did not resume saved Live program')
                boot['uart_evaluation'] = boot_diagnostics(boot_lines, port, raw_path)
                facts['boots'].append(boot)
                print('Emotiscope: saved application returned after reset', index + 1, flush=True)
            restore(link, original, 0)
            link.read(2)
            before_soak = runtime(link, expected, saved)
            facts['after_metrics'] = metrics(link.read(cfg['seconds']))
            after = runtime(link, expected, saved)
            facts['after'] = after
            require(after['frames'] > before_soak['frames'], 'Live renderer stopped')
            require(after['heap_free'] >= before_soak['heap_free'] - 256, 'Heap decline during soak')
            require(after['heap_largest'] >= before_soak['heap_largest'] - 256, 'Heap fragmentation during soak')
            require(facts['after_metrics']['vu_max'] > 0, 'No measured microphone activity during music')
            require(facts['after_metrics']['fps_median'] >= .9 * facts['baseline_metrics']['fps_median'], 'Cadence regression greater than 10%')
            facts['soak_before'] = before_soak
        finally:
            try:
                if original is not None:
                    restore(link, original, before['mode'])
                    facts['restored'] = runtime(link, expected, saved)
            finally:
                facts['commands'] = link.commands
                facts['raw_log'] = str(raw_path)
                facts['raw_sha256'] = sha(raw_path)
    facts['raw_sha256'] = sha(raw_path)


class EmotiscopeAdapter:
    def execute(self, step, plan, ctx):
        cfg = dict(step['inputs'])
        facts = {'action': cfg['action'], 'usb_serial': USB_SERIAL, 'psram_bytes': 0,
                 'qualification': 'target telemetry and post-current-limit LED buffers; not optical/electrical waveform certification'}
        ok, error = False, ''
        try:
            require(cfg.get('usb_serial') == USB_SERIAL and cfg.get('environment') == ENV, 'Pack target identity mismatch')
            facts['source'] = source_identity(cfg['source'])
            action = cfg['action']
            if action in ('build', 'flash'):
                if facts['source']['lane']:
                    cmd = [sys.executable, 'scripts/bench.py', 'build'] if action == 'build' else [sys.executable, 'scripts/flash.py']
                    if action == 'flash': identified_port(cfg['port'])
                    env = dict(os.environ)
                    env.pop('PLATFORMIO_BUILD_DIR', None)
                else:
                    cmd = (['pio', 'run', '-e', ENV] if action == 'build' else
                           ['bash', 'scripts/agent/k1-flash-verified.sh', ENV, '--port', identified_port(cfg['port'])])
                    env = dict(os.environ, PLATFORMIO_BUILD_DIR=str(Path(cfg['build_dir']).resolve()))
                log = ctx.logs_dir / (action + '.log')
                def execute():
                    with log.open('w') as out:
                        return subprocess.run(cmd, cwd=cfg['source'], env=env, stdout=out, stderr=subprocess.STDOUT, timeout=1200)
                if action == 'flash':
                    with ownership(cfg['port']):
                        proc = execute()
                else:
                    proc = execute()
                facts.update(argv=cmd, returncode=proc.returncode, log=str(log), log_sha256=sha(log))
                require(proc.returncode == 0, action + ' failed; inspect ' + str(log))
                require(source_identity(cfg['source']) == facts['source'], 'Source changed during build/flash')
                binary = ((materialized_source(cfg['source']) / '.pio/build') if facts['source']['lane'] else Path(cfg['build_dir'])) / ENV / 'firmware.bin'
                facts['binary'] = {'path': str(binary), 'bytes': binary.stat().st_size, 'sha256': sha(binary)}
            elif action in ('observe', 'test'):
                hardware(cfg, ctx, facts)
                require(source_identity(cfg['source']) == facts['source'], 'Source changed during hardware test')
            else:
                raise ValueError('Unknown Emotiscope action')
            ok = True
        except Exception as exc:
            error = str(exc)
        finally:
            raw = ctx.logs_dir / 'emotiscope.raw.log'
            if raw.exists(): facts.update(raw_log=str(raw), raw_sha256=sha(raw))
            path = evidence.write_evidence(ctx.run_dir, 'emotiscope-' + cfg['action'] + '.json', {'ok': ok, 'error': error, 'facts': facts})
        item = evidence.make_item(kind='emotiscope.' + cfg['action'], source='ael.adapters.emotiscope',
                                  ok=ok, summary=error or 'Completed declared checks', facts=facts, artifacts={'result': path})
        return {'ok': ok, 'retryable': False, 'error_summary': error, 'evidence': [item]}
