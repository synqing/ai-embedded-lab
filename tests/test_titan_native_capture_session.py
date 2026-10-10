"""Actual framed owner integration; all endpoints and clocks are host fakes."""
import base64
import json
from pathlib import Path
import struct
import zlib

import pytest

from ael import prism_native as wire, titan_loopback as loop, titan_isolated as isolated
from test_titan_loopback import Detector


def session(tmp,monkeypatch,*,fault=None,deadline_seconds=60):
    import serial
    from ael import prism_drive
    detector=Detector();detector.info['schema_sha256']=wire.SCHEMA
    ports=[]
    monkeypatch.setattr(isolated,'preflight',lambda *args,**kw:{'host_fixture_only':True})
    monkeypatch.setattr(wire.time,'monotonic',lambda:detector.now)
    monkeypatch.setattr(loop.time,'time',lambda:detector.now+1000000)
    monkeypatch.setattr(prism_drive,'uptime_ns',lambda:int(detector.now*1e9))
    original_acquire=loop.acquire
    monkeypatch.setattr(loop,'acquire',lambda *args,**kw:original_acquire(*args,**kw,
        clock=lambda:detector.now,sleep=lambda n:setattr(detector,'now',detector.now+n)))
    class Serial:
        def __init__(self,**kwargs):
            self.timeout=kwargs['timeout'];self.write_timeout=kwargs['write_timeout']
            self.data=b'';self.closed=False;self.body_reads=0;self.opcode=0;ports.append(self)
        def open(self):assert self.dtr is True and self.rts is False
        def close(self):self.closed=True
        def write(self,packet):
            opcode,sequence,cookie,n,crc,version=struct.unpack_from('<6I',packet,4)
            assert version==1 and zlib.crc32(packet[32:])==crc
            assert zlib.crc32(packet[:28])==struct.unpack_from('<I',packet,28)[0]
            self.opcode=opcode;self.body_reads=0
            if opcode==0x50520001:
                assert packet[32:]==wire.bind_payload(7);body=b''
            else:body=detector.exchange(opcode,packet[32:])
            size=len(body)
            if fault=='oversized' and opcode==1:size=4097
            header=b'K1R1'+struct.pack('<6I',0,sequence,cookie,size,0,zlib.crc32(body))
            self.data=header+struct.pack('<I',zlib.crc32(header))+body
            if fault=='short_header' and opcode==1:self.data=self.data[:9]
            if fault in ('short_body','mid_body_exception') and opcode==1:self.data=self.data[:37]
            if fault=='late_info' and opcode==1:self.data=b''
            if fault=='late_witness' and opcode==loop.TIMING_WITNESS:self.data=b''
            if fault=='late_bind' and opcode==0x50520001:self.data=b''
            if fault=='late_chunk' and opcode==loop.DRAIN:
                detector.now=1000+deadline_seconds-.05;self.data=b''
            if fault=='late_cancel' and opcode==loop.CANCEL:
                detector.now=1000+deadline_seconds-.05;self.data=b''
            return len(packet)
        def read(self,size):
            self.body_reads+=1
            if self.data:
                out,self.data=self.data[:size],self.data[size:]
                return out
            if fault=='mid_body_exception' and self.opcode==1:raise OSError('injected device disappearance')
            detector.now+=self.timeout
            return b''
    monkeypatch.setattr(serial,'Serial',Serial)
    event=tmp/'program.json';event.write_text('{}')
    manifest={'port':'/dev/cu.TEST-NO-HARDWARE','source_binding_hash':'b'*64,'source_commit':'d'*40,
        'image':{'sha256':'a'*64},'build_receipt':{'sha256':'e'*64},'isolated_fixture_id':'TEST-ONLY',
        'isolated_programming_event':{'path':str(event),'sha256':loop.digest(event.read_bytes())},
        'isolated_qualification':{'physical_confirmation':{},'bootstrap_authority':{}}}
    op=tmp/'operation.json';op.write_text(json.dumps({'isolated_capture':{'frames':100}}))
    return detector,ports,manifest,op


