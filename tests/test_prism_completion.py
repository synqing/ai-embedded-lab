import hashlib
import json
import struct
import pytest
from ael.prism_completion import (prepare,decode_probe,decode_cost,cost_delta,advancement,
                                  require_healthy,execute,PROBE,COST,PREAMBLE,Refusal)

def binding(path):
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def golden(tmp_path):
    pcm=tmp_path/'pcm.s16le';pcm.write_bytes(bytes(256))
    ref=tmp_path/'reference.jsonl'
    ref.write_text('\n'.join(json.dumps(r) for r in [
        {'schema':'titan-level-trace.v1','sample_rate':12800,'hop_samples':64,'percussion_proxy_h_sha256':'a'*64},
        {'hop':0,'core_valid':True,'d_raw':0.,'d_level':0.},
        {'hop':1,'core_valid':True,'d_raw':0.,'d_level':0.}]))
    return {'kind':'golden','trial':1,'pcm':binding(pcm),'reference':binding(ref),
            'reference_pcm_sha256':binding(pcm)['sha256'],'proxy_source_sha256':'a'*64}

def info():
    return dict(uid='545433931bd25436593630352d068363',boot_id=7,build_source_sha256='b'*64,
                schema_sha256='c'*64,clock_hz=1000000000,initialisation_failed=False,
                output_timeouts=0,capture_errors=[0,0],output_last_fsp_error=0,
                capture_clock_rejections=0,capture_restart_attempts=0,output_recovery_attempts=0)

def test_preparation_rejects_changed_pcm(tmp_path):
    s=golden(tmp_path);assert len(prepare(s)['expected'])==2
    (tmp_path/'pcm.s16le').write_bytes(bytes(128))
    with pytest.raises(Refusal):prepare(s)

@pytest.mark.parametrize('key,value',[('reference_pcm_sha256','0'*64),('proxy_source_sha256','0'*64),('trial',0),('trial',True)])
def test_prepare_rejects_identity(tmp_path,key,value):
    s=golden(tmp_path);s[key]=value
    with pytest.raises(Refusal):prepare(s)

@pytest.mark.parametrize('change',[{'hop':3},{'d_raw':float('nan')},{'core_valid':False}])
def test_golden_invalid_rows(tmp_path,change):
    s=golden(tmp_path);p=tmp_path/'reference.jsonl';rows=[json.loads(x) for x in p.read_text().splitlines()]
    rows[1].update(change);p.write_text('\n'.join(json.dumps(x) for x in rows));s['reference']=binding(p)
    with pytest.raises(Refusal):prepare(s)

@pytest.mark.parametrize('seconds',[0,121,float('inf'),True])
def test_measure_bounds(seconds):
    with pytest.raises(Refusal):prepare({'kind':'measure','seconds':seconds,'live_source':'D','observer_enabled':True})

def test_probe_exact_wire_vector():
    # Format oracle is Python standard struct; firmware uses its independent LE writer.
    body=bytes.fromhex('01000000020000000100000000320000')+struct.pack('<8f',1,2,3,4,5,6,7,8)
    assert decode_probe(body,1,2,True)['d_level']==8
    for bad in (body[:-1],body+b'\0',bytes(48)):
        with pytest.raises(Refusal):decode_probe(bad,1,2,True)
    with pytest.raises(Refusal):decode_probe(body,2,2,True)
    with pytest.raises(Refusal):decode_probe(body[:44]+struct.pack('<f',float('inf')),1,2,True)

def cost(samples,stage=3):
    # Independent bin construction from intervals, not production index routine.
    hist=[0]*256
    for x in samples:
        if x<8:hist[x]+=1
        else:
            for exponent in range(3,32):
                if 2**exponent<=x<2**(exponent+1):
                    for sub in range(8):
                        if 2**exponent+sub*2**(exponent-3)<=x<2**exponent+(sub+1)*2**(exponent-3):hist[exponent*8+sub]+=1
    return struct.pack('<IIQQIIII256I',stage,1000000000,len(samples),sum(samples),max(samples,default=0),0,256,1,*hist)

def test_cost_quantile_boundaries():
    b=decode_cost(cost([]),3);a=decode_cost(cost([0,7,8,9,15,16,1000,0xffffffff]),3)
    d=cost_delta(b,a);assert d['count']==8
    assert d['p50_us_interval']==pytest.approx([.009,.009])
    assert d['p99_us_interval'][0]<=0xffffffff/1000<=d['p99_us_interval'][1]
    with pytest.raises(Refusal):cost_delta(a,b)

