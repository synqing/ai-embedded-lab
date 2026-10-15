"""Offline replacement observer tests. Generated edges are never device proof."""
import copy
import json
import struct
import time
import zlib

import pytest

from ael import titan_replacement_observer as observer, titan_loopback as loop
from ael.titan_waveform import diagnostic_payload, digest, UID
from test_titan_loopback import direct_fixture


def fixture(pattern=2, epoch=1):
    s, _, sof = direct_fixture(pattern)
    s.update(version=4, epoch=epoch, capacity=7712, ccr=1 << 16, mpu=1,
             dma_begin=0x22000000, dma_end=0x22040000, dma_rbar=0x22000000,
             dma_rlar=0x2203ffe1, dma_mair0=0x44,
             microphone_begin=0x22020000, microphone_end=0x22028000,
             led_begin=0x22028000, led_end=0x22030000,observer_timeout_us=50000,drain_max_words=1000,
             words_a=15360, words_b=15360, edges_a=15360, edges_b=15360)
    streams=[]
    for lane in (0, 1):
        prefix='b_' if lane else ''
        first=s[prefix+'stimulus_tick']
        # Independent array construction from full GRB48 bytes.
        bits=''.join(f'{byte:08b}' for byte in diagnostic_payload(pattern,lane,bytes_per_lane=960))
        rises=[(first+i*390)&0xffffffff for i in range(7680)]
        falls=[(t+(198 if bit=='1' else 78))&0xffffffff for t,bit in zip(rises,bits)]
        streams.extend([rises,falls])
        s[prefix+'trailing_begin']=falls[-1]
        s[prefix+'trailing_end']=(falls[-1]+120000)&0xffffffff
        s[prefix+'capture_end_tick']=(falls[-1]+120001)&0xffffffff
    for i,name in enumerate(loop.SPLIT_NAMES):
        base=0x22000000+i*0x8000
        s.update({'dma_'+name:i+4,'buffer_'+name:base,'destination_'+name:base+7680*4,
                  'words_'+name:7680,'remaining_'+name:32})
    return s, streams, sof


def packed(s):
    return struct.pack('<160I', *([s[k] for k in loop.STATUS_FIELDS]+[0]+
        [s[k] for k in loop.DIRECT_FIELDS]+[s[k] for k in observer.EXTENSION]+[0]))


def raw_streams(streams,sof):
    return [struct.pack('<'+'I'*len(x),*x) for x in streams+[sum(sof,[])]]


def info():
    return {'uid':UID,'contract':'titan-replacement-v1','source_id':'b'*64,
            'build_profile':'titan-replacement','core_commit':observer.CORE,'core_tag':'v0.12.0-rc.2',
            'scene_pixels':[160,160],'logical_hz':120,
            'capabilities':{'isolated_raw_capture':observer.BACKEND,'fixture_drain_max_words':1000}}


def manifest():
    return {'target':'titan-replacement','identity':UID,'source_binding_hash':'b'*64,
            'source_commit':'c'*40,'image':{'sha256':'a'*64},'build_receipt':{'sha256':'d'*64},
            'isolated_programming_event':{},'port':'/dev/cu.TEST-NO-HARDWARE',
            'isolated_qualification':{'frames':100,'backend':observer.BACKEND,'pattern':2}}


def test_full_geometry_and_independent_ordered_byte_oracle():
    for pattern in range(7):
        s,streams,sof=fixture(pattern)
        result=observer.verify_epoch(observer.status(packed(s),7,1),raw_streams(streams,sof),pattern)
        hashes=[]
        for lane in (0,1):
            # Independent integer reader and bit assembly, no production decoder.
            raw=raw_streams(streams,sof)
            values=[[int.from_bytes(r[i:i+4],'little') for i in range(0,len(r),4)] for r in raw[2*lane:2*lane+2]]
            bits=[int(((b-a)&0xffffffff)>130) for a,b in zip(*values)]
            payload=bytes(sum(bits[i+j] << (7-j) for j in range(8)) for i in range(0,len(bits),8))
            assert payload==diagnostic_payload(pattern,lane,bytes_per_lane=960)
            hashes.append(digest(payload))
        assert result['payload_sha256']==hashes and result['bits_each']==7680
        assert result['physical_qualification'] is False


@pytest.mark.parametrize('field,value', [('ccr',0),('mpu',0),('dma_mair0',0xff),
    ('dma_end',0x22000100),('dma_rlar',0x2201ffe0),('dma_a_rise',1),('dma_b_fall',3),
    ('buffer_b_fall',0x22000000),('capacity',3872),('words_b_fall',3840),
    ('remaining_a_rise',0),('b_final_low',0),('trailing_end',0),('first_fsp_error',1)])