def test_real_single_owner_raw_capture_path(tmp_path,monkeypatch):
    detector,ports,m,op=session(tmp_path,monkeypatch)
    result=wire.run_session(m,tmp_path,60,op,deadline=1060)
    assert result['runtime_boot_verified'] and result['isolated_capture']['frames_each']==100
    assert not result['isolated_capture']['physical_qualification']
    assert len(ports)==1 and ports[0].closed
    records=[json.loads(x) for x in (tmp_path/'titan-native.jsonl').read_text().splitlines()]
    assert [r['sequence'] for r in records]==list(range(1,len(records)+1))
    assert sum(r['opcode']==loop.ARM for r in records)==100
    assert not any(r['opcode'] in (25,0x50520002) for r in records)
    assert all(r['error'] is None and r['response_complete'] for r in records)


@pytest.mark.parametrize('fault,minimum',[('short_header',9),('short_body',37),('oversized',32),('mid_body_exception',37)])
def test_failed_wire_reply_retains_actual_partial_bytes(tmp_path,monkeypatch,fault,minimum):
    detector,ports,m,op=session(tmp_path,monkeypatch,fault=fault)
    with pytest.raises((TimeoutError,OSError,ValueError)):
        wire.run_session(m,tmp_path,60,op,deadline=1060)
    record=json.loads((tmp_path/'titan-native.jsonl').read_text().splitlines()[0])
    assert len(base64.b64decode(record['response']))>=minimum
    assert record['error'] and not record['response_complete']
    reads=record['header_reads']+record['body_reads']
    assert sum(r['bytes'] for r in reads)==len(base64.b64decode(record['response']))
    assert all(r['ended_monotonic']>=r['started_monotonic'] for r in reads)
    if fault in ('short_header','short_body'):
        assert any(r['bytes']==0 for r in reads)
    assert len(ports)==1 and ports[0].closed and loop.ARM not in detector.calls


@pytest.mark.parametrize('fault',['late_info','late_bind','late_chunk','late_cancel'])
def test_one_absolute_deadline_bounds_info_bind_chunk_and_cancel(tmp_path,monkeypatch,fault):
    budget=.1 if fault in ('late_info','late_bind') else 30
    detector,ports,m,op=session(tmp_path,monkeypatch,fault=fault,deadline_seconds=budget)
    with pytest.raises((TimeoutError,RuntimeError)):
        wire.run_session(m,tmp_path,budget,op,deadline=1000+budget)
    assert detector.now<=1000+budget+1e-9
    assert ports[0].closed
    records=[json.loads(x) for x in (tmp_path/'titan-native.jsonl').read_text().splitlines()]
    assert any(r['error'] for r in records)
    assert all(r['write_bytes'] is None or r['before_uptime_ns']<int((1000+budget)*1e9) for r in records)
    if fault=='late_chunk':
        assert (tmp_path/'loopback/failure.json').is_file()
        # A bounded cancel may still fit inside the remaining interval; it
        # must neither erase the failed chunk nor extend the absolute deadline.
        assert records[-1]['opcode']==loop.CANCEL


def test_isolated_session_without_transaction_deadline_cannot_open_serial(tmp_path,monkeypatch):
    _,ports,m,op=session(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='absolute deadline'):
        wire.run_session(m,tmp_path,60,op)
    assert ports==[]


def test_optional_witness_timeout_is_one_second_and_does_not_mask_result(tmp_path,monkeypatch):
    detector,ports,m,op=session(tmp_path,monkeypatch,fault='late_witness')
    detector.info['capabilities']['fixture_timing_witness_opcode']=loop.TIMING_WITNESS
    base=detector.exchange
    def exchange(opcode,payload=b''):
        if opcode==loop.TIMING_WITNESS:return b''
        return base(opcode,payload)
    detector.exchange=exchange
    op.write_text(json.dumps({'isolated_capture':{'frames':100,'pattern':2}}))
    result=wire.run_session(m,tmp_path,60,op,deadline=1060)
    assert result['isolated_capture']['epochs'][0]['result']['raw_capture_consistent']
    records=[json.loads(x) for x in (tmp_path/'titan-native.jsonl').read_text().splitlines()]
    witness=[r for r in records if r['opcode']==loop.TIMING_WITNESS]
    assert len(witness)==1
    assert 0.999 <= (witness[0]['after_uptime_ns']-witness[0]['before_uptime_ns'])/1e9 <= 1.001
    assert witness[0]['error'] and ports[0].closed
