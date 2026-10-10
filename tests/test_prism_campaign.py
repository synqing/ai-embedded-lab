import copy
import json
from pathlib import Path
import threading

import pytest

from ael import prism_campaign as c


def frozen(tmp_path):
    passages=[]
    for song,name in c.SONGS.items():
        for seconds in (30,60):
            media=tmp_path/(song+'-'+str(seconds)+'.wav');media.write_bytes((song+str(seconds)).encode())
            passages.append(dict(id=f'{song}-{seconds}s',song=name,seconds=seconds,source_sha256=song*32,
                mixture=dict(path=str(media),sha256=c.sha(media),playback_path=str(media),playback_file_sha256=c.sha(media),
                             playback_transform_gain=.5,playback_gain=1,playback_engine_gain=1)))
    for identity in c.PILOTS:
        media=tmp_path/(identity+'.wav');media.write_bytes(identity.encode())
        passages.append(dict(id=identity,song=identity+'.wav',seconds=24,mixture=dict(path=str(media),sha256=c.sha(media),
                        playback_path=str(media),playback_file_sha256=c.sha(media),
                        playback_transform_gain=.5,playback_gain=1,playback_engine_gain=1)))
    words=[0]*18;words[14]=100
    value=dict(schema='titan.music_value.experiment/2',passages=passages,g=1,
               display_mapping=dict(settings_words=words,input_audio_gain=.5,shared_gain_g=1))
    value['freeze_sha256']=c.digest(value)
    path=tmp_path/'freeze.json';c.write_new(path,value);return path


@pytest.fixture
def campaign(tmp_path):
    freeze=frozen(tmp_path);out=tmp_path/'campaign'
    value=c.prepare_campaign(freeze,out,seed=27)
    return value,c.binding(out/'private-key.json'),tmp_path/'ledger.jsonl'


def test_masked_counterbalance_and_bound_durations(campaign):
    value,key,_=campaign
    public=json.loads((Path(key['path']).parent/'masked-schedule.json').read_text())
    assert all('arm' not in row and 'image' not in row for row in public['trials'])
    assert len({t['review_label'] for t in public['trials']})==len(public['trials'])
    assert sum(t['seconds'] for t in value['tasks'] if t['phase']=='endurance_playback')==1020
    assert sum(t['seconds'] for t in value['endurance_diagnostics']['windows'])+14*5==970
    assert all(t['seconds']==24 for t in value['tasks'] if t['phase']=='pilot')
    assert max(value['planned_seconds_by_song'].values())<900
    groups={};positions={a:[0]*4 for a in 'IACD'}
    for t in value['tasks']:
        if t['phase']=='comparison':groups.setdefault(t['passage'],[]).append(t['arm'])
    assert len(groups)==6
    for order in groups.values():
        assert set(order)==set('IACD') and len(order)==4
        for i,a in enumerate(order):positions[a][i]+=1
    assert all(max(counts)-min(counts)<=1 for counts in positions.values())


@pytest.mark.parametrize('fault',['missing','duplicate','unknown','duration','gain'])
def test_bad_freeze_refused_before_preparation(tmp_path,fault):
    path=frozen(tmp_path);value=json.loads(path.read_text())
    if fault=='missing':value['passages'].pop()
    if fault=='duplicate':value['passages'].append(value['passages'][0])
    if fault=='unknown':value['passages'][0]['song']='unknown music'
    if fault=='duration':value['passages'][-1]['seconds']=30
    if fault=='gain':value['g']=2
    value['freeze_sha256']=c.digest({k:v for k,v in value.items() if k!='freeze_sha256'});path.write_text(json.dumps(value))
    with pytest.raises(ValueError):c.prepare_campaign(path,tmp_path/'bad')


def test_failed_or_interrupted_playback_keeps_full_reservation(campaign):
    value,key,path=campaign;task=value['tasks'][0]
    ledger=c.PlaybackLedger(path,key);ledger.reserve(task['id'],task['media']['path'])
    ledger=c.PlaybackLedger(path,key)  # Process restart retains spend.
    ledger.complete(task['id'],success=False)
    assert ledger.records()[0]['reserved_ms']==24000
    with pytest.raises(ValueError,match='Duplicate/spent'):ledger.reserve(task['id'],task['media']['path'])
    with pytest.raises(ValueError,match='Duplicate completion'):ledger.complete(task['id'],success=True)


