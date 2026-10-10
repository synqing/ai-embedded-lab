import json
from unittest.mock import Mock
import pytest

@pytest.mark.parametrize('op',[
 {'completion':{'kind':'bad'}},
 {'completion':{'kind':'measure','seconds':1,'live_source':'A','observer_enabled':False},'save':True},
 {'completion':{'kind':'measure','seconds':1,'live_source':'A','observer_enabled':False},'evaluation_drive':{}},
 {'completion':{'kind':'measure','seconds':1,'live_source':'A','observer_enabled':False},'fields':{}},
])
def test_completion_request_refused_before_serial_owner(tmp_path,monkeypatch,op):
    from ael import prism_native
    import serial
    f=tmp_path/'op.json';f.write_text(json.dumps(op))
    forbidden=Mock(side_effect=AssertionError('serial touched'))
    monkeypatch.setattr(serial,'Serial',forbidden)
    with pytest.raises((RuntimeError,ValueError)):
        prism_native.run_session({},tmp_path,10,f)
    forbidden.assert_not_called()


import struct
import zlib
from types import SimpleNamespace
from ael import prism_completion as completion
from ael import prism_native as native


def healthy():
    return dict(uid=native.UID,boot_id=7,build_source_sha256='b'*64,
                schema_sha256=native.SCHEMA,clock_hz=1000000000,initialisation_failed=False,
                output_timeouts=0,capture_errors=[0,0],output_last_fsp_error=0,
                capture_clock_rejections=0,capture_restart_attempts=0,output_recovery_attempts=0)


def wire_cost(stage,count,cycles):
    histogram=[0]*256
    if count:
        if cycles<8: index=cycles
        else:
            exponent=cycles.bit_length()-1
            index=8*exponent+(cycles-(1<<exponent))//(1<<(exponent-3))
        histogram[index]=count
    return struct.pack('<IIQQIIII256I',stage,1000000000,count,cycles*count,cycles if count else 0,0,256,1,*histogram)


class MeasureBench:
    def __init__(self,fault=None):
        self.seconds=0.;self.calls=[];self.source=0;self.observer=None;self.fault=fault
    def pause(self,dt):self.seconds+=dt
    def clock(self):return self.seconds
    def exchange(self,opcode,payload=b''):
        self.calls.append((opcode,payload))
        if opcode==1:
            info=healthy()
            if self.fault=='boot':info['boot_id']=8
            if self.fault=='counter':info['capture_restart_attempts']=1
            if self.fault=='identity':info['uid']='other'
            return json.dumps(info).encode()
        if opcode==completion.PREAMBLE:
            if len(payload)==8:self.observer=struct.unpack('<II',payload)[1]
            return b'{}'
        if opcode==21:return b''
        if opcode==23:
            body=bytearray(1184);struct.pack_into('<I',body,0,0x53564C54)
            body[728:744]=bytes.fromhex(native.UID);body[744:776]=bytes.fromhex('b'*64);body[776:808]=bytes.fromhex(native.SCHEMA)
            epoch=2 if self.fault=='audiogap' and self.seconds else 1
            struct.pack_into('<Q',body,16,epoch)
            struct.pack_into('<Q',body,32,1000000+int(self.seconds*1000000))
            struct.pack_into('<Q',body,48,12800+int(self.seconds*12800))
            struct.pack_into('<I',body,608,200+int(self.seconds*200))
            struct.pack_into('<I',body,612,int(self.fault=='rejectedhop' and self.seconds>0))
            struct.pack_into('<I',body,820,100+int(self.seconds*100))
            return bytes(body)
        if opcode==0x50524C02:
            return json.dumps({'schema':'prism.titan.transmitter.v2','first_fault':int(self.fault=='txfault'),'failures':0,'pattern_requested':int(self.fault=='pattern'),'last_fsp_error':0,
                               'wire_reset_completions':100+(0 if self.fault=='frozenoutput' else int(self.seconds*100))}).encode()
        if opcode==0x50524403:
            return json.dumps({'active':self.fault=='revived','phase':'idle','live_source':self.source}).encode()
        if opcode==0x50524405:
            boot,self.source=struct.unpack('<II',payload);assert boot==7;return b'{}'
        if opcode==completion.COST:
            boot,stage=struct.unpack('<II',payload);assert boot==7
            n=10 if self.seconds else 0
            if self.fault=='missing' and stage==2:n=0
            cycles=2000000 if self.fault=='budget' and stage==3 else 1000
            return wire_cost(stage,n,cycles)
        if opcode==0x50520001:return b''
        raise AssertionError('Unwanted PATCH/save/operation: '+str(opcode))


