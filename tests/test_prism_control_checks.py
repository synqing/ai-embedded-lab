"""Protocol vectors and independent actual C++ ControlOwner emitter, host only."""
import copy
from pathlib import Path
import struct
import subprocess

import pytest

from ael.prism_control_checks import decode_state, verify_applied, verify_readback

SCHEMA = bytes(range(32)).hex()
KX = Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan')
FIELDS = {str(i + 1): value for i, value in enumerate(
    (0.125, 0.25, 0.5, 0.75, 1.0, 0.0, 0.375, 0.625, 2, 1, 0, 1, 0, 1, 12, 1, 1, 44))}


def vector():
    # A frozen non-default protocol record, independent standard struct writer.
    return (struct.pack('<6I', 0x454D5354, 1, 1, 7, 9, 31)
            + struct.pack('<9f', .125, .25, .5, .75, 1., 0., .375, .625, .5)
            + struct.pack('<12I', 2, 0x75, 12, 0xFFDF, 31, 30, 29, 42, 0, 0, 1, 1)
            + bytes(range(32)) + struct.pack('<5I', 44, 0, 0, 0, 0))


def test_frozen_vector_decodes_every_field():
    actual = decode_state(vector(), SCHEMA)
    assert actual['fields'] == FIELDS
    assert actual['palette'] == 44 and actual['brightness'] == 12
    assert actual['accepted'] == 31 and actual['rendered'] == 30 and actual['emitted'] == 29
    assert actual['changed'] == actual['mode_transition'] == 1


@pytest.mark.parametrize('offset,value', [(0, 0), (4, 2), (8, 0), (12, 0), (20, 0),
    (24, 0x7FC00000), (28, 0x7F800000), (32, 0xBF800000), (56, 0),
    (60, 7), (64, 0x80), (68, 256), (72, 0xFFFF), (92, 3),
    (96, 2), (100, 2), (104, 2), (140, 45), (144, 1), (156, 1)])
def test_wire_corruption_refused(offset, value):
    body = bytearray(vector())
    struct.pack_into('<I', body, offset, value)
    with pytest.raises(ValueError):
        decode_state(body, SCHEMA)


def test_length_schema_and_nonbytes_refused():
    for body in (vector()[:-1], vector() + b'\0', list(vector())):
        with pytest.raises(ValueError):
            decode_state(body, SCHEMA)
    for schema in ('00' * 32, 'x' * 64, SCHEMA[:-1], None):
        with pytest.raises(ValueError):
            decode_state(vector(), schema)


@pytest.fixture(scope='module')
def emitted(tmp_path_factory):
    work = tmp_path_factory.mktemp('actual-control-owner')
    source = work / 'emit.cpp'
    source.write_text(r'''
#include "platform/titan/control.h"
#include <cstdio>
using namespace prism::titan;
bool apply(void*,const Settings&){return true;}
int main(){
 std::uint8_t schema[32];for(unsigned i=0;i<32;++i)schema[i]=i;
 ControlOwner owner(nullptr,apply,7,schema);
 if(!owner.bind(expected_uid,schema,7))return 1;
 std::uint8_t p[168]{},out[160]{};unsigned n=0;
 const auto emit=[&](unsigned bytes){const auto status=owner.execute(p,bytes,out,n);return !status&&n==160&&std::fwrite(out,1,n,stdout)==n;};
 const auto get=[&](unsigned req){wire::put(p,0x454D0101);wire::put(p+4,req);wire::put(p+8,7);wire::put(p+12,0);return emit(16);};
 if(!get(10))return 2;
 const float f[]={.125F,.25F,.5F,.75F,1.F,0.F,.375F,.625F};
 const unsigned u[]={2,1,0,1,0,1,12,1,1,44};
 const auto patch=[&](unsigned req,unsigned rev){
  wire::put(p,0x454D0102);wire::put(p+4,rev);wire::put(p+8,req);wire::put(p+12,7);wire::put(p+16,0x3ffff);wire::put(p+20,18);
  for(unsigned i=0;i<18;++i){const auto kind=i<8?1U:i==8?3U:(i==14||i==17)?4U:2U;wire::put(p+24+i*8,(kind<<16)|(i+1));wire::put(p+28+i*8,i<8?scalar_bits(f[i]):u[i-8]);}
  return emit(168);
 };
 if(!patch(11,0))return 3;owner.rendered();owner.emitted();
 if(!get(12)||!patch(13,1)||!get(14))return 4;
 return std::fflush(stdout)?5:0;
}
''')
    binary = work / 'emit'
    subprocess.run(['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I' + str(KX), '-I' + str(KX / 'deps/PRISM-Core'),
                    str(source), '-o', str(binary)], check=True, capture_output=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True)
    assert len(result.stdout) == 800
    return [decode_state(result.stdout[i:i+160], SCHEMA) for i in range(0, 800, 160)]


