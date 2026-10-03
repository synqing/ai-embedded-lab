"""Candidate build admission checks, entirely isolated from physical hardware."""
import copy
from pathlib import Path
import struct

import pytest

from ael.adapters import prism_lane as lane


@pytest.fixture
def candidate(tmp_path):
    source = tmp_path / 'Kx-Titan'
    output = tmp_path / 'output'
    vendor = tmp_path / 'pinned-bsp'
    core = source / 'deps/PRISM-Core'
    roots = {'lane': source, 'core': core, 'vendor': vendor}
    paths = {'lane': 'src/application.cpp', 'core': 'music/runtime.cpp', 'vendor': 'startup.c'}
    inputs = {}
    for group, relative in paths.items():
        file = roots[group] / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('source ' + group)
        inputs[group] = {relative: lane.sha(file)}
    compiler = tmp_path / 'toolchain/bin/compiler'
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b'isolated compiler fixture')
    library = tmp_path / 'libfixture.a'
    library.write_bytes(b'isolated runtime archive fixture')
    inputs['toolchain'] = {'compiler_path': str(compiler), 'compiler_sha256': lane.sha(compiler),
                           'compiler_version': 'fixture-v1', 'linked_libraries': {str(library): lane.sha(library)}}
    output.mkdir()
    objects = []
    for group, relative in paths.items():
        obj = output / (group + '.o')
        obj.write_bytes(('object ' + group).encode())
        objects.append({'object': obj.name, 'sha256': lane.sha(obj), 'source': group + '/' + relative,
                        'source_sha256': inputs[group][relative]})
    header = bytearray(52)
    header[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHII', header, 16, 2, 40, 1, 0x02000001)
    (output / 'image.elf').write_bytes(header)
    (output / 'image.map').write_text('prism::music::Runtime::process_i16')
    record = {'schema': 'prism-product-build.v1', 'classification': 'PRODUCT_CANDIDATE',
              'exit_code': 0, 'hardware_access': False, 'product_admitted': False, 'lane': 'titan',
              'core_commit': 'pinned-commit', 'core_tag': 'pinned-tag',
              'native_application': 'M85 autonomous application', 'implemented_behaviours': ['PCM AP VP'],
              'open_dependencies': ['physical qualification'], 'input_roots': {k: str(v) for k, v in roots.items()},
              'inputs': inputs, 'linked_objects': objects,
              'artefacts': {p.name: lane.sha(p) for p in output.iterdir() if p.suffix in ('.elf', '.map')}}
    facts = {'source': {'core_commit': 'pinned-commit', 'core_tag': 'pinned-tag',
                       'tracked_files': ['src/application.cpp', 'deps/PRISM-Core/music/runtime.cpp']}}
    return record, output, source, facts


def test_candidate_is_native_compilation_without_deployment_admission(candidate):
    record, output, source, facts = candidate
    lane.validate_product_receipt(record, output, source, 'titan', facts)
    assert len(facts['binaries']) == 2
    assert facts['product_receipt']['product_admitted'] is False


def test_multiple_vendor_roots_and_target_compilers_are_bound(candidate):
    record, output, source, facts = candidate
    record['input_roots']['vendor'] = {'sdk': record['input_roots']['vendor']}
    record['inputs']['vendor'] = {'sdk/' + k: v for k, v in record['inputs']['vendor'].items()}
    for row in record['linked_objects']:
        if row['source'].startswith('vendor/'):
            row['source'] = row['source'].replace('vendor/', 'vendor/sdk/', 1)
    compiler = record['inputs']['toolchain']
    record['inputs']['toolchain'] = {'target_a': compiler, 'target_b': copy.deepcopy(compiler)}
    lane.validate_product_receipt(record, output, source, 'titan', facts)
    record['inputs']['toolchain']['target_b']['compiler_sha256'] = 'wrong'
    with pytest.raises(RuntimeError):
        lane.validate_product_receipt(record, output, source, 'titan', facts)


@pytest.mark.parametrize('group,relative', [('lane','vendor/palettes/__pycache__/generate.pyc'),
                                          ('lane','src/untracked.cpp'), ('core','music/untracked.cpp')])
def test_existing_hashed_untracked_product_inputs_are_rejected(candidate, group, relative):
    record, output, source, facts = candidate
    file = Path(record['input_roots'][group]) / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b'actual but uncommitted product input')
    record['inputs'][group][relative] = lane.sha(file)
    with pytest.raises(RuntimeError, match='absent from bound lane commit'):
        lane.validate_product_receipt(record, output, source, 'titan', facts)


def test_selected_system_header_hash_is_verified(candidate):
    record, output, source, facts = candidate
    header = source.parent / 'toolchain/include/cstdint'
    header.parent.mkdir(parents=True)
    header.write_text('isolated selected toolchain header')
    record['inputs']['toolchain']['system_headers'] = {str(header): lane.sha(header)}
    lane.validate_product_receipt(record, output, source, 'titan', facts)
    header.write_text('changed standard header')
    with pytest.raises(RuntimeError, match='Toolchain header missing or changed'):
        lane.validate_product_receipt(record, output, source, 'titan', facts)