def test_bad_setup_and_boundary_rejected(field,value):
    s,streams,sof=fixture();s[field]=value
    with pytest.raises(RuntimeError): observer.verify_epoch(observer.status(packed(s),7,1),raw_streams(streams,sof),2)


@pytest.mark.parametrize('fault',['half','tail','bit','swap','version','boot','epoch','size'])
def test_truncated_wrong_or_stale_raw_rejected(fault):
    s,streams,sof=fixture();raw=packed(s)
    if fault=='half':streams=[x[:3840] for x in streams]
    if fault=='tail':streams[3].pop()
    if fault=='bit':streams[1][-1]+=120
    if fault=='swap':streams[0],streams[2]=streams[2],streams[0]
    if fault=='version':s['version']=3
    if fault=='boot':s['boot']=8
    if fault=='epoch':s['epoch']=2
    raw=packed(s)
    if fault=='size':raw=raw[:-4]
    with pytest.raises(RuntimeError):observer.verify_epoch(observer.status(raw,7,1),raw_streams(streams,sof),2)


@pytest.mark.parametrize('key,value',[('source_id','wrong'),('build_profile','titan-native'),
    ('scene_pixels',[80,80]),('uid','wrong'),('core_commit','wrong'),('capabilities',{'firmware_fixture':False})])
def test_identity_refuses_before_stimulus(key,value):
    i=info();i[key]=value
    with pytest.raises(RuntimeError):observer.identity(i,manifest())


class Detector:
    def __init__(self):
        self.s,self.streams,self.sof=fixture();self.calls=[];self.drained=False
    def exchange(self,opcode,payload=b''):
        self.calls.append(opcode)
        if opcode==observer.IDENTITY:return json.dumps(info()).encode()
        if opcode==observer.CONTROL_STATUS:return struct.pack('<4I',1,7,0,1)+UID.encode()+bytes(64)
        if opcode==0x50524202:return struct.pack('<4I',1,7,1,1)+UID.encode()+bytes(64)
        if opcode==observer.HEALTH:return b'{"host_mock":true}'
        if opcode==loop.ARM:
            boot,epoch,pattern,_=struct.unpack('<4I',payload)
            self.s,self.streams,self.sof=fixture(pattern,epoch);self.drained=False
            return b''
        if opcode==loop.STATUS:
            _,epoch=struct.unpack('<2I',payload);s=copy.deepcopy(self.s)
            if epoch==0:
                s.update(epoch=0,state=0,gpt7_gtpr=0xfffffffe,gpt12_gtpr=0xfffffffe)
            if self.drained:
                for name in loop.SPLIT_NAMES:s['cursor_'+name]=7680
                s['cursor_split_sof']=len(self.sof)*4
            return packed(s)
        if opcode==loop.DRAIN:
            boot,epoch,stream,offset,n=struct.unpack('<5I',payload)
            values=(self.streams+[sum(self.sof,[])])[stream][offset:offset+n]
            if stream==4:self.drained=True
            return payload+struct.pack('<'+'I'*len(values),*values)
        if opcode==loop.CANCEL:return b''
        raise AssertionError(hex(opcode))


def test_real_collector_full_pair_and_cancel(tmp_path):
    d=Detector()
    result=observer.acquire(d.exchange,manifest(),{'frames':100,'pattern':2,'budget_seconds':60},tmp_path,info(),absolute_deadline=time.monotonic()+60)
    assert all(len(__import__('pathlib').Path(r['path']).read_bytes())==30720 for r in result['epochs'][0]['streams'][:4])
    assert d.calls.count(loop.ARM)==1 and d.calls[-1]==loop.CANCEL
    assert not result['physical_qualification']


def test_actual_framed_serial_owner_selects_replacement(tmp_path,monkeypatch):
    import serial
    from ael import prism_native as wire, titan_isolated
    d=Detector();ports=[]
    class Serial:
        def __init__(self,**kwargs):self.timeout=.2;self.write_timeout=1;self.data=b'';self.closed=False;ports.append(self)
        def open(self):assert self.dtr and not self.rts
        def close(self):self.closed=True
        def write(self,raw):
            op,seq,cookie,n,crc,version=struct.unpack_from('<6I',raw,4)
            assert raw[:4]==b'K1S1' and zlib.crc32(raw[32:])==crc
            body=d.exchange(op,raw[32:]);header=b'K1R1'+struct.pack('<6I',0,seq,cookie,len(body),0,zlib.crc32(body))
            self.data=header+struct.pack('<I',zlib.crc32(header))+body;return len(raw)
        def read(self,n):r,self.data=self.data[:min(n,17)],self.data[min(n,17):];return r
    monkeypatch.setattr(serial,'Serial',Serial)
    monkeypatch.setattr(titan_isolated,'preflight',lambda *a,**kw:{'offline_mock':True})
    op=tmp_path/'op.json';op.write_text(json.dumps({'isolated_capture':{'frames':100,'pattern':2,'budget_seconds':60}}))
    result=wire.run_session(manifest(),tmp_path,60,op,deadline=time.monotonic()+60,operation_sha256=digest(op.read_bytes()))
    assert result['isolated_capture']['backend']==observer.BACKEND
    assert len(ports)==1 and ports[0].closed and 1 not in d.calls and 0x50520001 not in d.calls