@pytest.mark.parametrize('offset,value',[(0,4),(4,0),(8,99),(24,999),(28,1),(32,128),(36,0),(40+4*8,1)])
def test_cost_corruption(offset,value):
    b=bytearray(cost([1,8,16]));struct.pack_into('<I',b,offset,value)
    with pytest.raises(Refusal):decode_cost(bytes(b),3)

def test_health_preserves_boot_and_faults():
    base=info();require_healthy(base,base)
    for k,v in [('boot_id',8),('output_timeouts',1),('capture_errors',[1,0]),('capture_clock_rejections',1)]:
        changed=dict(base);changed[k]=v
        with pytest.raises(Refusal):require_healthy(changed,base)

def test_actual_golden_flow_and_corruption(tmp_path):
    s=golden(tmp_path);build=tmp_path/'build.json';build.write_text(json.dumps({'inputs':{'lane':{'platform/titan/percussion_proxy.h':'a'*64}}}))
    m={'build_receipt':binding(build)};calls=[]
    def exchange(op,p=b'', **transport_limits):
        calls.append(op)
        if op==1:return json.dumps(info()).encode()
        if op==PREAMBLE:return b'{}'
        assert op==PROBE
        boot,action,trial,seq,rate,n=struct.unpack_from('<6I',p)
        assert boot==7 and rate==12800 and len(p)==24+2*n
        return struct.pack('<4I8f',trial,seq+(action==1),action!=2,12800,*([0.]*8))
    result=execute(exchange,m,s,tmp_path,info());assert result['hops']==2
    assert calls.count(PROBE)==4
    bad=tmp_path/'bad';bad.mkdir()
    def corrupt(op,p=b'',**transport_limits):
        result=exchange(op,p)
        if op==PROBE and struct.unpack_from('<I',p,4)[0]==1:return result[:44]+struct.pack('<f',.2)
        return result
    with pytest.raises(Refusal,match='golden mismatch'):execute(corrupt,m,s,bad,info())
    assert 'failure' in (bad/'titan-completion.jsonl').read_text()

def test_ratings_never_fabricate_missing_votes():
    assert advancement([])['decision']=='AWAITING_OWNER_REVIEW'
    rows=[dict(song=str(i),reviewer='Captain',compared_against='I',physical_evidence='bound-clip',musical_relationship='candidate',overall_appearance='candidate',severe_artifact_regression=False) for i in range(3)]
    rows[2]['overall_appearance']='tie';assert advancement(rows)['decision']=='ADVANCE_ELIGIBLE'
    rows[2]['severe_artifact_regression']=True;assert advancement(rows)['decision']=='RETAIN_DONOR'
    rows[2]['severe_artifact_regression']=False;rows[1]['musical_relationship']='tie';assert advancement(rows)['decision']=='RETAIN_DONOR'
    rows[0]['compared_against']='A';assert advancement(rows)['decision']=='AWAITING_OWNER_REVIEW'


def test_golden_outer_deadline_retains_rows_and_stops_next_exchange(tmp_path):
    spec = golden(tmp_path)
    build = tmp_path/'build.json'; build.write_text(json.dumps({'inputs':{'lane':{'platform/titan/percussion_proxy.h':'a'*64}}}))
    clock = [0.]; hops = []
    def exchange(op,p=b'', **transport_limits):
        if op == PREAMBLE: return b'{}'
        if op == PROBE:
            boot,action,trial,seq,rate,n = struct.unpack_from('<6I',p)
            if action == 1:
                hops.append(seq); clock[0] += .6
            return struct.pack('<4I8f',trial,seq+(action==1),action!=2,12800,*([0.]*8))
        raise AssertionError('Unexpected exchange')
    with pytest.raises(Refusal, match='absolute deadline'):
        execute(exchange, {'build_receipt':binding(build)}, spec, tmp_path, info(),
                monotonic=lambda:clock[0], deadline=1.)
    rows = [json.loads(x) for x in (tmp_path/'titan-completion.jsonl').read_text().splitlines()]
    assert hops == [0,1]
    assert [row['hop'] for row in rows if row['event']=='golden'] == [0]
    assert rows[-1]['event'] == 'failure'