def test_unknown_audio_and_partial_ledger_refused(campaign,tmp_path):
    value,key,path=campaign;task=value['tasks'][0];ledger=c.PlaybackLedger(path,key)
    other=tmp_path/'other.wav';other.write_bytes(b'unknown')
    with pytest.raises(ValueError):ledger.reserve(task['id'],other)
    with pytest.raises(ValueError):ledger.reserve('unknown',task['media']['path'])
    ledger.reserve(task['id'],task['media']['path'])
    with path.open('ab') as out:out.write(b'{')
    with pytest.raises(ValueError,match='Interrupted'):ledger.records()


def test_song_budget_across_new_campaigns_cannot_reset(tmp_path):
    freeze=frozen(tmp_path);ledger_path=tmp_path/'shared.jsonl'
    for i in range(15):
        out=tmp_path/f'campaign-{i}';value=c.prepare_campaign(freeze,out,seed=i)
        task=next(t for t in value['tasks'] if t['passage']=='03-60s' and t['phase']=='comparison')
        ledger=c.PlaybackLedger(ledger_path,c.binding(out/'private-key.json'))
        if i<14:ledger.reserve(task['id'],task['media']['path'])
        else:
            with pytest.raises(ValueError,match='budget exhausted'):ledger.reserve(task['id'],task['media']['path'])
    assert sum(e['reserved_ms'] for e in ledger.records())==840000


def test_rehashed_wrong_song_key_still_refused(campaign):
    value,key,path=campaign;value['tasks'][0]['song_key']='invented'
    value['campaign_sha256']=c.digest({k:v for k,v in value.items() if k!='campaign_sha256'})
    Path(key['path']).write_text(json.dumps(value));key=c.binding(key['path'])
    with pytest.raises(ValueError,match='song budget identity'):
        c.PlaybackLedger(path,key).reserve(value['tasks'][0]['id'],value['tasks'][0]['media']['path'])


def evidence(tmp_path):
    info=dict(uid='545433931bd25436593630352d068363',boot_id=7,build_source_sha256='b'*64,schema_sha256='c'*64,
              clock_hz=1000000000,initialisation_failed=False,output_timeouts=0,capture_errors=[0,0],output_last_fsp_error=0,
              capture_clock_rejections=0,capture_restart_attempts=0,output_recovery_attempts=0)
    def point(second):
        return dict(identity=info.copy(),snapshot=dict(capture_time_us=1000000+second*1000000,sample_end=12800+second*12800,
            hops=200+second*200,rejected_hops=0,logical_frame=100+second*100,epoch=1),
            transmitter=dict(schema='prism.titan.transmitter.v2',first_fault=0,failures=0,last_fsp_error=0,pattern_requested=0,
                             wire_reset_completions=100+second*100),drive=dict(active=False,phase='idle',live_source=1))
    windows=[];gaps=[]
    for i in range(15):
        start=i*65;before,after=point(start),point(start+60)
        rows=[dict(event='begin',identity=info.copy(),hardware_access=True,request=dict(kind='measure',seconds=60,live_source='D')),
              dict(event='progress_before',snapshot=before['snapshot'],transmitter=before['transmitter']),
              dict(event='health',**point(start+30)),
              dict(event='progress_after',snapshot=after['snapshot'],transmitter=after['transmitter']),
              dict(event='result',data=dict(final_identity=info.copy(),proxy_budget_met=True,hop_deadline_met=True,render_deadline_met=True))]
        p=tmp_path/f'window-{i}.jsonl';p.write_text('\n'.join(json.dumps(r) for r in rows)+'\n');windows.append(p)
        if i<14:
            p=tmp_path/f'gap-{i}.json';c.write_new(p,dict(schema='titan.endurance.gap.v1',hardware_access=True,before=after,after=point(start+65)));gaps.append(p)
    return windows,gaps


