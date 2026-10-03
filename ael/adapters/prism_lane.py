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
import struct
import subprocess
import sys
import time

from ael import evidence
from ael.adapters.emotiscope import git, require, sha

TITAN_UID = '545433931bd25436593630352d068363'
LANES = {'dualmcu': 'K1-DualMCU', 'titan': 'Kx-Titan'}
# These are the current lane-owned product entry points, separate from donor targets.
# Architecture alone cannot identify which processor application an ELF replaces.
PRODUCT_TARGETS = {
    'dualmcu': {
        'rt1062': ('build/prism_rt1062/prism_rt1062/firmware.elf', 40, True),
        's3_radio': ('build/prism_s3_ble/prism_s3_ble/firmware.elf', 94, False),
    },
    'titan': {'m85': ('titan-native.elf', 40, True)},
}
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


def lane_bench(cfg, ctx, facts):
    """Use the lane-owned locked reference; never imply clean product admission."""
    source = Path(cfg['source']).resolve()
    script = source / 'scripts/bench.py'
    require(script.is_file() and not script.is_symlink(), 'Lane has no owned bench entry point')
    tracked = facts['source']['tracked_files']
    require('scripts/bench.py' in tracked, 'Bench entry point must be recorded in the lane')
    before = donor_identity(source)
    action = cfg['action']
    command = [sys.executable, '-B', str(script)]
    if action == 'bench-build':
        command.append('build')
        if cfg['lane'] == 'dualmcu':
            require(cfg.get('target') in DUAL_TARGETS, 'Unsupported DualMCU bench target')
            command += ['--target', cfg['target']]
    elif action == 'regression':
        command.append('test')
    else:
        raise ValueError('Unsupported bench action')
    run_key = hashlib.sha256(str(ctx.run_dir.resolve()).encode()).hexdigest()[:16]
    output = source / '_scratch/ael' / run_key
    facts['lane_output'] = str(output)
    require(not output.exists(), 'Fresh lane bench output required')
    command += ['--output', str(output)]
    log = ctx.logs_dir / 'lane-bench.log'
    facts.update(argv=command, cwd=str(source), lane_identity=before,
                 qualification='BENCH_ONLY: inherited/uncertain reference; no clean product or physical acceptance')
    with log.open('w') as out:
        proc = run_command(command, cwd=source, stdout=out, timeout=1200)
    facts.update(returncode=proc.returncode, log=str(log), log_sha256=sha(log))
    require(proc.returncode == 0, 'Lane bench operation failed; ' + str(log))
    require(donor_identity(source) == before, 'Lane source changed during bench operation')
    receipt = output / 'receipt.json'
    require(receipt.is_file() and not receipt.is_symlink(), 'Lane bench produced no execution receipt')
    record = json.loads(receipt.read_text())
    expected_schema = 'titan-bench-execution.v1' if cfg['lane'] == 'titan' else 'prism.operation.v1'
    require(record.get('schema') == expected_schema, 'Wrong lane bench receipt schema')
    require(record.get('operation') == ('build' if action == 'bench-build' else 'test'), 'Wrong lane receipt operation')
    if record.get('schema') == 'prism.operation.v1':
        require(record.get('returncode') == 0, 'Lane receipt records failed execution')
        require(record.get('product_admission') is False and record.get('device_proof') is False,
                'Bench receipt cannot claim product admission or device proof')
        commands = record.get('commands')
        require(isinstance(commands, list) and commands, 'Lane receipt has no executed commands')
        for executed in commands:
            require(isinstance(executed.get('argv'), list) and executed['argv'] and executed.get('returncode') == 0,
                    'Lane receipt contains missing or failed execution')
            name = Path(executed.get('log', ''))
            require(not name.is_absolute() and '..' not in name.parts and name.name,
                    'Unsafe lane command log path')
            command_log = output / name
            require(command_log.is_file() and not command_log.is_symlink() and sha(command_log) == executed.get('log_sha256'),
                    'Lane command log missing or changed')
    elif record.get('schema') == 'titan-bench-execution.v1':
        require(record.get('exit_code') == 0, 'Lane receipt records failed execution')
        require(record.get('product_admitted') is False and record.get('hardware_access') is False,
                'Bench receipt cannot claim product admission or hardware access')
    else:
        raise RuntimeError('Unknown lane bench receipt schema')
    require(str(record.get('classification', '')).startswith('BENCH_ONLY'), 'Unclassified bench receipt')
    facts['lane_receipts'] = [{'path': str(receipt), 'sha256': sha(receipt)}]
    if record['schema'] == 'titan-bench-execution.v1':
        nested = output / ('build/receipt.json' if action == 'bench-build' else 'checks/receipt.json')
        key = 'build_receipt_sha256' if action == 'bench-build' else 'checks_receipt_sha256'
        require(nested.is_file() and not nested.is_symlink() and sha(nested) == record.get(key),
                'Titan nested execution receipt missing or changed')
        if action == 'bench-build':
            build = json.loads(nested.read_text())
            require(build.get('pass') is True and isinstance(record.get('build_id'), str)
                    and len(record['build_id']) == 64 and build.get('build_id') == record['build_id']
                    and build.get('artifacts') == record.get('artifacts'),
                    'Titan nested build failed or differs from outer receipt')
        if action == 'regression':
            checks = json.loads(nested.read_text())
            require(checks.get('schema') == 'titan-adapter-checks.v1' and checks.get('exit_code') == 0
                    and checks.get('hardware_tested') is False, 'Titan adapter checks did not succeed within host scope')
        facts['lane_receipts'].append({'path': str(nested), 'sha256': sha(nested)})
    elif action == 'regression':
        nested = output / 'clean-components/receipt.json'
        require(nested.is_file() and not nested.is_symlink() and sha(nested) == record.get('clean_components_receipt_sha256'),
                'DualMCU clean component receipt missing or changed')
        checks = json.loads(nested.read_text())
        require(checks.get('schema') == 'prism.operation.v1' and checks.get('operation') == 'test'
                and checks.get('returncode') == 0 and checks.get('product_admission') is False
                and checks.get('device_proof') is False, 'DualMCU component tests did not succeed within host scope')
        facts['lane_receipts'].append({'path': str(nested), 'sha256': sha(nested)})
    if action == 'bench-build':
        artifacts = [p for p in output.rglob('*') if p.is_file() and p.suffix in ('.elf', '.hex', '.bin')]
        require(artifacts, 'Lane bench build produced no firmware')
        declared = record.get('artefacts') if record['schema'] == 'prism.operation.v1' else record.get('artifacts')
        require(isinstance(declared, dict) and declared, 'Lane build receipt has no artifact hashes')
        for name, digest in declared.items():
            relative = Path(name)
            require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe lane artifact path')
            artifact_root = output if record['schema'] == 'prism.operation.v1' else output / 'build'
            bound = artifact_root / relative
            require(bound.is_file() and not bound.is_symlink() and sha(bound) == digest,
                    'Declared lane artifact missing or changed: ' + name)
        for artifact in artifacts:
            relative = artifact.relative_to(output).as_posix()
            matches = [digest for name, digest in declared.items()
                       if relative == name or relative.endswith('/' + name)]
            require(len(matches) == 1 and matches[0] == sha(artifact), 'Lane build artifact not bound to receipt: ' + relative)
        facts['binaries'] = [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(artifacts)]