@pytest.mark.parametrize('source,observer',[('A',False),('D',True)])
def test_actual_measure_branch_source_observer_and_cost(tmp_path,source,observer):
    b=MeasureBench();spec={'kind':'measure','seconds':1,'live_source':source,'observer_enabled':observer}
    result=completion.execute(b.exchange,{'source_binding_hash':'b'*64},spec,tmp_path,healthy(),monotonic=b.clock,pause=b.pause)
    assert b.source==int(source=='D') and b.observer==int(observer)
    assert result['health_samples']==4 and all(x['count']==10 for x in result['costs'])
    assert result['proxy_budget_met'] and result['hop_deadline_met'] and result['render_deadline_met']
    assert result['physical_latency']=='UNMEASURED' and not result['optical_verified']
    assert [json.loads(x)['event'] for x in (tmp_path/'titan-completion.jsonl').read_text().splitlines()][-1]=='result'


@pytest.mark.parametrize('fault',['boot','identity','counter','missing','revived','frozenoutput','audiogap','rejectedhop','txfault','pattern'])
def test_measure_fault_preserves_evidence_and_refuses(tmp_path,fault):
    b=MeasureBench(fault)
    with pytest.raises((completion.Refusal,ValueError)):
        completion.execute(b.exchange,{'source_binding_hash':'b'*64},dict(kind='measure',seconds=1,live_source='D',observer_enabled=False),tmp_path,healthy(),monotonic=b.clock,pause=b.pause)
    assert json.loads((tmp_path/'titan-completion.jsonl').read_text().splitlines()[-1])['event']=='failure'


def test_measure_budget_failure_is_false_not_acceptance(tmp_path):
    b=MeasureBench('budget')
    result=completion.execute(b.exchange,{'source_binding_hash':'b'*64},dict(kind='measure',seconds=1,live_source='D',observer_enabled=False),tmp_path,healthy(),monotonic=b.clock,pause=b.pause)
    assert result['proxy_budget_met'] is False


@pytest.mark.parametrize('fault',[None,'budget'])
def test_existing_serial_owner_runs_completion_and_refuses_budget_failure(tmp_path,monkeypatch,fault):
    import serial
    bench=MeasureBench(fault);ports=[]
    # Initial identity must be read before any experiment mutation.
    class Port:
        def __init__(self,**kwargs):self.buffer=b'';self.closed=False;ports.append(self)
        def open(self):pass
        def close(self):self.closed=True
        def write(self,packet):
            opcode,seq,cookie,size,crc,version,hcrc=struct.unpack_from('<7I',packet,4)
            assert zlib.crc32(packet[:28])==hcrc and zlib.crc32(packet[32:])==crc
            assert len(packet[32:])==size and version==1
            body=bench.exchange(opcode,packet[32:])
            header=b'K1R1'+struct.pack('<6I',0,seq,cookie,len(body),0,zlib.crc32(body))
            self.buffer=header+struct.pack('<I',zlib.crc32(header))+body;return len(packet)
        def read(self,n):result,self.buffer=self.buffer[:n],self.buffer[n:];return result
    monkeypatch.setattr(serial,'Serial',Port)
    actual_execute=completion.execute
    monkeypatch.setattr(completion,'execute',lambda ex,m,s,o,i,**kw:actual_execute(ex,m,s,o,i,monotonic=bench.clock,pause=bench.pause,**kw))
    op=tmp_path/'operation.json';op.write_text(json.dumps({'completion':dict(kind='measure',seconds=1,live_source='D',observer_enabled=True)}))
    manifest={'port':'EMULATED-NO-HARDWARE','source_binding_hash':'b'*64}
    if fault:
        with pytest.raises(ValueError,match='timing budget'):native.run_session(manifest,tmp_path,10,op)
    else:
        result=native.run_session(manifest,tmp_path,10,op)
        assert result['completion']['proxy_budget_met'] and not result['optical_verified']
    assert len(ports)==1 and ports[0].closed
    assert not any(opcode in (25,0x50520002) for opcode,_ in bench.calls)
    assert sum(opcode==0x50520001 for opcode,_ in bench.calls)==1


