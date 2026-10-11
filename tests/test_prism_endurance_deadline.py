"""Independent host faults; no serial device, playback or product verdict."""
import json
import struct
import threading
import time
from pathlib import Path

import pytest
from ael import prism_native as native, prism_completion as completion, prism_endurance as endurance
from tests.test_prism_completion import info
from tests.test_prism_completion_measure import MeasureBench, healthy, wire_cost


def request():
    return dict(kind='endurance', gap_seconds=5, windows=[
        dict(kind='measure', seconds=60, live_source='D', observer_enabled=True)
        for _ in range(15)])


class Bench(MeasureBench):
    def exchange(self, opcode, payload=b'', **kwargs):
        if opcode == completion.COST:
            _, stage = struct.unpack('<II', payload)
            return wire_cost(stage, int(self.seconds*200), 1000)
        return super().exchange(opcode, payload)


class ClockDevice:
    def __init__(self):
        self.seconds=0.; self.calls=[]; self.kwargs=[]; self.measures=[]; self.pauses=[]
        self.fault=False
    def now(self): return self.seconds
    def pause(self, seconds):
        self.pauses.append((seconds, len(self.calls))); self.seconds += seconds
    def exchange(self, opcode, payload=b'', **kwargs):
        self.calls.append(opcode); self.kwargs.append(kwargs)
        if opcode==1:
            row=info()
            if self.fault: row['boot_id'] += 1
        elif opcode==23:
            n=int(self.seconds*1e6)
            row=dict(epoch=1,capture_time_us=n,sample_end=int(self.seconds*12800),
                     hops=int(self.seconds*200),rejected_hops=0,logical_frame=int(self.seconds*100))
        elif opcode==0x50524c02:
            row=dict(schema='prism.titan.transmitter.v2',first_fault=0,failures=0,
                     last_fsp_error=0,pattern_requested=0,wire_reset_completions=int(self.seconds*100))
        elif opcode==0x50524403: row=dict(active=False,phase='idle',live_source=1)
        else: raise AssertionError(opcode)
        return json.dumps(row).encode()
    def measure(self, exchange, manifest, req, out, initial, **kwargs):
        self.measures.append(kwargs)
        self.seconds+=60
        (Path(out)/'titan-completion.jsonl').write_text('{"test_fixture":true}\n')
        return dict(proxy_budget_met=True,hop_deadline_met=True,render_deadline_met=True)


def run(d, out, **kwargs):
    return endurance.execute(d.exchange, {'source_binding_hash':'b'*64}, request(), out, info(),
        monotonic=d.now, pause=d.pause, measure=d.measure,
        verifier=lambda *a, **kw: {'music':{'status':'UNMEASURED'}}, **kwargs)


def test_supported_blocking_read_receives_cutoff_before_call_returns():
    """Sleep emulates OS serial read honouring configured timeout."""
    class Port:
        timeout=.6
        def __init__(self): self.bounds=[]
        def read(self,n):
            self.bounds.append(self.timeout);time.sleep(self.timeout);return b''
    p=Port(); start=time.monotonic()
    with pytest.raises(TimeoutError):
        native.read_exact(p, 1, timeout=.6, absolute_deadline=start+.06)
    assert time.monotonic()-start < .25
    assert p.bounds and max(p.bounds) <= .06
    assert p.timeout == .6


def test_cancelled_read_never_enters_blocking_transport():
    class Port:
        timeout=.6
        def read(self,n): raise AssertionError('Cancelled run entered port.read')
    cancel=threading.Event();cancel.set()
    with pytest.raises((TimeoutError, ValueError, completion.Refusal, InterruptedError),match='[Cc]ancel'):
        native.read_exact(Port(), 1, cancel_event=cancel)


def test_supported_blocking_write_receives_deadline_before_call(tmp_path, monkeypatch):
    import serial
    ports=[]
    class Port:
        def __init__(self,**kw):
            self.timeout=kw['timeout'];self.write_timeout=kw['write_timeout'];self.closed=False;self.bounds=[];ports.append(self)
        def open(self): pass
        def close(self): self.closed=True
        def write(self, packet):
            self.bounds.append(self.write_timeout);time.sleep(self.write_timeout)
            raise TimeoutError('blocked fake write timed out at configured OS bound')
    monkeypatch.setattr(serial,'Serial',Port)
    start=time.monotonic()
    with pytest.raises(TimeoutError):
        native.run_session({'port':'EMULATED-NO-HARDWARE','source_binding_hash':'b'*64},tmp_path,1,
                           deadline=start+.06)
    assert time.monotonic()-start < .25
    assert ports[0].closed and max(ports[0].bounds)<=.06
    rows=[json.loads(s) for s in (tmp_path/'titan-native.jsonl').read_text().splitlines()]
    assert len(rows)==1 and not rows[0]['response_complete'] and rows[0]['error']