def test_continuous_telemetry_does_not_claim_music_or_optics(tmp_path):
    windows,gaps=evidence(tmp_path);result=c.verify_endurance(windows,gaps)
    assert result['covered_seconds']==970 and result['source']=='LIVE_D'
    assert result['music']['status']=='UNMEASURED' and result['optical_verified'] is False
    with pytest.raises(ValueError):c.verify_endurance(windows,[])
    with pytest.raises(ValueError):c.verify_endurance(windows[:2],gaps[:1])


@pytest.mark.parametrize('fault',['boot','build','epoch','counter','fault','hostonly','replay','failed'])
def test_endurance_reset_missing_gap_or_false_host_claim_rejected(tmp_path,fault):
    windows,gaps=evidence(tmp_path);gap=json.loads(gaps[3].read_text());p=gap['after']
    if fault=='boot':p['identity']['boot_id']=8
    if fault=='build':p['identity']['build_source_sha256']='d'*64
    if fault=='epoch':p['snapshot']['epoch']=2
    if fault=='counter':p['transmitter']['wire_reset_completions']=0
    if fault=='fault':p['identity']['capture_restart_attempts']=1
    if fault=='hostonly':gap['hardware_access']=False
    if fault=='replay':p['drive']['active']=True
    if fault=='gap':p['snapshot']['capture_time_us']-=20000
    if fault=='failed':p['transmitter']['first_fault']=1
    gaps[3].write_text(json.dumps(gap))
    with pytest.raises(ValueError):c.verify_endurance(windows,gaps)


def test_stream_budget_is_mandatory_and_canonical(campaign):
    value,key,path=campaign;task=value['tasks'][0]
    prepared=dict(spec={},freeze={'freeze_sha256':value['freeze_sha256']},media=Path(task['media']['path']),arm=task['arm'],hops=4800)
    with pytest.raises(ValueError,match='durable campaign'):c.playback_budget(prepared)
    prepared['spec']['playback_budget']=dict(campaign=key,ledger=str(path),trial_id=task['id'])
    with pytest.raises(ValueError,match='shared durable'):c.playback_budget(prepared)


def stamp_host_evidence(windows,gaps,nonce,boot):
    base=10**12
    for index,path in enumerate(windows):
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row['host_boot_session']=boot;row['host_clock']='CLOCK_UPTIME_RAW'
            if row['event']=='begin':row['request']['acquisition_nonce']=nonce
            if 'snapshot' in row:row['host_uptime_ns']=base+(row['snapshot']['capture_time_us']-1000000)*1000
        path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
    for path in gaps:
        gap=json.loads(path.read_text());gap['acquisition_nonce']=nonce
        for p in (gap['before'],gap['after']):
            p.update(host_boot_session=boot,host_clock='CLOCK_UPTIME_RAW',
                     host_before_uptime_ns=base+(p['snapshot']['capture_time_us']-1000000)*1000,
                     host_after_uptime_ns=base+(p['snapshot']['capture_time_us']-1000000)*1000)
        path.write_text(json.dumps(gap))


def player_log(path,task,origin,boot):
    rows=[dict(event='start',wav=task['media']['path'],clock='CLOCK_UPTIME_RAW',host_boot_session=boot,
               input_gain=1,frames=2880000,file_rate=48000,uptime_ns=origin),
          dict(event='clock',render_uptime_ns=origin,render_sample=0,latency_s=0),
          dict(event='clock',render_uptime_ns=origin+60000000000,render_sample=2880000,latency_s=0),
          dict(event='end',frames=2880000,uptime_ns=origin+60000000000)]
    path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')