def lane_diagnosis(cfg, facts):
    """Report available capabilities without probing, opening or resetting hardware."""
    source = Path(cfg['source']).resolve()
    facts['capabilities'] = {
        'locked_bench_entry': (source / 'scripts/bench.py').is_file(),
        'native_product_build': 'scripts/build.py' in facts['source'].get('tracked_files', []),
        'native_product_host_checks': any(script in facts['source'].get('tracked_files', [])
                                          for script in ('scripts/native_check.py', 'scripts/native_test.py')),
        'migration_manifest': (source / 'docs/migration').is_dir(),
        'core_tag': facts['source']['core_tag'],
        'native_product_deployment': False,
    }
    facts['qualification'] = 'Read-only capability inventory; no firmware, electrical or optical acceptance'
    facts['remaining'] = [
        'Close the full required audio, effect and control inventory against frozen expectations',
        'Verify the native product receipt and actual linked source independently of bench source',
        'Identify and qualify the intended physical target before deployment',
    ]


def safe_file(root, relative):
    """Bind a regular file inside its declared root without symlink escapes."""
    name = Path(relative)
    require(name.parts and not name.is_absolute() and '..' not in name.parts,
            'Unsafe product file path: ' + str(relative))
    root = Path(root).resolve()
    file = root / name
    require(file.is_file() and not any((root / Path(*name.parts[:i])).is_symlink()
                                     for i in range(1, len(name.parts) + 1)),
            'Product file missing or symlinked: ' + str(relative))
    require(file.resolve().is_relative_to(root), 'Product file escaped declared root')
    return file


