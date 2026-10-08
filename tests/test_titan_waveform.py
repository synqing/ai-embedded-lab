"""Synthetic verifier tests. None of these files is physical qualification."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ael import titan_waveform as wave, titan_capture as capture
from ael.adapters import prism_bench_trial as bench


def fixture_capture(count=100, diagnostic=False):
    # Independent stimulus uses durations internal to the published intervals,
    # not production transmitter constants: period1300ns, highs260/700ns.
    expected=[[],[]]; events={0:[0,0]}; t=400000
    for f in range(count):
        for lane in range(2):
            payload=bytes(((i*31+f*17+lane*91)&255) for i in range(480))
            if diagnostic: payload=wave.diagnostic_payload(f,lane)
            expected[lane].append(payload)
            for b in range(3840):
                value=(payload[b//8]>>(7-b%8))&1
                rise=t+b*1300; fall=rise+(700 if value else 260)
                events.setdefault(rise,[None,None])[lane]=1
                events.setdefault(fall,[None,None])[lane]=0
        t+=3840*1300+400000
    events[t]=[0,0]
    state=[0,0]; lines=['TITAN-EDGES-1']
    for t,changes in sorted(events.items()):
        state=[state[i] if changes[i] is None else changes[i] for i in (0,1)]
        lines.append(f'{t},{state[0]},{state[1]}')
    return ('\n'.join(lines)+'\n').encode(),expected


@pytest.fixture(scope='module')
def valid(): return fixture_capture()


def independent_oracle(raw):
    # Independent byte-level reference scanner, no production parsing/segmentation.
    # Consume ordered rows, derive high runs, split frames at >280us silence.
    samples=[]
    for row in raw.split(b'\n')[1:]:
        if row:
            fields=row.split(b',')
            samples.append(tuple(int(x) for x in fields))
    out=[]
    for col in (1,2):
        rising=[r[0] for a,r in zip(samples,samples[1:]) if a[col]==0 and r[col]==1]
        falling=[r[0] for a,r in zip(samples,samples[1:]) if a[col]==1 and r[col]==0]
        assert len(rising)==len(falling)
        frames=[]; bits=''
        for i,(a,b) in enumerate(zip(rising,falling)):
            if i and a-falling[i-1]>280000:
                frames.append(int(bits,2).to_bytes(len(bits)//8,'big')); bits=''
            bits+='1' if b-a>400 else '0'
        frames.append(int(bits,2).to_bytes(len(bits)//8,'big'))
        out.append(frames)
    return out


def test_full_two_lane_raw_verification_and_independent_order_oracle(valid):
    raw,expected=valid
    assert independent_oracle(raw)==expected
    result=wave.verify_raw(raw,expected,5)
    assert [x['frames'] for x in result['lanes']]==[100,100]
    assert result['measured_waveform_pass'] and not result['physical_qualification']
    assert result['raw_sha256']==hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('raw',[b'',b'timestamp,A,B\n0,0,0\n120,0,0\n',
 b'TITAN-EDGES-1\n0,0,0\n1,0,0\n2,0,0\n',
 b'TITAN-EDGES-1\n0,0,0\n1,1,0\n1,0,0\n',
 b'TITAN-EDGES-1\n0,0,0\n1,1,0\n2,1,0\n',
 b'TITAN-EDGES-1\n0,0,0\nNaN,1,0\n3,0,0\n',
 b'TITAN-EDGES-1\n0,0,0\n1,2,0\n3,0,0\n'])
def test_malformed_never_becomes_declared_frames(raw):
    with pytest.raises(RuntimeError): wave.parse_edges(raw)


@pytest.mark.parametrize('fault',['one_lane','truncated','extra','missing','high','low','period','payload','swap','order','reset','terminal','initial'])
def test_raw_faults(valid,fault):
    raw,expected=valid
    if fault in ('payload','swap','order'):
        expected=copy.deepcopy(expected)
        if fault=='payload': expected[0][0]=bytes(480)
        if fault=='swap': expected=expected[::-1]
        if fault=='order': expected[0]=expected[0][::-1]
    else:
        rows=[list(x) for x in wave.parse_edges(raw)]
        if fault=='one_lane':
            rows=[x for i,x in enumerate(rows) if i==0 or i==len(rows)-1 or x[1]!=rows[i-1][1]]
            for x in rows: x[2]=0
        if fault=='truncated': rows=rows[:-10]
        if fault=='extra': rows.insert(-1,[rows[-1][0]-1000,1,1]); rows.insert(-1,[rows[-1][0]-500,0,0])
        if fault=='missing': del rows[1:4]
        if fault=='high': rows[2][0]=rows[1][0]+100
        if fault=='low': rows[4][0]+=180
        if fault=='period': rows[4][0]-=100
        if fault=='reset':
            for x in rows:
                if x[0]>=5792000: x[0]-=200000
        if fault=='terminal': rows[-1][0]=rows[-2][0]+100
        if fault=='initial': rows[1][0]=100
        raw=('TITAN-EDGES-1\n'+'\n'.join(','.join(map(str,x)) for x in rows)+'\n').encode()
    with pytest.raises(RuntimeError): wave.verify_raw(raw,expected)


@pytest.mark.parametrize('v',[float('nan'),float('inf'),-1,11,True,'1'])
def test_bad_timebase(valid,v):
    with pytest.raises(RuntimeError): wave.verify_raw(*valid,v)


def test_esp_parser_independent_big_endian_and_no_truncation():
    raw=b'\x00\x01\x02\x80\xff'
    status,words=wave.parse_esp32jtag_instant(raw)
    assert status==0 and words==[258,33023]
    assert words==[(raw[i]<<8)+raw[i+1] for i in range(1,len(raw),2)]
    with pytest.raises(RuntimeError): wave.parse_esp32jtag_instant(raw+b'\x00')


def test_isolated_action_refuses_before_any_hardware(tmp_path,monkeypatch):
    m={'isolated_qualification':{'operation':'titan-isolated-waveform-v1','backend':'esp32jtag-instant-v1',
       'isolated':True,'detector_ready':True,'physical_evidence':{'claimed':True}}}
    monkeypatch.setattr(bench,'validate_manifest',lambda cfg,facts:(m,tmp_path,tmp_path/'candidate.hex','titan'))
    forbidden=Mock(side_effect=AssertionError('hardware reached'))
    monkeypatch.setattr(bench,'authorise',forbidden)
    monkeypatch.setattr(bench.subprocess,'run',forbidden)
    with pytest.raises(RuntimeError,match='BLOCKED_CAPTURE_CAPABILITY'):
        bench.execute({'action':'bench-trial-qualify-isolated'},SimpleNamespace(logs_dir=tmp_path),{})
    forbidden.assert_not_called()


@pytest.mark.parametrize('backend',['esp32jtag-instant-v1','esp32-meter-v1','pin-loopback','unknown'])
def test_declarations_cannot_create_ready_backend(backend):
    with pytest.raises(RuntimeError,match='BLOCKED_CAPTURE_CAPABILITY'):
        capture.isolated_preflight({'isolated_qualification':{'operation':'titan-isolated-waveform-v1','backend':backend}})


def test_status_only_known_readonly_endpoints(monkeypatch):
    calls=[]
    def get(url,**kw):
        calls.append(url)
        return SimpleNamespace(status_code=200,raise_for_status=lambda:None,json=lambda:{'observed':'test mock'})
    monkeypatch.setattr(capture.requests,'get',get)
    out=capture.read_only_status('https://instrument.invalid')
    assert calls==['https://instrument.invalid/api/version','https://instrument.invalid/la_status']
    assert out['physical_readiness'] is False


def test_manifest_wrong_uid_and_stale_program_event(tmp_path):
    m={'schema':'prism.titan.capture.v1','identity':'wrong'}
    with pytest.raises(RuntimeError,match='UID'): wave.verify_manifest(m)
    event={'identity':wave.UID,'image_sha256':'a'*64,'source_binding_hash':'b'*64,'readback_sha256':'a'*64,
           'readback_verified':True,'completed_unix':100}
    f=tmp_path/'event.json'; f.write_text(json.dumps(event))
    m.update(identity=wave.UID,image_sha256='a'*64,source_binding_hash='b'*64,source_commit='c'*40,
       build_receipt_sha256='d'*64,physical_pins={'A':'P601','B':'P604'},requirements=wave.REQUIREMENTS,
       programming_event={'path':str(f),'sha256':wave.digest(f.read_bytes())},acquisition_unix=[90,91],
       pattern_set='pattern-set-v1',host_clock_uncertainty_ns=1000)
    for key in ('fixture_witness','instrument_status','acquisition_settings','fitted_part_evidence'):
        m[key]={'path':str(f),'sha256':wave.digest(f.read_bytes())}
    with pytest.raises(RuntimeError,match='Stale'): wave.verify_manifest(m)
    m['image_sha256']='e'*64
    with pytest.raises(RuntimeError,match='binding'): wave.verify_manifest(m)


def test_diagnostic_patterns_cover_boundaries_and_lanes():
    assert wave.diagnostic_payload(0,0)==bytes(480)
    assert wave.diagnostic_payload(1,1)==bytes([255])*480
    assert wave.diagnostic_payload(2,0)==bytes([0xaa])*480
    assert wave.diagnostic_payload(2,1)==bytes([0x55])*480
    assert {(wave.diagnostic_payload(f,0)[0]>>7,wave.diagnostic_payload(f,0)[-1]&1) for f in range(3,7)}=={(0,0),(0,1),(1,0),(1,1)}
    assert wave.diagnostic_payload(3,0)!=wave.diagnostic_payload(3,1)



def test_manifest_candidate_identity_and_record_mutations(tmp_path):
    import time
    witness=tmp_path/'witness';witness.write_text('SYNTHETIC TEST ONLY')
    row={'path':str(witness),'sha256':wave.digest(witness.read_bytes())}
    end=time.time()-1
    event={'identity':wave.UID,'image_sha256':'a'*64,'source_binding_hash':'b'*64,
           'readback_sha256':'a'*64,'readback_verified':True,'completed_unix':end-2}
    f=tmp_path/'program';f.write_text(json.dumps(event))
    m={'schema':'prism.titan.capture.v1','identity':wave.UID,'image_sha256':'a'*64,
       'source_binding_hash':'b'*64,'source_commit':'c'*40,'build_receipt_sha256':'d'*64,
       'physical_pins':{'A':'P601','B':'P604'},'requirements':wave.REQUIREMENTS,
       'programming_event':{'path':str(f),'sha256':wave.digest(f.read_bytes())},
       'acquisition_unix':[end-1,end],'pattern_set':'pattern-set-v1','host_clock_uncertainty_ns':1000}
    for key in ('fixture_witness','instrument_status','acquisition_settings','fitted_part_evidence'):m[key]=row
    candidate={'identity':wave.UID,'image':{'sha256':'a'*64},'source_commit':'c'*40,
               'source_binding_hash':'b'*64,'build_receipt':{'sha256':'d'*64}}
    for field in ('image_sha256','source_binding_hash','source_commit','build_receipt_sha256'):
        bad=copy.deepcopy(m);bad[field]='e'*len(bad[field])
        with pytest.raises(RuntimeError,match='mismatch'):wave.verify_manifest(bad,candidate)
    bad=copy.deepcopy(m);bad['requirements']['t0h_ns'][1]=1000
    # Compare to independently frozen copy, not a mutable imported singleton.
    assert bad['requirements']!=wave.REQUIREMENTS
    with pytest.raises(RuntimeError,match='frozen'):wave.verify_manifest(bad)
    m['acquisition_unix']=[end-90000,end-89999]
    event['completed_unix']=end-90001;f.write_text(json.dumps(event));m['programming_event']['sha256']=wave.digest(f.read_bytes())
    with pytest.raises(RuntimeError,match='Stale'):wave.verify_manifest(m)


def test_real_cli_redecodes_full_synthetic_capture_without_physical_admission(tmp_path):
    import subprocess
    import sys
    import time
    raw,expected=fixture_capture(diagnostic=True)
    def file(name,data):
        f=tmp_path/name;f.write_bytes(data)
        return {'path':str(f),'sha256':wave.digest(data)}
    witness=file('synthetic-witness',b'SYNTHETIC TEST ONLY; no instrument')
    end=time.time()-2;duration=wave.parse_edges(raw)[-1][0]/1e9
    event={'identity':wave.UID,'image_sha256':'a'*64,'source_binding_hash':'b'*64,
           'readback_sha256':'a'*64,'readback_verified':True,'completed_unix':end-duration-1}
    m={'schema':'prism.titan.capture.v1','identity':wave.UID,'image_sha256':'a'*64,
       'source_binding_hash':'b'*64,'source_commit':'c'*40,'build_receipt_sha256':'d'*64,
       'physical_pins':{'A':'P601','B':'P604'},'requirements':wave.REQUIREMENTS,
       'programming_event':file('event',json.dumps(event).encode()),
       'acquisition_unix':[end-duration,end],'pattern_set':'pattern-set-v1','host_clock_uncertainty_ns':1000,
       'raw':file('raw.edges',raw),'expected_payload':file('expected.bin',b''.join(expected[l][f] for f in range(100) for l in (0,1))),
       'edge_uncertainty_ns':5,'origin':'synthetic-test','backend':'esp32jtag-instant-v1'}
    for key in ('fixture_witness','instrument_status','acquisition_settings','fitted_part_evidence'):m[key]=witness
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(m));out=tmp_path/'verdict.json'
    run=subprocess.run([sys.executable,'-m','ael.titan_waveform','--manifest',str(manifest),'--output',str(out)],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr
    result=json.loads(out.read_text());assert result['measured_waveform_pass'] and not result['physical_qualification']
    assert [x['frames'] for x in result['lanes']]==[100,100]
    proof={'schema':'prism.titan.output-qualification.v2','capture_manifest':{'path':str(manifest),'sha256':wave.digest(manifest.read_bytes())}}
    candidate={'identity':wave.UID,'image':{'sha256':'a'*64},'source_commit':'c'*40,'source_binding_hash':'b'*64,'build_receipt':{'sha256':'d'*64}}
    with pytest.raises(RuntimeError,match='Synthetic'):capture.consume_output_proof(candidate,proof)
    m['origin']='physical-acquisition';manifest.write_text(json.dumps(m));proof['capture_manifest']['sha256']=wave.digest(manifest.read_bytes())
    with pytest.raises(RuntimeError,match='BLOCKED_CAPTURE_CAPABILITY'):capture.consume_output_proof(candidate,proof)