@pytest.mark.parametrize('fault',[None,'old-run','old-boot','old-time','overlap'])
def test_playlist_music_requires_same_run_boot_and_actual_temporal_overlap(campaign,tmp_path,fault):
    value,key,path=campaign;ledger=c.PlaybackLedger(path,key);nonce='a'*64;boot='test-boot-identity'
    windows,gaps=evidence(tmp_path);stamp_host_evidence(windows,gaps,nonce,boot)
    tasks=[t for t in value['tasks'] if t['phase']=='endurance_playback']
    for i,task in enumerate(tasks):
        ledger.reserve(task['id'],task['media']['path']);log=tmp_path/f'player-{i}.jsonl'
        origin=10**12+i*60000000000-(10**13 if fault=='old-time' else 0)
        player_log(log,task,origin,'old-boot' if fault=='old-boot' else boot)
        ledger.complete(task['id'],success=True,player_log=log,acquisition_nonce='old-run' if fault=='old-run' else nonce)
    if fault=='old-run':
        with pytest.raises(ValueError,match='playback evidence'):c.verify_endurance(windows,gaps,playback_ledger=ledger,acquisition_nonce=nonce)
        return
    if fault=='overlap':
        # Repeated host windows must not multiply one minute into15minutes.
        for path in windows:
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            for r in rows:
                if r['event']=='progress_before':r['host_uptime_ns']=10**12
                if r['event']=='progress_after':r['host_uptime_ns']=10**12+60000000000
            path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
    result=c.verify_endurance(windows,gaps,playback_ledger=ledger,acquisition_nonce=nonce)
    assert (result['music']['temporal_alignment']=='HOST_RENDER_CLOCK_OVERLAP') is (fault is None)
    if fault=='overlap':assert result['music']['overlap_with_observed_host_seconds']<900


@pytest.mark.parametrize('fault',[None,'gain','timeout'])
def test_actual_playlist_loop_reserves_before_owned_player_and_preserves_failure(campaign,tmp_path,monkeypatch,fault):
    from ael import prism_drive as drive
    value,key,path=campaign;monkeypatch.setattr(c,'PLAYBACK_LEDGER',path)
    monkeypatch.setattr(drive,'host_boot_session',lambda:'test-boot')
    clock=[0.];players=[]
    def pause(dt):clock[0]+=dt
    class Player:
        def __init__(self,media,log,**kwargs):
            records=c.PlaybackLedger(path,key).records();assert records[-1]['event']=='reserve'
            self.done=fault!='timeout';self.error=None;self.aborted=False;players.append(self)
            self.start=dict(clock='CLOCK_UPTIME_RAW',input_gain=2 if fault=='gain' else 1,file_rate=48000,frames=2880000)
            task=next(t for t in value['tasks'] if t['id']==records[-1]['trial_id'])
            player_log(log,task,10**12,'test-boot')
        def close(self):pass
        def abort(self):self.aborted=True
    playlist=c.CampaignPlaylist(dict(campaign=key,ledger=str(path)),tmp_path/'played',player_factory=Player,now=lambda:clock[0],pause=pause).start()
    if fault:
        with pytest.raises(ValueError):playlist.finish(timeout=3)
        assert players[0].aborted
        assert playlist.ledger.records()[-1]['success'] is False
    else:
        assert playlist.finish(timeout=3)['completed']==17
        assert len(playlist.ledger.records())==34
    playlist.stop()


def test_endurance_rejects_wrong_live_health_source(tmp_path):
    windows,gaps=evidence(tmp_path)
    rows=[json.loads(line) for line in windows[0].read_text().splitlines()]
    rows[2]['drive']['live_source']=0
    windows[0].write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
    with pytest.raises(ValueError,match='differs from requested'):c.verify_endurance(windows,gaps)


def test_disjoint_valid_windows_cannot_sum_to_continuous_endurance(tmp_path):
    windows,gaps=evidence(tmp_path)
    for i,path in enumerate(windows):
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            if 'snapshot' in row:row['snapshot']['capture_time_us']+=i*1000000000
        path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
    for i,path in enumerate(gaps):
        gap=json.loads(path.read_text())
        for point in (gap['before'],gap['after']):point['snapshot']['capture_time_us']+=i*1000000000
        path.write_text(json.dumps(gap))
    with pytest.raises(ValueError,match='acquisition span'):
        c.verify_endurance(windows,gaps)


