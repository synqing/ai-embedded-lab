"""Finite bench-trial refusals and a native-production framing fixture."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import Mock
import zlib
import pytest
from ael.adapters import prism_bench_trial as bench
from ael import prism_native as native


def bound(p):
    return {'path': str(p), 'sha256': bench.sha(p)}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    from ael.adapters import prism_lane
    source = tmp_path / 'candidate'; source.mkdir()
    (source / 'deps').mkdir(); (source / 'deps/prism-core.lock.json').write_text(json.dumps({'commit':'core','tag':'v0.9.0'}))
    build = tmp_path / 'build'; build.mkdir()
    target='prism_s3_ble_bench16_diag'
    image=build/'build'/target/target/'firmware.bin'; image.parent.mkdir(parents=True);image.write_bytes(b'candidate')
    receipt=build/'receipt.json';receipt.write_text(json.dumps({'source_binding_hash':'fixture-binding','artefacts':{image.relative_to(build).as_posix():bench.sha(image)}}))
    recovery=tmp_path/'current-app.bin';recovery.write_bytes(b'recovery')
    raw=tmp_path/'identity.log';raw.write_text('actual identity fixture; not hardware evidence')
    preflight=tmp_path/'preflight.json'
    observed={'identity':bench.TARGETS[target][1],'target':target,'observed_unix':time.time(),'owner_clear':True,
              'method':'fixture','raw_evidence':bound(raw),'port':'/dev/cu.fixture'}
    preflight.write_text(json.dumps(observed))
    m={'source_binding_hash':'fixture-binding','schema':'prism.bench-trial.v1','target':target,'identity':observed['identity'],'source_commit':'candidate',
       'build_receipt':bound(receipt),'image':bound(image),'offset':0x10000,'permitted_range':[0x10000,0x650000],
       'port':'/dev/cu.fixture','preflight':bound(preflight),'recovery':{'image':bound(recovery),'restore_method':'app-only fixture','provenance':'current fixture'},
       'authority':{k:True for k in ['exclusive_owner','identity_verified','serial_open_reset_accounted','replacement_authorised','recovery_verified','retained_bootloader_compatible','security_compatible','peer_isolation']}}
    manifest=tmp_path/'deployment.json'
    cfg={'source':str(source),'lane':'dualmcu','target':target,'action':'bench-trial-flash','deployment_manifest':str(manifest)}
    monkeypatch.setattr(prism_lane,'git',lambda root,*args: 'candidate' if args==('rev-parse','HEAD') else '' if args[0]=='status' else 'main.cpp')
    monkeypatch.setattr(prism_lane,'validate_product_receipt',lambda *a, **kw: None)
    return m,cfg,manifest,preflight,observed


@pytest.mark.parametrize('fault',['identity','source','image','range','offset','recovery','authority','stale','wrong_preflight','owner','raw_changed','runtime_binding'])
def test_refusal_never_invokes_programmer(prepared, tmp_path, monkeypatch, fault):
    m,cfg,manifest,preflight,observed=prepared
    if fault=='runtime_binding':m['source_binding_hash']='wrong'
    if fault=='identity':m['identity']='wrong'
    if fault=='source':m['source_commit']='other'
    if fault=='image':m['image']['sha256']='wrong'
    if fault=='range':m['permitted_range']=[0,0x1000000]
    if fault=='offset':m['offset']=0
    if fault=='recovery':m['recovery']['image']['sha256']='wrong'
    if fault=='authority':m['authority']['replacement_authorised']=False
    if fault=='stale':observed['observed_unix']-=121
    if fault=='wrong_preflight':observed['identity']='wrong'
    if fault=='owner':observed['owner_clear']=False
    if fault=='raw_changed':Path(observed['raw_evidence']['path']).write_text('changed')
    preflight.write_text(json.dumps(observed));m['preflight']=bound(preflight);manifest.write_text(json.dumps(m))
    invoked=Mock(side_effect=AssertionError('Refused request launched process'))
    monkeypatch.setattr(bench.subprocess,'run',invoked)
    logs=tmp_path/'logs';logs.mkdir()
    with pytest.raises(RuntimeError):bench.execute(cfg,SimpleNamespace(run_dir=tmp_path,logs_dir=logs),{})
    invoked.assert_not_called()


def test_success_programmer_is_exact_app_only(prepared,tmp_path,monkeypatch):
    m,cfg,manifest,*_=prepared;manifest.write_text(json.dumps(m))
    logs=tmp_path/'logs';logs.mkdir(); calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1 if argv[0]=='lsof' else 0,stdout='')
    monkeypatch.setattr(bench.subprocess,'run',run)
    facts={};bench.execute(cfg,SimpleNamespace(run_dir=tmp_path,logs_dir=logs),facts)
    assert facts['programmed'] is True and facts['runtime_boot_verified'] is False
    assert len(calls)==2 and calls[-1][-2]=='0x10000'
    assert '--port-filter' in calls[-1] and 'erase_flash' not in calls[-1]
    assert json.loads((logs/'native-invocation.json').read_text())['programmed'] is False


def test_native_protocol_against_production_transport(tmp_path):
    root=Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan')
    cpp=tmp_path/'wire.cpp';exe=tmp_path/'wire'
    cpp.write_text('''#include "platform/titan/transport.h"
#include <cstdio>
using namespace prism::titan;
unsigned call(void*,std::uint32_t op,const std::uint8_t*p,unsigned n,std::uint8_t*out,unsigned&size){if(op!=1||n){size=0;return 3;}const char text[]="{\\"native_fixture\\":true}";size=sizeof(text)-1;std::memcpy(out,text,size);return 0;}
int main(){wire::Transport t(nullptr,call);unsigned char b;while(std::fread(&b,1,1,stdin))if(!t.feed(&b,1))return 2;std::fwrite(t.response(),1,t.response_size(),stdout);}
''')
    subprocess.run(['clang++','-std=c++17','-I'+str(root),str(cpp),'-o',str(exe)],check=True,capture_output=True)
    q=native.request(1,sequence=23,cookie=42)
    answer=subprocess.run([str(exe)],input=q,capture_output=True,check=True).stdout
    assert json.loads(native.response(answer,23,42))=={'native_fixture':True}
    with pytest.raises(ValueError):native.response(answer,22,42)
    bad=bytearray(answer);bad[-1]^=1
    with pytest.raises(ValueError):native.response(bad,23,42)
    badq=bytearray(q);badq[28]^=1
    rejected=subprocess.run([str(exe)],input=badq,capture_output=True,check=True).stdout
    with pytest.raises(ValueError,match='rejection'):native.response(rejected,23,42)


def test_native_control_encoding_and_bind():
    assert len(native.bind_payload(17))==68
    p=native.patch_payload({'9':6,'15':100},17,3,42)
    assert struct.unpack_from('<6I',p)==(0x454D0102,3,42,17,(1<<8)|(1<<14),2)
    assert struct.unpack_from('<HHI',p,24)==(9,3,6)
    assert struct.unpack_from('<HHI',p,32)==(15,4,100)
    with pytest.raises(ValueError):native.patch_payload({'19':1},17,3,42)


def test_device_time_window_ignores_host_arrival():
    first={'epoch':1,'capture_time_us':1000000,'sample_end':12800,'hops':200,'rejected_hops':0,'logical_frame':120}
    last={**first,'capture_time_us':61000000,'sample_end':780800,'hops':12200,'logical_frame':7320}
    result=native.window(first,last)
    assert result['analysis_sample_rate_hz']==12800 and result['analysis_hop_rate_hz']==200
    assert result['physical_output_rate_measured'] is False
    with pytest.raises(ValueError):native.window(first,first)
    with pytest.raises(ValueError):native.window(first,{**last,'epoch':2})


def test_stalled_native_reader_has_finite_deadline(monkeypatch):
    now=iter([0,1,2,3,4]);monkeypatch.setattr(native.time,'monotonic',lambda:next(now))
    port=SimpleNamespace(read=lambda n:b'')
    with pytest.raises(TimeoutError):native.read_exact(port,32)


def test_snapshot_binds_nonzero_native_device_record():
    body=bytearray(1184);struct.pack_into('<I',body,0,0x53564C54)
    source='ab'*32
    body[728:744]=bytes.fromhex(native.UID);body[744:776]=bytes.fromhex(source);body[776:808]=bytes.fromhex(native.SCHEMA)
    struct.pack_into('<Q',body,8,45);struct.pack_into('<Q',body,32,225000)
    struct.pack_into('<Q',body,48,2880);struct.pack_into('<f',body,96,.75)
    decoded=native.snapshot(body,source)
    assert decoded['generation']==45 and decoded['pcm_peak']==.75 and decoded['sample_end']==2880
    body[744]^=1
    with pytest.raises(ValueError):native.snapshot(body,source)


def _titan_output_proof(tmp_path, image_sha, **changes):
    raw = tmp_path / 'loopback.csv'; raw.write_text('lane,frame,ok\nA,1,1\nB,1,1\n')
    proof = {'schema': 'prism.titan.output-qualification.v1', 'image_sha256': image_sha, 'off_product': True,
             'method': 'pin-loopback', 'lanes_verified': ['A', 'B'], 'frames_completed': 120,
             'stuck_high_detected': False, 'raw_evidence': bound(raw)}
    proof.update(changes)
    path = tmp_path / 'output-proof.json'; path.write_text(json.dumps(proof))
    return {'image': {'path': 'x', 'sha256': image_sha}, 'output_qualification': bound(path)}


@pytest.mark.parametrize('method', bench.OUTPUT_PROOF_METHODS)
def test_titan_output_assertions_and_two_row_csv_are_not_physical_proof(tmp_path, method):
    with pytest.raises(RuntimeError, match='OUTPUT_QUALIFICATION_UNAVAILABLE'):
        bench.require_output_qualification(_titan_output_proof(tmp_path, 'img', method=method))


@pytest.mark.parametrize('change', [
    {'schema': 'other'}, {'image_sha256': 'different-image'}, {'off_product': False}, {'method': 'owner-strip'},
    {'lanes_verified': ['A']}, {'frames_completed': 10}, {'frames_completed': '200'}, {'stuck_high_detected': True},
    {'stuck_high_detected': None}])
def test_titan_output_proof_refuses_every_weakened_proof(tmp_path, change):
    with pytest.raises(RuntimeError):
        bench.require_output_qualification(_titan_output_proof(tmp_path, 'img', **change))


def test_titan_output_proof_refuses_missing_or_changed_evidence(tmp_path):
    with pytest.raises(RuntimeError):
        bench.require_output_qualification({'image': {'sha256': 'img'}})
    m = _titan_output_proof(tmp_path, 'img'); (tmp_path / 'loopback.csv').write_text('edited')
    with pytest.raises(RuntimeError):
        bench.require_output_qualification(m)


def test_titan_native_flash_without_output_proof_never_reaches_hardware(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bench, 'validate_manifest', lambda cfg, facts: ({'image': {'sha256': 'img'}}, tmp_path, tmp_path / 'titan-native.hex', 'titan'))
    monkeypatch.setattr(bench, 'authorise', lambda m, backend, write: {})
    monkeypatch.setattr(bench.subprocess, 'run', lambda *a, **k: calls.append(a))
    cfg = {'action': 'bench-trial-flash', 'lane': 'titan', 'target': 'titan-native'}
    with pytest.raises(RuntimeError, match='output_qualification'):
        bench.execute(cfg, SimpleNamespace(run_dir=tmp_path, logs_dir=tmp_path), {})
    assert calls == []


@pytest.fixture
def known_donor_recovery(tmp_path, monkeypatch):
    image = tmp_path / 'donor.hex'
    image.write_text('explicit emulated donor recovery bytes')
    derivation = tmp_path / 'derivation.json'
    derivation.write_text(json.dumps({'schema': 'titan.recovery.inrange/1',
            'derived_sha256': bench.sha(image), 'build_id': bench.TITAN_RECOVERY_BUILD}))
    receipt = tmp_path / 'executed.json'
    receipt.write_text(json.dumps({'ok': True, 'steps': [{'result': {'evidence': [{'facts': {
            'identity': bench.TITAN_RECOVERY_UID, 'invoked_image_sha256': bench.sha(image),
            'programmed': True, 'tool_exit_verified': True}}]}}]}))
    # Test-only pins for explicit emulator files, never deployed policy changes.
    monkeypatch.setattr(bench, 'TITAN_RECOVERY_HEX_SHA256', bench.sha(image))
    monkeypatch.setattr(bench, 'TITAN_RECOVERY_DERIVATION_SHA256', bench.sha(derivation))
    monkeypatch.setattr(bench, 'TITAN_RECOVERY_RECEIPT_SHA256', bench.sha(receipt))
    return {'identity': bench.TITAN_RECOVERY_UID, 'recovery': {
            'image': bound(image), 'derivation': bound(derivation), 'qualification_receipt': bound(receipt)}}


def test_recovery_exemption_is_only_exact_known_donor(known_donor_recovery):
    result = bench.require_titan_recovery(known_donor_recovery)
    assert result['image_sha256'] == bench.TITAN_RECOVERY_HEX_SHA256


@pytest.mark.parametrize('fault', ['candidate', 'uid', 'derivation', 'receipt'])
def test_recovery_cannot_disguise_candidate_or_unsupported_receipt(known_donor_recovery, tmp_path, fault):
    m = known_donor_recovery
    if fault == 'uid':
        m['identity'] = 'other'
    else:
        path = tmp_path / 'replacement'
        path.write_text('new candidate or arbitrary evidence, not the known donor')
        key = {'candidate': 'image', 'derivation': 'derivation', 'receipt': 'qualification_receipt'}[fault]
        m['recovery'][key] = bound(path)
    with pytest.raises(RuntimeError):
        bench.require_titan_recovery(m)


def test_candidate_disguised_as_recovery_never_queries_owner_or_invokes_hardware(tmp_path, monkeypatch):
    image = tmp_path / 'candidate.hex'
    image.write_text('candidate')
    m = {'identity': bench.TITAN_RECOVERY_UID, 'recovery': {'image': bound(image)}}
    monkeypatch.setattr(bench, 'validate_manifest', lambda cfg, facts: (m, tmp_path, image, 'titan'))
    never = Mock(side_effect=AssertionError('Invalid recovery touched hardware'))
    monkeypatch.setattr(bench, 'authorise', never)
    monkeypatch.setattr(bench.subprocess, 'run', never)
    with pytest.raises(RuntimeError, match='exact known donor'):
        bench.execute({'action': 'bench-trial-recover'}, SimpleNamespace(logs_dir=tmp_path, run_dir=tmp_path), {})
    never.assert_not_called()