def test_endurance_delegation_accepts_explicit_collector_cutoff(tmp_path,monkeypatch):
    seen={}
    def delegated(*a,**kw): seen.update(kw);return {'fixture':True}
    monkeypatch.setattr(endurance,'execute',delegated)
    event=threading.Event()
    completion.execute(lambda *a,**kw:b'',{},request(),tmp_path,info(),deadline=1100.,cancel_event=event)
    assert seen['deadline']==1100. and seen['cancel_event'] is event


def test_fifteen_complete_windows_receive_one_absolute_cutoff(tmp_path,monkeypatch):
    monkeypatch.setattr(native,'snapshot',lambda b,binding:json.loads(b))
    d=ClockDevice();event=threading.Event();result=run(d,tmp_path,deadline=1100.,cancel_event=event)
    assert len(result['segments'])==15 and len(result['gaps'])==14
    assert d.seconds==970 and not result['endurance_pass']
    assert len(d.measures)==15 and all(kw['deadline']==1100. and kw['cancel_event'] is event for kw in d.measures)
    assert d.kwargs and all(kw['absolute_deadline']==1100. and kw['cancel_event'] is event for kw in d.kwargs)
    assert abs(sum(seconds for seconds,_ in d.pauses)-70)<1e-6


def test_expired_collector_does_not_start_first_window(tmp_path,monkeypatch):
    monkeypatch.setattr(native,'snapshot',lambda b,binding:json.loads(b))
    d=ClockDevice()
    with pytest.raises((TimeoutError,completion.Refusal),match='deadline|cutoff|bounded'):
        run(d,tmp_path,deadline=0.)
    assert not d.measures and not d.calls
    assert not (tmp_path/'endurance/collection.json').exists()


def test_gap_fault_observation_is_retained_before_health_rejection(tmp_path,monkeypatch):
    monkeypatch.setattr(native,'snapshot',lambda b,binding:json.loads(b))
    d=ClockDevice();pause=d.pause
    def failed_gap(seconds): pause(seconds);d.fault=True
    d.pause=failed_gap
    with pytest.raises(completion.Refusal,match='identity/boot'):
        run(d,tmp_path)
    records=[]
    for p in (tmp_path/'endurance').rglob('*.json*'):
        for line in (p.read_text().splitlines() if p.suffix=='.jsonl' else [p.read_text()]):
            try: records.append(json.loads(line))
            except ValueError: pass
    def contains_fault(x):
        if isinstance(x,dict): return x.get('boot_id')==info()['boot_id']+1 or any(contains_fault(y) for y in x.values())
        if isinstance(x,list): return any(contains_fault(y) for y in x)
        return False
    assert any(contains_fault(r) for r in records), 'First failing decoded identity was discarded'
    assert not (tmp_path/'endurance/window-02').exists()


def test_healthy_real_measure_and_verifier_fifteen_window_positive_control(tmp_path,monkeypatch):
    b=Bench()
    monkeypatch.setattr(completion,'uptime_ns',lambda:int((b.seconds+1)*1e9))
    monkeypatch.setattr(endurance,'uptime_ns',lambda:int((b.seconds+1)*1e9))
    result=endurance.execute(b.exchange,{'source_binding_hash':'b'*64},request(),tmp_path,healthy(),
        monotonic=b.clock,pause=b.pause,deadline=1100.)
    assert result['verification']['covered_seconds']>=970
    assert len(result['segments'])==15 and len(result['gaps'])==14
    assert result['verification']['music']['status']=='UNMEASURED'
    assert not result['endurance_pass'] and not result['optical_verified']


def test_readiness_enforces_transport_bound_and_preserves_partial_row(tmp_path):
    b=Bench();seen=[]
    def exchange(op,payload=b'',**kw):
        seen.append((op,kw))
        if op==23:
            assert kw['absolute_deadline'] < 120.
            b.seconds=kw['absolute_deadline']
            raise TimeoutError('first readiness snapshot hit its configured cutoff')
        return b.exchange(op,payload)
    with pytest.raises(TimeoutError,match='readiness'):
        completion.execute(exchange,{'source_binding_hash':'b'*64},dict(kind='measure',seconds=60,
            live_source='D',observer_enabled=True),tmp_path,healthy(),monotonic=b.clock,pause=b.pause,deadline=120.)
    rows=[json.loads(s) for s in (tmp_path/'titan-completion.jsonl').read_text().splitlines()]
    assert any(r.get('event')=='readiness_health' and r.get('observation_complete') is False for r in rows)
    assert rows[-1]['event']=='failure' and not any(r.get('event')=='result' for r in rows)