def test_existing_player_startup_is_bounded_and_stops_only_owned_child(tmp_path,monkeypatch):
    import threading
    from ael import prism_drive as drive
    stopped=threading.Event()
    class Output:
        def readline(self):stopped.wait(1);return ''
    class Child:
        stdout=Output();stderr=None
        def poll(self):return None if not stopped.is_set() else 0
        def terminate(self):stopped.set()
        def wait(self,timeout):assert stopped.is_set();return 0
    child=Child();monkeypatch.setattr(drive.subprocess,'Popen',lambda *a,**k:child)
    with pytest.raises(ValueError,match='startup deadline'):
        drive.Player(tmp_path/'unused.wav',tmp_path/'player.jsonl',startup_timeout=.02)
    assert stopped.is_set()


def test_actual_player_wrapper_stamps_read_host_boot_identity(tmp_path,monkeypatch):
    import io
    from ael import prism_drive as drive
    class Child:
        stdout=io.StringIO(json.dumps(dict(event='start',clock='CLOCK_UPTIME_RAW',input_gain=1,file_rate=48000))+'\n'+json.dumps(dict(event='end'))+'\n')
        stderr=None
        def poll(self):return 0
        def wait(self,timeout):return 0
    monkeypatch.setattr(drive.subprocess,'Popen',lambda *a,**k:Child())
    monkeypatch.setattr(drive,'host_boot_session',lambda:'host-boot-from-kernel-fixture')
    path=tmp_path/'player.jsonl';player=drive.Player(tmp_path/'unused.wav',path);player.close()
    row=json.loads(path.read_text().splitlines()[0])
    assert row['host_boot_session']=='host-boot-from-kernel-fixture'
    assert row['host_boot_session_origin'].startswith('Python owner wrapper')


def test_host_boot_identity_refuses_invalid_kernel_value(monkeypatch):
    from types import SimpleNamespace
    from ael import prism_drive as drive
    drive.host_boot_session.cache_clear()
    monkeypatch.setattr(drive.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='not-a-uuid'))
    with pytest.raises(ValueError):drive.host_boot_session()
    drive.host_boot_session.cache_clear()


@pytest.fixture
def incumbent(campaign,tmp_path,monkeypatch):
    from ael import prism_drive as drive
    value,key,ledger=campaign
    monkeypatch.setattr(c,'PLAYBACK_LEDGER',ledger)
    binary=tmp_path/'existing-player';binary.write_bytes(b'owned existing engine fixture')
    monkeypatch.setattr(drive,'PLAYER',binary)
    task=next(t for t in value['tasks'] if t['arm']=='I')
    spec=dict(schema='titan.music.incumbent-prepared.v1',campaign=key,freeze=value['freeze'],
              trial_id=task['id'],media=task['media'],seconds=task['seconds'],input_gain=1)
    observation={k:str(tmp_path/k) for k in ('owner_dir','donor_source','build_receipt')}
    return spec,ledger,observation


def test_existing_eight_donor_requests_validate_without_playback_or_ledger(campaign,incumbent):
    value,key,_=campaign;spec,ledger,_=incumbent
    tasks=[t for t in value['tasks'] if t['arm']=='I']
    assert len(tasks)==8
    for task in tasks:
        request=dict(spec,trial_id=task['id'],media=task['media'],seconds=task['seconds'])
        prepared=c.prepare_incumbent_request(request)
        assert prepared['task']==task and prepared['media']==Path(task['media']['path'])
        assert prepared['playback_started'] is prepared['optical_verified'] is False
    assert not ledger.exists()


@pytest.mark.parametrize('fault',['schema','gain','media','duration','native-arm','freeze','spent','file'])
def test_incumbent_readiness_rejects_changed_inputs_and_spent_trials(campaign,incumbent,fault):
    value,key,_=campaign;spec,ledger,_=incumbent;spec=copy.deepcopy(spec)
    if fault=='schema':spec['schema']='unknown'
    if fault=='gain':spec['input_gain']=.5
    if fault=='media':spec['media']=value['tasks'][6]['media']
    if fault=='duration':spec['seconds']-=1
    if fault=='native-arm':spec['trial_id']=next(t['id'] for t in value['tasks'] if t['arm']=='A')
    if fault=='freeze':spec['freeze']['sha256']='f'*64
    if fault=='spent':c.PlaybackLedger(ledger,key).reserve(spec['trial_id'],spec['media']['path'])
    if fault=='file':Path(spec['media']['path']).write_bytes(b'changed source')
    with pytest.raises(ValueError):c.prepare_incumbent_request(spec)
    assert ledger.exists() is (fault=='spent')