@pytest.mark.parametrize('cutoff',[0.,.5,1.])
def test_measure_respects_outer_deadline_without_shortening_window(tmp_path, cutoff):
    b = MeasureBench()
    with pytest.raises(completion.Refusal, match='absolute deadline'):
        completion.execute(b.exchange, {'source_binding_hash':'b'*64},
            dict(kind='measure',seconds=1,live_source='D',observer_enabled=False),
            tmp_path, healthy(), monotonic=b.clock, pause=b.pause, deadline=cutoff)
    assert b.seconds == 0
    assert json.loads((tmp_path/'titan-completion.jsonl').read_text().splitlines()[-1])['event'] == 'failure'


def test_exchange_expiry_and_cancellation_preserve_first_failure(tmp_path):
    for fault in ('expiry', 'cancel'):
        out = tmp_path/fault; out.mkdir()
        b = MeasureBench()
        def exchange(op, payload=b''):
            if op == completion.COST:
                if fault == 'cancel': raise KeyboardInterrupt('cancelled cost response')
                b.seconds = 80.
            return b.exchange(op, payload)
        with pytest.raises((completion.Refusal, KeyboardInterrupt)):
            completion.execute(exchange, {'source_binding_hash':'b'*64},
                dict(kind='measure',seconds=1,live_source='D',observer_enabled=False),
                out, healthy(), monotonic=b.clock, pause=b.pause, deadline=80.)
        rows = [json.loads(x) for x in (out/'titan-completion.jsonl').read_text().splitlines()]
        assert rows[-1]['event'] == 'failure'
        assert not any(row['event'] == 'result' for row in rows)


@pytest.mark.parametrize('fault', ['startup', 'partial', 'cancel', 'expiry', None])
def test_isolated_completion_existing_wire_owner_closes_and_retains_failure(tmp_path, monkeypatch, fault):
    import base64
    import hashlib
    import serial
    from ael import titan_isolated
    bench = MeasureBench(); ports = []; admissions = []
    spec = dict(kind='measure', seconds=1, live_source='D', observer_enabled=False)
    request = tmp_path/'request.json'; request.write_text(json.dumps(spec))
    manifest = dict(port='EMULATED-NO-HARDWARE', source_binding_hash='b'*64,
        isolated_qualification={'completion_request': {'path':str(request),
            'sha256':hashlib.sha256(request.read_bytes()).hexdigest()}})
    monkeypatch.setattr(titan_isolated, 'preflight',
        lambda m, consume=False: admissions.append((m, consume)))
    monkeypatch.setattr(native.time, 'monotonic', bench.clock)
    actual_execute = completion.execute
    monkeypatch.setattr(completion, 'execute', lambda ex,m,s,o,i,**kw:
        actual_execute(ex,m,s,o,i,monotonic=bench.clock,pause=bench.pause,**kw))
    class Port:
        def __init__(self, **kwargs): self.buffer=b''; self.closed=False; ports.append(self)
        def open(self): pass
        def close(self): self.closed=True
        def write(self, packet):
            self.opcode, seq, cookie, size, crc, version, hcrc = struct.unpack_from('<7I', packet, 4)
            assert zlib.crc32(packet[:28]) == hcrc and zlib.crc32(packet[32:]) == crc
            body = bench.exchange(self.opcode, packet[32:])
            if self.opcode == 1 and fault == 'startup':
                info=json.loads(body); info['output_timeouts']=1; body=json.dumps(info).encode()
            header=b'K1R1'+struct.pack('<6I',0,seq,cookie,len(body),0,zlib.crc32(body))
            self.buffer=header+struct.pack('<I',zlib.crc32(header))+body
            return len(packet)
        def read(self, n):
            if self.opcode == completion.PREAMBLE and n != 32 and fault in ('partial','cancel','expiry'):
                if fault == 'cancel': raise KeyboardInterrupt('cancelled body')
                result,self.buffer=self.buffer[:1],self.buffer[1:]
                bench.seconds += 4 if fault == 'partial' else 80
                return result
            result,self.buffer=self.buffer[:n],self.buffer[n:]; return result
    monkeypatch.setattr(serial, 'Serial', Port)
    op=tmp_path/'operation.json'; op.write_text(json.dumps({'completion':spec}))
    if fault:
        with pytest.raises((completion.Refusal, TimeoutError, KeyboardInterrupt)):
            native.run_session(manifest,tmp_path,80,op,deadline=80.,operation_sha256=hashlib.sha256(op.read_bytes()).hexdigest())
    else:
        result=native.run_session(manifest,tmp_path,80,op,deadline=80.,operation_sha256=hashlib.sha256(op.read_bytes()).hexdigest())
        assert result['completion']['proxy_budget_met'] is True
    assert len(ports)==1 and ports[0].closed
    assert admissions==[(manifest,False)]
    rows=[json.loads(s) for s in (tmp_path/'titan-native.jsonl').read_text().splitlines()]
    assert rows[0]['opcode']==1 and rows[0]['response_complete']
    assert not any(opcode in (25,0x50520002) for opcode,_ in bench.calls)
    if fault in ('partial','cancel','expiry'):
        assert rows[-1]['opcode']==completion.PREAMBLE and not rows[-1]['response_complete']
        assert rows[-1]['error']
        assert len(base64.b64decode(rows[-1]['response'])) == (32 if fault=='cancel' else 33)
    if fault=='startup': assert len(bench.calls)==2  # INFO and bind only, no computation stimulus.