@pytest.mark.parametrize('seconds',[20,60])
def test_child_measurement_keeps_full_window_under_explicit_cutoff(tmp_path,seconds):
    b=Bench(); bounds=[]
    def exchange(op,payload=b'',**kw):
        bounds.append(kw['absolute_deadline']);return b.exchange(op,payload)
    result=completion.execute(exchange,{'source_binding_hash':'b'*64},dict(kind='measure',seconds=seconds,
        live_source='D',observer_enabled=True),tmp_path,healthy(),monotonic=b.clock,pause=b.pause,deadline=100.)
    rows=[json.loads(s) for s in (tmp_path/'titan-completion.jsonl').read_text().splitlines()]
    begins=[r for r in rows if r.get('event')=='measurement_begin']
    assert len(begins)==1 and begins[0]['full_window_seconds']==seconds
    assert result['measurement_seconds']==seconds and result['live_continuity_met']
    assert max(bounds)==100. and min(bounds)<100.


def test_cancellation_after_blocking_read_preserves_partial_bytes():
    event=threading.Event()
    class Port:
        timeout=.2
        def read(self,n): event.set();return b'Q'
    with pytest.raises(InterruptedError,match='[Cc]ancel') as error:
        native.read_exact(Port(),1,cancel_event=event)
    assert error.value.partial==b'Q'


def test_cancellation_during_gap_stops_before_next_query(tmp_path,monkeypatch):
    monkeypatch.setattr(native,'snapshot',lambda b,binding:json.loads(b))
    d=ClockDevice();event=threading.Event();original=d.pause; calls=[]
    def cancel(seconds):
        original(seconds);calls.append(len(d.calls));event.set()
    d.pause=cancel
    with pytest.raises(completion.Refusal,match='[Cc]ancel'):
        run(d,tmp_path,cancel_event=event)
    assert len(d.calls)==calls[-1]
    assert not (tmp_path/'endurance/window-02').exists()
    failure=json.loads((tmp_path/'endurance/failure.json').read_text())
    assert len(failure['segments'])==1 and failure['gaps']==[]


@pytest.mark.parametrize('fault',['cancel','final'])
def test_owned_playlist_cleanup_retains_primary_or_final_failure(tmp_path,monkeypatch,fault):
    from ael import prism_campaign as campaign
    monkeypatch.setattr(native,'snapshot',lambda b,binding:json.loads(b))
    d=ClockDevice();event=threading.Event();instances=[]
    class Playlist:
        def __init__(self,*args,**kw):
            self.started=False;self.stops=[];self.acquisition_nonce='f'*64;self.ledger=None
            instances.append(self)
        def start(self): self.started=True
        def check(self): pass
        def finish(self,timeout=60): d.fault=True
        def stop(self,**kwargs): self.stops.append(kwargs)
    monkeypatch.setattr(campaign,'CampaignPlaylist',Playlist)
    req=request();req['playlist']={'test_only':True}
    def measure(*args,**kwargs):
        if fault=='cancel':
            event.set();raise KeyboardInterrupt('planted child cancellation')
        return d.measure(*args,**kwargs)
    with pytest.raises((KeyboardInterrupt,completion.Refusal),match='cancellation|identity/boot'):
        endurance.execute(d.exchange,{'source_binding_hash':'b'*64},req,tmp_path,info(),
            monotonic=d.now,pause=d.pause,measure=measure,cancel_event=event,deadline=1100.)
    assert not instances[0].started and not instances[0].stops
    owned=instances[-1];assert owned.started and len(owned.stops)==1
    assert owned.stops[0]['timeout']==8 and owned.stops[0]['absolute_deadline']==d.seconds+8
    assert (tmp_path/'endurance/failure.json').exists() and not (tmp_path/'endurance/collection.json').exists()
    if fault=='final':
        observations=[json.loads(p.read_text()) for p in (tmp_path/'endurance').glob('health-*.json')]
        assert any(r.get('identity',{}).get('boot_id')==info()['boot_id']+1 for r in observations)


def test_playlist_stop_joins_only_owned_thread_with_cleanup_bound():
    from ael.prism_campaign import CampaignPlaylist
    class Worker:
        def __init__(self): self.joins=[]
        def join(self,seconds): self.joins.append(seconds)
        def is_alive(self): return False
    owned=Worker();unowned=Worker();playlist=CampaignPlaylist.__new__(CampaignPlaylist)
    playlist.cancel=threading.Event();playlist.thread=owned;playlist.now=lambda:500.
    playlist.stop(timeout=8,absolute_deadline=502.)
    assert owned.joins==[2.] and unowned.joins==[] and playlist.cancel.is_set()