@pytest.mark.parametrize('fault',[None,'preflight','brightness-before','constructor','clock','gain','duration',
                                 'player','close','observer','owner','brightness-during','media-during',
                                 'truncated','timeout','cancel','observer-blocked'])
def test_incumbent_actual_consumer_full_charge_and_owned_cleanup(incumbent,tmp_path,fault):
    spec,path,observation=incumbent;prepared=c.prepare_incumbent_request(spec)
    clock=[0.];players=[];calls=[];cancel=threading.Event()
    def pause(dt):
        clock[0]+=1
        threading.Event().wait(.0001)  # Yield to our injected observation worker.
    def observe(cfg,ctx,facts,*,cancel_event):
        before=ctx.logs_dir.name=='donor-before';calls.append(cfg['seconds'])
        assert cfg['seconds']==(3 if before else spec['seconds'])
        assert cancel_event is not cancel and not cancel_event.is_set()
        if before:
            assert not path.exists()  # Preflight never charges or starts media.
            if fault=='preflight':raise ValueError('injected source/owner preflight failure')
        else:
            if fault=='observer':raise ValueError('injected donor observation failure')
            if fault=='observer-blocked':
                assert cancel_event.wait(3), 'Owned observer was not stopped after the outer timeout'
                return
            if fault=='cancel':cancel.set()
            if fault=='media-during':Path(spec['media']['path']).write_bytes(b'drift during playback')
        facts.update(owner_identity=dict(pid=8 if fault=='owner' and not before else 7,
                          serial_opens=1,epoch=5,identity=dict(uid='Titan fixture')),
                     measurements=dict(brightness_observed=[24 if fault==('brightness-before' if before else 'brightness-during') else 100]))
        raw=ctx.logs_dir/'titan-owner.jsonl';raw.write_text(json.dumps(facts)+'\n')
        facts.update(raw_log=str(raw),raw_sha256=c.sha(raw))
    class Player:
        def __init__(self,media,log,**kwargs):
            records=c.PlaybackLedger(path,spec['campaign']).records()
            assert records[-1]['event']=='reserve' and records[-1]['reserved_ms']==spec['seconds']*1000
            assert media==prepared['media'] and kwargs['input_gain']==1 and kwargs['cancel_event'] is cancel
            if fault=='constructor':raise ValueError('injected bounded player startup failure')
            self.done=fault!='timeout';self.error='bad owned player' if fault=='player' else None
            self.aborted=False;self.closed=False;players.append(self)
            self.start=dict(event='start',wav=str(media),clock='other' if fault=='clock' else 'CLOCK_UPTIME_RAW',
                            input_gain=.5 if fault=='gain' else 1,file_rate=48000,
                            frames=int(spec['seconds']*48000)+(1 if fault=='duration' else 0))
            rows=[self.start,dict(event='end',frames=self.start['frames']-(1 if fault=='truncated' else 0))]
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        def close(self):
            if fault=='close':raise ValueError('injected owned close failure')
            self.closed=True
        def abort(self):self.aborted=True
    out=tmp_path/'executed'
    args=dict(player_factory=Player,observer=observe,cancel_event=cancel,now=lambda:clock[0],pause=pause)
    if fault:
        with pytest.raises(ValueError):c.execute_incumbent(prepared,out,observation,**args)
        failure=json.loads((out/'failure.json').read_text())
        assert failure['reserved'] is (fault not in ('preflight','brightness-before'))
        assert not (out/'result.json').exists()
    else:
        result=c.execute_incumbent(prepared,out,observation,**args)
        assert result['scope']=='DONOR_BROKER_TELEMETRY_AND_PLAYER_ONLY'
        assert result['optical_verified'] is False and result['seconds']==spec['seconds']
        assert 'NOT_AVAILABLE' in result['controls']
        assert calls==[3,spec['seconds']] and players[0].closed and not players[0].aborted
    if fault in ('preflight','brightness-before'):
        assert not path.exists() and not players
    else:
        records=c.PlaybackLedger(path,spec['campaign']).records()
        assert [r['event'] for r in records]==['reserve','complete']
        assert records[0]['reserved_ms']==spec['seconds']*1000
        assert records[-1]['success'] is (fault is None)
        if players:assert players[0].closed or players[0].aborted
        with pytest.raises(ValueError,match='Trial media/arm changed' if fault=='media-during' else 'Duplicate/spent'):
            c.PlaybackLedger(path,spec['campaign']).reserve(spec['trial_id'],spec['media']['path'])