@pytest.mark.parametrize('deadline', [None, 0, True, float('nan'), float('inf')])
def test_isolated_completion_invalid_outer_deadline_precedes_wire_owner(tmp_path, monkeypatch, deadline):
    import serial
    from ael import titan_isolated
    spec=dict(kind='measure',seconds=1,live_source='D',observer_enabled=False)
    op=tmp_path/'op.json'; op.write_text(json.dumps({'completion':spec}))
    monkeypatch.setattr(titan_isolated,'preflight',lambda *a,**kw:None)
    monkeypatch.setattr(titan_isolated,'completion_request',lambda m:spec)
    forbidden=Mock(side_effect=AssertionError('serial touched'))
    monkeypatch.setattr(serial,'Serial',forbidden)
    with pytest.raises(ValueError,match='absolute deadline'):
        native.run_session({'isolated_qualification':True},tmp_path,80,op,deadline=deadline)
    forbidden.assert_not_called()


@pytest.mark.parametrize('replacement', [
    {'disconnect_check':{}}, {'fields':{},'save':True},
    {'completion':{},'save':True}, {'isolated_capture':{'frames':101,'budget_seconds':60}},
])
def test_isolated_operation_replacement_cannot_open_control_route(tmp_path, monkeypatch, replacement):
    import serial
    from ael import titan_isolated
    from ael.titan_waveform import digest
    op=tmp_path/'operation.json';op.write_text(json.dumps(replacement))
    monkeypatch.setattr(titan_isolated,'preflight',lambda *a,**kw:None)
    monkeypatch.setattr(titan_isolated,'completion_request',lambda m:None)
    forbidden=Mock(side_effect=AssertionError('serial touched'));monkeypatch.setattr(serial,'Serial',forbidden)
    with pytest.raises(ValueError):
        native.run_session({'isolated_qualification':{'frames':100}},tmp_path,80,op,
                           deadline=native.time.monotonic()+80,operation_sha256=digest(op.read_bytes()))
    forbidden.assert_not_called()


def test_isolated_operation_digest_is_checked_before_owner(tmp_path, monkeypatch):
    import serial
    from ael.titan_waveform import digest
    op=tmp_path/'operation.json';op.write_text(json.dumps({'isolated_capture':{'frames':100,'budget_seconds':60}}))
    original=digest(op.read_bytes());op.write_text(json.dumps({'fields':{},'save':True}))
    forbidden=Mock(side_effect=AssertionError('serial touched'));monkeypatch.setattr(serial,'Serial',forbidden)
    with pytest.raises(RuntimeError,match='Changed bound artefact'):
        native.run_session({'isolated_qualification':{'frames':100}},tmp_path,80,op,
                           deadline=native.time.monotonic()+80,operation_sha256=original)
    forbidden.assert_not_called()


def test_endurance_cannot_drop_isolated_deadline(tmp_path):
    exchange=Mock(side_effect=AssertionError('endurance reached wire'))
    with pytest.raises(completion.Refusal,match='Endurance'):
        completion.execute(exchange,{}, {'kind':'endurance'},tmp_path,{},deadline=80.)
    exchange.assert_not_called()
