import json
from pathlib import Path
import pytest

from ael.prism_endurance import prepare, execute, Refusal
from tests.test_prism_completion import info


def spec():
    return {'kind':'endurance','gap_seconds':5,'windows':[
        {'kind':'measure','seconds':60,'live_source':'D','observer_enabled':True}
        for _ in range(15)]}


@pytest.mark.parametrize('change',[{'windows':[]},{'gap_seconds':0},{'kind':'unknown'}])
def test_bounds(change):
    request=spec();request.update(change)
    with pytest.raises(Refusal):prepare(request)


def test_reject_oversized_window():
    request=spec();request['windows'][0]['seconds']=121
    with pytest.raises(Refusal):prepare(request)


class Device:
    def __init__(self):
        self.time=0.;self.calls=[];self.pauses=[];self.boot_change=False
    def now(self):return self.time
    def pause(self,seconds):
        before=len(self.calls);self.time+=seconds
        self.pauses.append((seconds,before,len(self.calls)))
    def snapshot(self):
        n=int(self.time*1000000)
        return {'epoch':1,'capture_time_us':n,'sample_end':n*12800//1000000,
                'hops':n//5000,'rejected_hops':0,'logical_frame':n//10000}
    def exchange(self,op,payload=b''):
        self.calls.append(op)
        if op==1:
            value=info()
            if self.boot_change and self.time>60:value['boot_id']+=1
        elif op==23:value=self.snapshot()
        elif op==0x50524c02:
            value={'schema':'prism.titan.transmitter.v2','first_fault':0,'failures':0,
                   'last_fsp_error':0,'pattern_requested':0,'wire_reset_completions':int(self.time*100)}
        elif op==0x50524403:value={'active':False,'phase':'idle','live_source':1}
        else:raise AssertionError(op)
        return json.dumps(value).encode()
    def measure(self,exchange,manifest,request,out,initial,**kwargs):
        assert exchange==self.exchange and request['seconds']==60
        self.time+=60
        (Path(out)/'titan-completion.jsonl').write_text('{"synthetic_test":true}\n')
        return dict(proxy_budget_met=True,hop_deadline_met=True,render_deadline_met=True)


def test_same_owner_bounded_gaps_and_no_fabricated_pass(tmp_path,monkeypatch):
    monkeypatch.setattr('ael.prism_native.snapshot',lambda body,binding:json.loads(body))
    d=Device();result=execute(d.exchange,{'source_binding_hash':'b'*64},spec(),tmp_path,info(),
                              monotonic=d.now,pause=d.pause,measure=d.measure)
    assert len(result['segments'])==15 and len(result['gaps'])==14
    assert result['elapsed_host_seconds']==970
    assert not result['endurance_pass'] and result['playback_evidence']=='REQUIRED_SEPARATELY'
    assert all(seconds==5 and before==after for seconds,before,after in d.pauses)
    assert len(d.calls)==14*8
    for row in result['gaps']:
        gap=json.loads(Path(row['path']).read_text())
        assert gap['after']['snapshot']['capture_time_us']-gap['before']['snapshot']['capture_time_us']==5000000
        assert gap['diagnostic_queries_between_endpoints']==0


def test_boot_change_preserves_failure_and_stops(tmp_path,monkeypatch):
    monkeypatch.setattr('ael.prism_native.snapshot',lambda body,binding:json.loads(body))
    d=Device();d.boot_change=True
    with pytest.raises(Refusal,match='identity/boot'):
        execute(d.exchange,{'source_binding_hash':'b'*64},spec(),tmp_path,info(),
                monotonic=d.now,pause=d.pause,measure=d.measure)
    failure=json.loads((tmp_path/'endurance/failure.json').read_text())
    assert len(failure['segments'])==1 and not failure['endurance_pass']
    assert not (tmp_path/'endurance/window-02').exists()