def validate_product_targets(output, declared, lane):
    """Bind native processor roles to immutable image/map bytes, without hardware access.

    This is one part of candidate build validation. It establishes neither full
    source admission nor timing, deployment permission or observed device identity.
    """
    targets = PRODUCT_TARGETS[lane]
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*.elf') if p.is_file()}
    require(actual == {spec[0] for spec in targets.values()}, 'Product application target set mismatch')
    executable_targets = {}
    for role, (relative, expected_machine, owns_runtime) in targets.items():
        executable = safe_file(output, relative)
        require(relative in declared and sha(executable) == declared[relative],
                'Product application image missing or changed')
        header = executable.read_bytes()[:52]
        require(len(header) == 52 and header[:7] == b'\x7fELF\x01\x01\x01',
                'Product image is not a little-endian ELF32 executable')
        image_type, machine, version, entry = struct.unpack_from('<HHII', header, 16)
        require(image_type == 2 and version == 1 and entry != 0 and machine == expected_machine,
                'Product ELF architecture or execution identity mismatch')
        map_relative = str(Path(relative).with_suffix('.map'))
        require(map_relative in declared, 'Product application lacks its bound dependency map')
        dependency_map_file = safe_file(output, map_relative)
        require(sha(dependency_map_file) == declared[map_relative], 'Product application map changed')
        dependency_map = dependency_map_file.read_text(errors='replace')
        has_runtime = ('prism::music::Runtime::' in dependency_map
                       or '_ZN5prism5music7Runtime' in dependency_map)
        require(has_runtime == owns_runtime,
                'Product processor runtime ownership mismatch: ' + role)
        executable_targets[role] = {'elf': relative, 'elf_sha256': sha(executable),
                                   'map': map_relative, 'map_sha256': declared[map_relative],
                                   'machine': machine, 'entry': entry,
                                   'owns_musical_runtime': owns_runtime}
    return executable_targets