def test_actual_cpp_emitter_patch_and_fresh_readback(emitted):
    initial, applied, readback, noop, last = emitted
    assert initial['brightness'] == 100  # Current autonomous default preserved.
    assert initial['fields']['16'] == 1
    assert applied['fields'] == FIELDS
    assert applied['settings_words'][2] == 0x3F000000
    verify_applied(initial, applied, FIELDS, boot=7, request=11)
    verify_readback(applied, readback, boot=7, request=12)
    assert readback['rendered'] == readback['emitted'] == 11
    verify_applied(readback, noop, FIELDS, boot=7, request=13)
    assert noop['revision'] == applied['revision'] == 1
    assert noop['accepted'] == 11 and noop['changed'] == 0
    verify_readback(noop, last, boot=7, request=14)


@pytest.mark.parametrize('field,value', [('18', 43), ('15', 100), ('9', 0), ('16', 0), ('17', 0),
                                        ('3', .50000006), ('10', 0), ('11', 1), ('12', 0), ('14', 0)])
def test_wrong_applied_palette_dimming_mode_float_or_flag_rejected(emitted, field, value):
    requested = dict(FIELDS, **{field: value})
    with pytest.raises(ValueError, match='settings differ'):
        verify_applied(emitted[0], emitted[1], requested, boot=7, request=11)


@pytest.mark.parametrize('key,value', [('revision', 0), ('accepted', 10), ('deduplicated', 1),
                                      ('changed', 0), ('mode_transition', 0), ('status', 3),
                                      ('boot', 8), ('request', 13), ('schema_sha256', '00' * 32)])
def test_applied_identity_status_and_revision_rejected(emitted, key, value):
    applied = dict(emitted[1], **{key: value})
    with pytest.raises(ValueError):
        verify_applied(emitted[0], applied, FIELDS, boot=7, request=11)


def test_unrequested_field_mutation_rejected(emitted):
    initial, applied = emitted[:2]
    requested = dict(FIELDS)
    del requested['18']
    with pytest.raises(ValueError, match='settings differ'):
        verify_applied(initial, applied, requested, boot=7, request=11)


@pytest.mark.parametrize('key,value', [('revision', 2), ('accepted', 13), ('deduplicated', 1),
                                      ('changed', 1), ('mode_transition', 1), ('status', 3),
                                      ('boot', 8), ('request', 11), ('schema_sha256', '00' * 32)])
def test_fresh_readback_rejects_replay_and_revision_loss(emitted, key, value):
    readback = dict(emitted[2], **{key: value})
    with pytest.raises(ValueError):
        verify_readback(emitted[1], readback, boot=7, request=12)


@pytest.mark.parametrize('index', range(18))
def test_fresh_readback_rejects_each_changed_word(emitted, index):
    readback = copy.deepcopy(emitted[2])
    readback['settings_words'][index] ^= 1
    with pytest.raises(ValueError, match='settings changed'):
        verify_readback(emitted[1], readback, boot=7, request=12)


@pytest.mark.parametrize('fields', [{}, {'19': 1}, {'0': 1}, {'1': True}, {'1': float('nan')},
    {'1': 1.01}, {'9': 7}, {'15': 256}, {'18': 45}, {'10': 2}, {'9': 2.0}, {'01': .125, '1': .125}])
def test_invalid_requested_fields_rejected(emitted, fields):
    with pytest.raises(ValueError):
        verify_applied(emitted[0], emitted[1], fields, boot=7, request=11)