def test_foreign_file_cannot_be_disguised_as_toolchain_header(candidate):
    record, output, source, facts = candidate
    header = source.parent / 'K1-DualMCU/foreign.h'
    header.parent.mkdir()
    header.write_text('foreign lane source')
    record['inputs']['toolchain']['system_headers'] = {str(header): lane.sha(header)}
    with pytest.raises(RuntimeError, match='escaped compiler package'):
        lane.validate_product_receipt(record, output, source, 'titan', facts)


@pytest.mark.parametrize('fault', ['scope', 'hardware', 'admission', 'failed', 'core', 'lane',
                                  'source_drift', 'object_drift', 'object_omitted', 'extra_object',
                                  'missing_elf', 'image_drift', 'extra_image', 'missing_map', 'stub_map',
                                  'input_symlink', 'escape', 'compiler_drift', 'donor_root', 'reference_input',
                                  'development_core', 'sibling_root', 'library_drift', 'missing_libraries', 'boolean_exit',
                                  'donor_library', 'sibling_library', 'reference_library',
                                  'fake_elf', 'wrong_architecture', 'non_executable'])
def test_broken_product_receipts_are_rejected(candidate, fault):
    original, output, source, facts = candidate
    record = copy.deepcopy(original)
    if fault == 'scope': record['classification'] = 'BENCH_ONLY'
    if fault == 'hardware': record['hardware_access'] = True
    if fault == 'admission': record['product_admitted'] = True
    if fault == 'failed': record['exit_code'] = 1
    if fault == 'core': record['core_commit'] = 'wrong'
    if fault == 'lane': record['lane'] = 'dualmcu'
    if fault == 'source_drift': (source / 'src/application.cpp').write_text('changed')
    if fault == 'object_drift': (output / 'core.o').write_bytes(b'changed')
    if fault == 'object_omitted': record['linked_objects'].pop()
    if fault == 'extra_object': (output / 'unbound.o').write_bytes(b'extra')
    if fault == 'missing_elf': (output / 'image.elf').unlink()
    if fault == 'image_drift': (output / 'image.elf').write_bytes(b'changed')
    if fault == 'extra_image': (output / 'unbound.bin').write_bytes(b'extra')
    if fault == 'missing_map': (output / 'image.map').unlink()
    if fault == 'stub_map':
        (output / 'image.map').write_text('stub renderer')
        record['artefacts']['image.map'] = lane.sha(output / 'image.map')
    if fault == 'input_symlink':
        file = source / 'src/application.cpp'
        target = source / 'application-original.cpp'
        file.rename(target)
        file.symlink_to(target)
    if fault == 'escape': record['inputs']['lane']['../escape.cpp'] = 'wrong'
    if fault == 'compiler_drift': Path(record['inputs']['toolchain']['compiler_path']).write_bytes(b'changed')
    if fault == 'donor_root': record['input_roots']['vendor'] = '/tmp/SpectraSynq-K1-RA8P1-Firmware'
    if fault == 'reference_input': record['inputs']['lane']['bench/oracle.cpp'] = 'wrong'
    if fault == 'development_core': record['development_core'] = True
    if fault == 'sibling_root': record['input_roots']['vendor'] = str(source.parent / 'K1-DualMCU')
    if fault == 'library_drift': Path(next(iter(record['inputs']['toolchain']['linked_libraries']))).write_bytes(b'changed')
    if fault == 'missing_libraries': record['inputs']['toolchain'].pop('linked_libraries')
    if fault == 'boolean_exit': record['exit_code'] = False
    if fault in ('fake_elf', 'wrong_architecture', 'non_executable'):
        image = bytearray((output / 'image.elf').read_bytes())
        if fault == 'fake_elf': image[:4] = b'TEXT'
        if fault == 'wrong_architecture': struct.pack_into('<H', image, 18, 62)
        if fault == 'non_executable': struct.pack_into('<H', image, 16, 1)
        (output / 'image.elf').write_bytes(image)
        record['artefacts']['image.elf'] = lane.sha(output / 'image.elf')
    if fault in ('donor_library', 'sibling_library', 'reference_library'):
        directory = {'donor_library': 'SpectraSynq-K1-RA8P1-Firmware',
                     'sibling_library': 'K1-DualMCU', 'reference_library': 'bench'}[fault]
        archive = source.parent / directory / 'libfixture.a'
        archive.parent.mkdir(exist_ok=True)
        archive.write_bytes(b'isolated inadmissible archive fixture')
        record['inputs']['toolchain']['linked_libraries'] = {str(archive): lane.sha(archive)}
    with pytest.raises(RuntimeError):
        lane.validate_product_receipt(record, output, source, 'titan', facts)