def validate_product_receipt(record, output, source, lane, facts):
    """Validate actual candidate images; this grants no deployment admission."""
    require(record.get('schema') == 'prism-product-build.v1', 'Wrong product receipt schema')
    require(record.get('classification') == 'PRODUCT_CANDIDATE', 'Wrong product classification')
    require(type(record.get('exit_code')) is int and record.get('exit_code') == 0 and record.get('hardware_access') is False
            and record.get('product_admitted') is False, 'Invalid candidate execution scope')
    require(record.get('development_core', False) is False, 'Development Core is not an independent pinned build')
    require(record.get('lane') == lane, 'Product receipt lane mismatch')
    require(record.get('core_commit') == facts['source']['core_commit']
            and record.get('core_tag') == facts['source']['core_tag'], 'Product Core pin mismatch')
    require(isinstance(record.get('native_application'), (str, dict)) and record['native_application']
            and isinstance(record.get('implemented_behaviours'), list) and record['implemented_behaviours']
            and isinstance(record.get('open_dependencies'), list), 'Missing application/dependency account')
    roots, inputs = record.get('input_roots'), record.get('inputs')
    require(isinstance(roots, dict) and isinstance(inputs, dict), 'Missing product input inventory')
    require(Path(roots.get('lane', '')).resolve() == source.resolve()
            and Path(roots.get('core', '')).resolve() == (source / 'deps/PRISM-Core').resolve(),
            'Product lane/Core roots mismatch')
    bound_sources = {}
    tracked = facts['source'].get('tracked_files')
    require(isinstance(tracked, list) and tracked, 'Missing tracked product source identity')
    tracked = set(tracked)
    input_groups = []
    for group, root in roots.items():
        rows = inputs.get(group)
        if isinstance(root, dict) and group.startswith('vendor'):
            require(root and isinstance(rows, dict) and rows, 'Empty vendor input inventory')
            for label, base in root.items():
                require(label and '/' not in label, 'Invalid vendor root label')
                prefix = label + '/'
                selected = {name[len(prefix):]: digest for name, digest in rows.items() if name.startswith(prefix)}
                input_groups.append((group, base, selected, group + '/' + prefix))
            require(all(name.split('/', 1)[0] in root for name in rows), 'Unbound vendor input root')
        else:
            input_groups.append((group, root, rows, group + '/'))
    for group, root, rows, prefix in input_groups:
        require(group == 'lane' or group == 'core' or group.startswith('vendor'), 'Unsupported product input group')
        require(not any(old in str(root) for old in ('SpectraSynq_K1_Firmware',
                    'SpectraSynq-K1-DualMCU-Firmware', 'SpectraSynq-K1-RA8P1-Firmware')),
                'Product input depends on donor checkout')
        if group.startswith('vendor'):
            siblings = [name for name in LANES.values() if name != source.name]
            require(not any(part in Path(root).resolve().parts for part in siblings),
                    'Vendor input depends on another product lane')
        require(isinstance(rows, dict) and rows, 'Empty product input group')
        for name, digest in rows.items():
            require(not any(part in Path(name).parts for part in ('bench', '_scratch', 'reference')),
                    'Reference source in product input inventory')
            file = safe_file(root, name)
            require(sha(file) == digest, 'Product input changed: ' + group + '/' + name)
            if group in ('lane', 'core'):
                tracked_name = name if group == 'lane' else 'deps/PRISM-Core/' + name
                require(tracked_name in tracked, 'Product input absent from bound lane commit: ' + tracked_name)
            bound_sources[prefix + name] = digest
    toolchains = inputs.get('toolchain', {})
    require(isinstance(toolchains, dict) and toolchains, 'Missing compiler inventory')
    identities = [toolchains] if 'compiler_path' in toolchains else list(toolchains.values())
    for toolchain in identities:
        require(isinstance(toolchain, dict), 'Invalid compiler inventory')
        compiler = Path(toolchain.get('compiler_path', ''))
        require(compiler.is_file() and sha(compiler) == toolchain.get('compiler_sha256')
                and toolchain.get('compiler_version'), 'Compiler identity missing or changed')
        headers = toolchain.get('system_headers', {})
        require(isinstance(headers, dict), 'Invalid toolchain header inventory')
        for name, digest in headers.items():
            header = Path(name)
            require(header.is_absolute() and header.is_file() and not header.is_symlink()
                    and sha(header) == digest, 'Toolchain header missing or changed')
            require(header.resolve().is_relative_to(compiler.resolve().parent.parent),
                    'Toolchain header escaped compiler package')
            require(not any(old in str(header.resolve()) for old in ('SpectraSynq_K1_Firmware',
                        'SpectraSynq-K1-DualMCU-Firmware', 'SpectraSynq-K1-RA8P1-Firmware'))
                    and not any(part in header.resolve().parts for part in ('bench', 'reference')),
                    'Toolchain header depends on donor/reference source')
        libraries = toolchain.get('linked_libraries')
        require(isinstance(libraries, dict) and libraries, 'Missing linked runtime library inventory')
        for name, digest in libraries.items():
            library = Path(name)
            require(library.is_absolute() and library.is_file() and sha(library) == digest,
                    'Linked runtime library missing or changed')
            require(not any(old in str(library.resolve()) for old in ('SpectraSynq_K1_Firmware',
                        'SpectraSynq-K1-DualMCU-Firmware', 'SpectraSynq-K1-RA8P1-Firmware'))
                    and not any(part in library.resolve().parts for part in ('bench', 'reference')),
                    'Linked runtime library depends on donor/reference source')
            require(not any(part in library.resolve().parts for part in LANES.values()
                            if part != source.name), 'Linked runtime library depends on another product lane')
    objects = record.get('linked_objects')
    require(isinstance(objects, list) and objects, 'Missing linked object inventory')
    named_objects = set()
    for row in objects:
        require(row.get('source') in bound_sources
                and row.get('source_sha256') == bound_sources[row['source']], 'Unbound linked object source')
        file = safe_file(output, row.get('object', ''))
        require(file.suffix == '.o' and sha(file) == row.get('sha256'), 'Linked object missing or changed')
        require(row['object'] not in named_objects, 'Duplicate linked object')
        named_objects.add(row['object'])
    actual_objects = {p.relative_to(output).as_posix() for p in output.rglob('*.o') if p.is_file()}
    require(actual_objects == named_objects, 'Product object inventory incomplete')
    declared = record.get('artefacts')
    require(isinstance(declared, dict) and declared, 'Missing product image hashes')
    for name, digest in declared.items():
        require(sha(safe_file(output, name)) == digest, 'Product artefact missing or changed: ' + name)
    images = [p for p in output.rglob('*') if p.is_file() and p.suffix in ('.elf', '.hex', '.bin', '.map')]
    require(any(p.suffix == '.elf' for p in images) and any(p.suffix == '.map' for p in images),
            'Product requires native ELF and dependency map')
    require({p.relative_to(output).as_posix() for p in images}.issubset(declared), 'Unbound product image')
    executable_targets = validate_product_targets(output, declared, lane)
    require(any(name.startswith('core/music/') for name in bound_sources), 'Product lacks shared musical runtime input')
    facts.update(product_receipt=record, executable_targets=executable_targets,
                 qualification='PRODUCT_CANDIDATE: independent native compilation; full behaviour and physical gates remain open',
                 binaries=[{'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(images)])


def lane_product_build(cfg, ctx, facts):
    source = Path(cfg['source']).resolve()
    script = safe_file(source, 'scripts/build.py')
    require('scripts/build.py' in facts['source']['tracked_files'], 'Product builder must be recorded in lane')
    before = donor_identity(source)
    run_key = hashlib.sha256(str(ctx.run_dir.resolve()).encode()).hexdigest()[:16]
    output = source / '_scratch/ael-product' / run_key
    require(not output.exists(), 'Fresh product output required')
    command = [sys.executable, '-B', str(script), '--output', str(output)]
    log = ctx.logs_dir / 'lane-product-build.log'
    facts.update(argv=command, cwd=str(source), lane_identity=before, lane_output=str(output))
    with log.open('w') as out:
        proc = run_command(command, cwd=source, stdout=out, timeout=1200)
    facts.update(returncode=proc.returncode, log=str(log), log_sha256=sha(log))
    require(proc.returncode == 0, 'Lane product build failed; ' + str(log))
    require(donor_identity(source) == before, 'Lane source changed during product build')
    receipt = safe_file(output, 'receipt.json')
    validate_product_receipt(json.loads(receipt.read_text()), output, source, cfg['lane'], facts)
    facts['lane_receipts'] = [{'path': str(receipt), 'sha256': sha(receipt)}]


def validate_native_checks(record, output, source, lane, facts):
    """Validate observed lane host checks without admitting untested inventory."""
    require(type(record.get('exit_code')) is int and record['exit_code'] == 0
            and record.get('hardware_access') is False and record.get('product_admitted') is False,
            'Invalid native host execution scope')
    require(record.get('development_core', False) is False, 'Native checks require pinned Core')
    tracked = set(facts['source']['tracked_files'])
    inputs = record.get('inputs')
    require(isinstance(inputs, dict) and inputs, 'Missing native check source inventory')
    for name, digest in inputs.items():
        require(name in tracked and sha(safe_file(source, name)) == digest,
                'Native check input unbound or changed: ' + name)
        require(not any(part in Path(name).parts for part in ('bench', '_scratch', 'reference')),
                'Native check includes reference capsule source')
    if lane == 'titan':
        require(record.get('schema') == 'prism-titan-native-checks.v1'
                and record.get('classification') == 'HOST_QUALIFICATION_ONLY', 'Wrong Titan native check receipt')
        core = source / 'deps/PRISM-Core'
        require(Path(record.get('core_root', '')).resolve() == core.resolve(), 'Native checks use foreign Core')
        core_inputs = record.get('core_inputs')
        require(isinstance(core_inputs, dict) and core_inputs, 'Missing native Core check inventory')
        for name, digest in core_inputs.items():
            require('deps/PRISM-Core/' + name in tracked and sha(safe_file(core, name)) == digest,
                    'Native check Core input unbound or changed')
        operations = record.get('results')
        require(isinstance(operations, list) and operations, 'Missing observed native checks')
        positives, faults, compiled_outputs, fault_artifacts, executions = [], [], {}, [], []
        for row in operations:
            require(isinstance(row.get('argv'), list) and row['argv']
                    and type(row.get('exit_code')) is int and row.get('case'), 'Invalid native check operation')
            if row['case'].endswith(' planted fault'):
                require(row['exit_code'] != 0, 'Native planted fault survived')
                require(len(row['argv']) == 1, 'Native fault must execute its compiled binary')
                binary = Path(row['argv'][0]).resolve()
                require(binary in compiled_outputs, 'Native fault lacks its successful compilation')
                require(binary.is_relative_to(output.resolve()), 'Native fault binary escapes check output')
                artifact = safe_file(output, str(binary.relative_to(output.resolve())))
                fault_artifacts.append({'case': row['case'], 'binary': str(binary),
                                        'sha256': sha(artifact), 'compile_argv': compiled_outputs.pop(binary)})
                faults.append(row['case'])
            else:
                require(row['exit_code'] == 0, 'Native positive check failed')
                if row['case'].endswith(' compile'):
                    argv = row['argv']
                    require(Path(argv[0]).name in ('clang++', 'g++', 'c++', 'clang', 'gcc')
                            and argv.count('-o') == 1 and argv.index('-o') + 1 < len(argv),
                            'Native compile lacks a compiler output')
                    binary = Path(argv[argv.index('-o') + 1]).resolve()
                    require(binary.is_relative_to(output.resolve()), 'Native compiler output escapes checks')
                    compiled_outputs[binary] = argv
                else:
                    require(len(row['argv']) == 1, 'Native positive must execute its compiled binary')
                    binary = Path(row['argv'][0]).resolve()
                    require(binary in compiled_outputs, 'Native positive lacks its successful compilation')
                    require(binary.is_relative_to(output.resolve()), 'Native positive binary escapes check output')
                    artifact = safe_file(output, str(binary.relative_to(output.resolve())))
                    executions.append({'case': row['case'], 'binary': str(binary),
                                       'sha256': sha(artifact), 'compile_argv': compiled_outputs[binary]})
                positives.append(row['case'])
        require(executions and faults and any(case.endswith(' compile') for case in positives),
                'Native checks require actual compilation, positive execution and compiled faults')
        facts['compiled_fault_artifacts'] = fault_artifacts
        facts['compiled_positive_artifacts'] = executions
    else:
        require(record.get('schema') == 'prism.native-host-test.v1'
                and record.get('classification') == 'PRODUCT_CANDIDATE'
                and record.get('operation') == 'test', 'Wrong DualMCU native check receipt')
        operations = record.get('operations')
        require(isinstance(operations, list) and operations, 'Missing observed native checks')
        def check_log(row):
            file = safe_file(output, row.get('log', ''))
            require(sha(file) == row.get('log_sha256'), 'Native check log missing or changed')
        for row in operations:
            require(isinstance(row.get('argv'), list) and row['argv']
                    and type(row.get('returncode')) is int and row['returncode'] == 0,
                    'Native positive check failed or missing')
            if 'oracle_returncode' in row:
                require(type(row['oracle_returncode']) is int and row['oracle_returncode'] == 0,
                        'Native differential oracle failed')
            check_log(row)
        mutations = record.get('mutations')
        require(isinstance(mutations, list) and mutations, 'Missing compiled native faults')
        for row in mutations:
            require(type(row.get('compile_returncode')) is int and row['compile_returncode'] == 0
                    and type(row.get('run_returncode')) is int and row['run_returncode'] != 0
                    and row.get('detected') is True and row.get('name'), 'Native planted fault survived or did not compile')
            check_log(row)
        positives, faults = [row['argv'] for row in operations], [row['name'] for row in mutations]
    facts.update(native_check_receipt=record, observed_positive_checks=positives, rejected_compiled_faults=faults,
                 qualification='NATIVE_HOST_CANDIDATE_CHECKS: observed owned application checks; full inventory and physical gates remain open')


def lane_product_test(cfg, ctx, facts):
    source = Path(cfg['source']).resolve()
    script_name = 'scripts/native_check.py' if cfg['lane'] == 'titan' else 'scripts/native_test.py'
    script = safe_file(source, script_name)
    require(script_name in facts['source']['tracked_files'], 'Native check entry must be bound in lane')
    before = donor_identity(source)
    compiler = Path(shutil.which('clang++') or '').resolve()
    require(compiler.is_file(), 'Native host compiler unavailable')
    compiler_digest = sha(compiler)
    run_key = hashlib.sha256(str(ctx.run_dir.resolve()).encode()).hexdigest()[:16]
    output = source / '_scratch/ael-product-test' / run_key
    require(not output.exists(), 'Fresh native check output required')
    command = [sys.executable, '-B', str(script), '--output', str(output)]
    log = ctx.logs_dir / 'lane-product-test.log'
    facts.update(argv=command, cwd=str(source), lane_identity=before, lane_output=str(output),
                 host_compiler={'path': str(compiler), 'sha256': compiler_digest})
    with log.open('w') as out:
        proc = run_command(command, cwd=source, stdout=out, timeout=1200)
    facts.update(returncode=proc.returncode, log=str(log), log_sha256=sha(log))
    require(proc.returncode == 0, 'Native host checks failed; ' + str(log))
    require(donor_identity(source) == before and sha(compiler) == compiler_digest,
            'Native source/compiler changed during checks')
    receipt = safe_file(output, 'receipt.json')
    validate_native_checks(json.loads(receipt.read_text()), output, source, cfg['lane'], facts)
    facts['lane_receipts'] = [{'path': str(receipt), 'sha256': sha(receipt)}]


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
                raise RuntimeError('No native firmware/deployment profile admitted in this PRISM lane; bench operations, donor observation and core-test are separate capabilities')
            elif action in ('bench-build', 'regression'):
                lane_bench(cfg, ctx, facts)
            elif action == 'product-build':
                lane_product_build(cfg, ctx, facts)
            elif action == 'product-test':
                lane_product_test(cfg, ctx, facts)
            elif action == 'diagnose':
                lane_diagnosis(cfg, facts)
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
                facts['qualification'] = 'Fresh host C++ compilation and JS parity only; no native firmware or device qualification'
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