def test_incumbent_cli_validation_is_read_only_and_execution_is_explicit(incumbent,tmp_path,monkeypatch,capsys):
    import sys
    spec,ledger,_=incumbent;request=tmp_path/'request.json';c.write_new(request,spec)
    output=tmp_path/'validated'
    monkeypatch.setattr(c,'execute_incumbent',lambda *a,**k:pytest.fail('unexpected playback'))
    monkeypatch.setattr(sys,'argv',['prism_campaign','--incumbent-request',str(request),'--out',str(output)])
    c.main();row=json.loads(capsys.readouterr().out)
    assert row['scope']=='VALIDATED_ONLY' and row['playback_started'] is False
    assert json.loads((output/'consumer-ready.json').read_text())==row and not ledger.exists()
    monkeypatch.setattr(sys,'argv',['prism_campaign','--incumbent-request',str(request),'--out',str(tmp_path/'refused'),'--execute-incumbent'])
    with pytest.raises(SystemExit):c.main()
    assert not ledger.exists() and not (tmp_path/'refused').exists()


def test_existing_donor_observer_cancellation_prevents_owner_reads(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from serial.tools import list_ports
    from ael.adapters import prism_lane as lane
    cancel=threading.Event();cancel.set()
    monkeypatch.setattr(list_ports,'comports',lambda:[SimpleNamespace(vid=0x045b,pid=0x5310,
                        serial_number='0000000000001',device='fixture-no-open')])
    monkeypatch.setattr(lane,'titan_build_binding',lambda cfg:dict(build_id='fixture',sources={}))
    monkeypatch.setattr(lane,'git',lambda *args:'fixture-commit')
    receipt=tmp_path/'receipt.json';receipt.write_text('{}')
    cfg=dict(owner_dir=str(tmp_path/'absent-owner'),donor_source=str(tmp_path/'absent-donor'),
             build_receipt=str(receipt),seconds=24)
    with pytest.raises(RuntimeError,match='Titan observation cancelled'):
        lane.observe_titan(cfg,SimpleNamespace(logs_dir=tmp_path),{},cancel_event=cancel)
    assert (tmp_path/'titan-owner.jsonl').read_text()==''


@pytest.mark.parametrize('fault',['request','player','ledger','observation'])
def test_incumbent_changed_prepared_binding_refused_before_side_effects(incumbent,tmp_path,fault):
    spec,ledger,observation=incumbent;prepared=c.prepare_incumbent_request(spec)
    if fault=='request':prepared['spec']['input_gain']=.5
    if fault=='player':Path(prepared['player']['path']).write_bytes(b'changed engine')
    if fault=='ledger':prepared['ledger']=str(tmp_path/'alternate-ledger')
    if fault=='observation':observation['owner_dir']='relative-owner'
    output=tmp_path/'refused'
    with pytest.raises(ValueError):
        c.execute_incumbent(prepared,output,observation,
                            player_factory=lambda *a,**k:pytest.fail('unexpected playback'),
                            observer=lambda *a,**k:pytest.fail('unexpected observation'))
    assert not ledger.exists() and not output.exists()
