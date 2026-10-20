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
        return SimpleNamespace(returncode=1 if argv[0]=='lsof' else 0,stdout='',stderr='')
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
    struct.pack_into('<HH',body,4,1,25)
    source='ab'*32
    body[728:744]=bytes.fromhex(native.UID);body[744:776]=bytes.fromhex(source);body[776:808]=bytes.fromhex(native.SCHEMA)
    struct.pack_into('<Q',body,8,45);struct.pack_into('<Q',body,32,225000)
    struct.pack_into('<Q',body,48,2880);struct.pack_into('<f',body,96,.75)
    decoded=native.snapshot(body,source)
    assert decoded['generation']==45 and decoded['pcm_peak']==.75 and decoded['sample_end']==2880
    assert decoded['capture_valid'] is True and decoded['warming'] is False and decoded['stale'] is False
    assert decoded['flags']==25 and decoded['last_invalidate_reason_name']=='None'
    body[744]^=1
    with pytest.raises(ValueError):native.snapshot(body,source)


@pytest.mark.parametrize('flags,valid,warming,stale',[(25,True,False,False),(26,False,True,False),(30,False,True,True)])
def test_snapshot_actual_schema_validity_and_persistent_reason(flags,valid,warming,stale):
    body=bytearray(1184)
    struct.pack_into('<IHH',body,0,0x53564C54,1,flags)
    body[728:744]=bytes.fromhex(native.UID)
    body[744:776]=bytes.fromhex('ab'*32)
    body[776:808]=bytes.fromhex(native.SCHEMA)
    struct.pack_into('<Q',body,32,1000000)  # Nonzero time never replaces flags.
    struct.pack_into('<I',body,616,0x50520005)
    decoded=native.snapshot(body,'ab'*32)
    assert (decoded['capture_valid'],decoded['warming'],decoded['stale'])==(valid,warming,stale)
    assert decoded['last_invalidate_reason']==0x50520005
    assert decoded['last_invalidate_reason_name']=='RingOverwrite'
    assert decoded['physical_timestamp_valid'] is False
    for offset,value in ((4,2),(6,0),(6,27),(6,57)):
        corrupt=bytearray(body);struct.pack_into('<H',corrupt,offset,value)
        with pytest.raises(ValueError,match='version/flags'):native.snapshot(corrupt,'ab'*32)