def test_drain_failure_retained_without_rearm(tmp_path):
    d=Detector()
    def exchange(op,payload=b''):
        raw=d.exchange(op,payload)
        return raw[:-1] if op==loop.DRAIN else raw
    with pytest.raises(RuntimeError,match='Truncated'):
        observer.acquire(exchange,manifest(),{'frames':100,'pattern':2,'budget_seconds':60},tmp_path,info(),absolute_deadline=time.monotonic()+60)
    assert d.calls.count(loop.ARM)==1 and d.calls[-1]==loop.CANCEL
    assert (tmp_path/'replacement-loopback/failure.json').exists()


@pytest.mark.parametrize('field', ['image_sha256','source_commit','source_binding_hash','build_receipt_sha256'])
def test_capture_prior_candidate_binding_refused(field):
    m=manifest()
    a={'schema':observer.SCHEMA,'backend':observer.BACKEND,'identity':info(),
       'image_sha256':m['image']['sha256'],'source_commit':m['source_commit'],
       'source_binding_hash':m['source_binding_hash'],'build_receipt_sha256':m['build_receipt']['sha256']}
    a[field]='wrong'
    with pytest.raises(RuntimeError,match='candidate mismatch'):observer.verify_acquisition(a,m)


def test_stale_capture_refused():
    m=manifest();now=time.time()
    a={'schema':observer.SCHEMA,'backend':observer.BACKEND,'identity':info(),
       'image_sha256':m['image']['sha256'],'source_commit':m['source_commit'],
       'source_binding_hash':m['source_binding_hash'],'build_receipt_sha256':m['build_receipt']['sha256'],
       'acquisition_unix':[now-90002,now-90000]}
    with pytest.raises(RuntimeError,match='Stale'):observer.verify_acquisition(a,m)


def test_electrical_gate_remains_closed(tmp_path,monkeypatch):
    from ael import titan_capture
    p=tmp_path/'capture.json';p.write_text(json.dumps({'schema':observer.SCHEMA}))
    monkeypatch.setattr(observer,'verify_acquisition',lambda *a:{'raw_capture_consistent':True,'physical_qualification':False})
    with pytest.raises(RuntimeError,match='UNQUALIFIED_INPUT_CAPTURE_TIMING'):
        titan_capture.consume_output_proof(manifest(),{'schema':'prism.titan.output-qualification.v2',
            'capture_manifest':{'path':str(p),'sha256':digest(p.read_bytes())}})


def test_wrong_runtime_memory_prevents_arm(tmp_path):
    d=Detector();d.s['ccr']=0
    with pytest.raises(RuntimeError,match='D-cache'):
        observer.acquire(d.exchange,manifest(),{'frames':100,'pattern':2,'budget_seconds':60},tmp_path,info(),absolute_deadline=time.monotonic()+60)
    assert loop.ARM not in d.calls


def test_deadline_during_drain_does_not_rearm(tmp_path):
    d=Detector();now=[0.]
    def exchange(op,payload=b''):
        raw=d.exchange(op,payload)
        if op==loop.DRAIN:now[0]=61
        return raw
    with pytest.raises(RuntimeError,match='deadline'):
        observer.acquire(exchange,manifest(),{'frames':100,'pattern':2,'budget_seconds':60},tmp_path,info(),absolute_deadline=80,clock=lambda:now[0])
    assert d.calls.count(loop.ARM)==1 and d.calls[-1]==loop.CANCEL


def test_cancel_failure_is_not_success(tmp_path):
    d=Detector()
    def exchange(op,payload=b''):
        if op==loop.CANCEL:raise OSError('mock cancel lost')
        return d.exchange(op,payload)
    with pytest.raises(OSError,match='cancel lost'):
        observer.acquire(exchange,manifest(),{'frames':100,'pattern':2,'budget_seconds':60},tmp_path,info(),absolute_deadline=time.monotonic()+60)
    assert not (tmp_path/'replacement-loopback/acquisition.json').exists()