def test_snapshot_differential_decode_retained_device_corpus():
    # Independent byte-slice interpretation of the original firmware encoder,
    # compared in emitted order over the retained failed device transaction.
    # The raw acquisition remains local evidence, never manufactured by this test.
    import base64
    source=Path('/Users/spectrasynq/ai-embedded-lab/_scratch/titan-completion-20261008/r2-repair-cost-d-off-20/logs/titan-native.jsonl')
    if not source.is_file():pytest.skip('Retained local Titan raw device corpus unavailable')
    seen=[]
    for row in map(json.loads,source.read_text().splitlines()):
        if row['opcode']!=23 or not row.get('response_complete'):continue
        packet=base64.b64decode(row['response'])
        body=native.response(packet,row['sequence'],0x50524953)
        oracle_flags=int.from_bytes(body[6:8],'little')
        oracle_reason=int.from_bytes(body[616:620],'little')
        decoded=native.snapshot(body,body[744:776].hex())
        actual=(decoded['flags'],decoded['capture_valid'],decoded['warming'],decoded['stale'],
                decoded['last_invalidate_reason'],decoded['epoch'],decoded['capture_time_us'],decoded['sample_end'])
        independent=(oracle_flags,oracle_flags%2==1,(oracle_flags//2)%2==1,(oracle_flags//4)%2==1,
            oracle_reason,int.from_bytes(body[16:24],'little'),int.from_bytes(body[32:40],'little'),int.from_bytes(body[48:56],'little'))
        assert actual==independent
        seen.append(actual)
    assert len(seen)==2 and [r[5] for r in seen]==[0,33]
    assert all(not r[1] and r[4]==0x50520005 for r in seen)


def test_capture_queue_frozen_witness_and_stage_attribution():
    body=bytearray(1536)
    struct.pack_into('<10I',body,0,0x51544C54,1,1536,1000000000,22,20,2,4,41431,1)
    struct.pack_into('<4Q',body,40,2,17,1,20)
    struct.pack_into('<Q',body,72,55330)
    struct.pack_into('<5I',body,80,1,2,1,2,33)
    struct.pack_into('<I',body,100,1)
    struct.pack_into('<Q',body,104,100500)
    struct.pack_into('<9I',body,112,123,18,1,41431,1,1,9,1,9)
    struct.pack_into('<QQII',body,208+24,1,55330000,55330000,0)
    struct.pack_into('<Q6I',body,472,99990,55330000,55330000,1,18,1,1)
    struct.pack_into('<Q6I',body,504,100500,4000000,1000000,2,22,20,2)
    struct.pack_into('<Q6I',body,984,99990,55330000,55330000,1,18,1,1)
    decoded=native.capture_queue(bytes(body))
    assert decoded['overwrite_events']==2 and decoded['dropped_blocks']==17 and decoded['copy_races']==1
    assert decoded['longest_consumption_gap_us']==55330 and decoded['longest_gap_end_visit_backlog']==1
    assert decoded['longest_gap_observation'] is None
    assert decoded['first_fault_valid']==1 and decoded['first_producer']==18 and decoded['first_consumer']==1
    assert decoded['history'][0]['stage']=='coefficients' and decoded['history'][1]['stage']=='resample_excluding_hops'
    assert decoded['first_history']==decoded['history'][:1]
    assert decoded['history_overwritten']==33 and decoded['first_history_overwritten']==9
    assert decoded['stages'][1]['maximum_cycles']==55330000
    for offset,value in ((0,0),(4,2),(8,1535),(24,3),(28,1),(84,11),(92,17),(100,2),(140,17),(484,55330001)):
        corrupt=bytearray(body);struct.pack_into('<I',corrupt,offset,value)
        with pytest.raises(ValueError):native.capture_queue(bytes(corrupt))


def test_capture_queue_version2_endpoints_are_not_dma_phase():
    body=bytearray(1536)
    struct.pack_into('<10I',body,0,0x51544C54,2,1536,1000000000,3,3,0,3,41431,1)
    struct.pack_into('<Q',body,72,8403)
    struct.pack_into('<I',body,80,1)
    struct.pack_into('<IQQ5I',body,1496,0x47415031,3000,11403,2,3,3,2,3)
    decoded=native.capture_queue(bytes(body))
    assert decoded['schema']=='prism.titan.capture-queue.v2'
    assert decoded['longest_gap_end_visit_backlog']==1
    assert 'longest_gap_start_backlog' not in decoded
    assert decoded['longest_gap_observation']==dict(previous_consumed_us=3000,
        ending_consumed_us=11403,previous_visit_backlog=2,ending_visit_backlog=1,
        previous_producer=3,ending_producer=3,previous_consumer=2,ending_consumer=3)
    assert 'DMA_PHASE_UNMEASURED' in decoded['gap_time_scope']
    for offset,value,format in ((80,7,'<I'),(1496,0,'<I'),(1500,0,'<Q'),(1508,3000,'<Q'),(1508,11404,'<Q'),(1516,7,'<I')):
        corrupt=bytearray(body);struct.pack_into(format,corrupt,offset,value)
        with pytest.raises(ValueError):native.capture_queue(bytes(corrupt))
    struct.pack_into('<Q',body,72,0)
    with pytest.raises(ValueError):native.capture_queue(bytes(body))
    body[1496:]=bytes(40)
    assert native.capture_queue(bytes(body))['longest_gap_observation'] is None


def test_capture_queue_version2_zero_timestamp_is_valid_endpoint():
    body=bytearray(1536)
    struct.pack_into('<10I',body,0,0x51544C54,2,1536,1000000000,2,2,0,2,41431,1)
    struct.pack_into('<Q',body,72,8403)
    struct.pack_into('<I',body,80,1)
    struct.pack_into('<IQQ5I',body,1496,0x47415031,0,8403,1,2,2,1,2)
    decoded=native.capture_queue(bytes(body))
    assert decoded['longest_consumption_gap_us']==8403
    assert decoded['longest_gap_observation']==dict(previous_consumed_us=0,
        ending_consumed_us=8403,previous_visit_backlog=1,ending_visit_backlog=1,
        previous_producer=2,ending_producer=2,previous_consumer=1,ending_consumer=2)


def test_window_rejects_invalid_metadata_source_change_and_counter_wrap():
    first=dict(epoch=1,capture_valid=True,warming=False,stale=False,source_rate=41431,
        source_binding='ab'*32,capture_time_us=1000000,sample_end=12800,hops=200,
        rejected_hops=0,logical_frame=120)
    last={**first,'capture_time_us':2000000,'sample_end':25600,'hops':400,'logical_frame':220}
    for change in ({'capture_valid':False},{'stale':True},{'warming':True},{'source_rate':41430},
                   {'source_binding':'cd'*32},{'hops':0},{'logical_frame':0},{'rejected_hops':-1}):
        with pytest.raises(ValueError):native.window(first,{**last,**change})


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

import os
import tempfile
import unittest
from unittest import mock

def recovery_test_fixture():
    """AEL_TITAN_RECOVERY_FIXTURE selects immutable rows; mutations use per-test temp."""
    config = os.environ.get('AEL_TITAN_RECOVERY_FIXTURE')
    required = os.environ.get('AEL_TITAN_RECOVERY_FIXTURE_REQUIRED') == '1'
    if not config:
        if required:
            raise RuntimeError('Supplied recovery fixture is required')
        raise unittest.SkipTest('Optional immutable recovery fixture not configured')
    path = Path(config).resolve()
    if not path.is_file():
        raise RuntimeError('Configured recovery fixture is missing')
    data = json.loads(path.read_text())
    if data.get('schema') != 'titan.recovery.test-fixture.v1':
        raise RuntimeError('Wrong recovery test fixture schema')
    result = {}
    for branch in ['current', 'legacy']:
        result[branch] = {'identity':bench.TITAN_RECOVERY_UID, 'recovery':{}}
        for name, row in data[branch].items():
            f = (path.parent / row['path']).resolve()
            if not f.is_file() or bench.sha(f) != row['sha256']:
                raise RuntimeError('Missing/changed immutable recovery fixture: '+branch+'/'+name)
            result[branch]['recovery'][name] = {'path':str(f),'sha256':row['sha256']}
    return result

class TestCurrentRangeRecovery(unittest.TestCase):
    def setUp(self):
        self.m = copy.deepcopy(recovery_test_fixture()['current'])
        temporary = tempfile.TemporaryDirectory(prefix='ael-recovery-')
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)

    def test_genuine_source_coverage_equivalence(self):
        result = bench.require_titan_recovery(self.m)
        self.assertTrue(result['recovery_byte_equivalence_verified'])
        self.assertFalse(result['derived_image_programmed'])
        self.assertEqual(result['historical_source_verified_ranges'],[[0x02000000,0x02082720]])

    def test_original_full_image_is_not_admitted(self):
        self.m['recovery']['image'] = self.m['recovery']['source_image']
        with self.assertRaises(RuntimeError):
            bench.require_titan_recovery(self.m)

    def test_wrong_uid_is_refused(self):
        self.m['identity']='wrong'
        with self.assertRaisesRegex(RuntimeError,'UID'):
            bench.require_titan_recovery(self.m)

    def test_changed_bound_records_are_refused(self):
        for key in self.m['recovery']:
            with self.subTest(key=key):
                original=self.m['recovery'][key]
                path=self.tmp/('changed-'+key)
                path.write_bytes(Path(original['path']).read_bytes()+b'\n')
                self.m['recovery'][key]={'path':str(path),'sha256':bench.sha(path)}
                with self.assertRaises(RuntimeError):
                    bench.require_titan_recovery(self.m)
                self.m['recovery'][key]=original

    def test_derivation_semantics_fail_closed(self):
        cases=[('build_id','wrong'),('uid','wrong'),('source_pin','wrong'),
               ('in_range_bytes',534303),('range','all'),('dropped_records',[]),
               ('derived_image_programmed',True),('hardware_access',True),
               ('historical_verified_ranges',[[0x02000000,0x02082710]]),
               ('historical_source_programming_receipt_sha256','wrong')]
        original=self.m['recovery']['derivation']
        data=json.loads(Path(original['path']).read_text())
        for key,value in cases:
            with self.subTest(key=key):
                altered=dict(data);altered[key]=value
                path=self.tmp/'fault-derivation.json';path.write_text(json.dumps(altered))
                self.m['recovery']['derivation']={'path':str(path),'sha256':bench.sha(path)}
                with mock.patch.object(bench,'TITAN_CURRENT_RECOVERY_DERIVATION_SHA256',bench.sha(path)):
                    with self.assertRaises(RuntimeError):
                        bench.require_titan_recovery(self.m)
        self.m['recovery']['derivation']=original

    def test_original_receipt_semantics_fail_closed(self):
        cases=[('execute',False),('dry_run',True),('returncode',False),
               ('hex_sha256','wrong'),('range','all'),('flags',['-erase']),
               ('debug_mode','gdb'),('stdout','Operation successful')]
        original=self.m['recovery']['qualification_receipt']
        data=json.loads(Path(original['path']).read_text())
        for key,value in cases:
            with self.subTest(key=key):
                altered=dict(data);altered[key]=value
                path=self.tmp/'fault-programming.json';path.write_text(json.dumps(altered))
                self.m['recovery']['qualification_receipt']={'path':str(path),'sha256':bench.sha(path)}
                with mock.patch.object(bench,'TITAN_CURRENT_RECOVERY_RECEIPT_SHA256',bench.sha(path)):
                    with self.assertRaises(RuntimeError):
                        bench.require_titan_recovery(self.m)
        self.m['recovery']['qualification_receipt']=original

    def test_checksum_eof_overlap_and_address_validation(self):
        original=Path(self.m['recovery']['image']['path']).read_text()
        lines=original.splitlines()
        malformed={
            'checksum':lines[0][:-2]+'00\n'+'\n'.join(lines[1:])+'\n',
            'missing-eof':'\n'.join(lines[:-1])+'\n',
            'post-eof':original+':00000001FF\n',
            'overlap':'\n'.join([lines[0],lines[1],lines[1],*lines[2:]])+'\n',
            'address':':020001040200F7\n'+ '\n'.join(lines[1:])+'\n'}
        for key,text in malformed.items():
            with self.subTest(key=key):
                path=self.tmp/('malformed-'+key+'.hex');path.write_text(text)
                with self.assertRaises(RuntimeError):
                    bench.recovery_hex_bytes(path)
