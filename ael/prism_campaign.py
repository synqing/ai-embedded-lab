"""Offline comparison preparation, durable playback budget and evidence checks.

This module never opens serial, starts playback or admits an image. The existing
streamer consumes its reservation hook before creating the media-clock player.
"""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import secrets
import threading
import time

SONGS = {'03': 'Dash Berlin - Shelter (Yoel Lewis Remix)',
         '04': 'Alok & Ava Max - Car Keys (Tiesto Remix)',
         '05': 'Collapz - The Valhalla King'}
PILOTS = ('sonic-samba-20-44s', 'carte-blanche-20-44s')
PLAYBACK_LEDGER = Path(__file__).resolve().parents[1] / '_scratch/titan-music-playback-ledger.jsonl'


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binding(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path)}


def bound(spec):
    require(isinstance(spec, dict) and isinstance(spec.get('path'), str), 'Bound file required')
    path = Path(spec['path'])
    require(path.is_absolute() and path.is_file() and sha(path) == spec.get('sha256'), 'Bound file changed')
    return path


def write_new(path, value):
    with Path(path).open('x') as out:
        out.write(json.dumps(value, indent=2) + '\n')


def prepare_campaign(freeze_path, output, *, seed=None):
    freeze_path, output = Path(freeze_path).resolve(), Path(output).resolve()
    frozen = json.loads(freeze_path.read_text())
    require(frozen.get('schema') == 'titan.music_value.experiment/2' and
            frozen.get('freeze_sha256') == digest({k:v for k,v in frozen.items() if k != 'freeze_sha256'}), 'Invalid frozen experiment')
    passages = {p['id']: p for p in frozen['passages']}
    require(len(passages) == len(frozen['passages']) and set(passages) ==
            {s+'-'+str(n)+'s' for s in SONGS for n in (30,60)} | set(PILOTS), 'Missing/duplicate/unknown music passage')
    for identity, p in passages.items():
        if identity not in PILOTS:
            require(p['song'] == SONGS[identity[:2]], 'Unknown approved song')
        require(p['seconds'] == (24 if identity in PILOTS else int(identity[3:-1])), 'Frozen passage duration changed')
        require(sha(p['mixture']['playback_path']) == p['mixture']['playback_file_sha256'], 'Playback binding changed')
    require(frozen['display_mapping']['settings_words'][14] == 100 and frozen['g'] == 1, 'Frozen scene/gain changed')
    output.mkdir(parents=True, exist_ok=False)
    seed = secrets.randbits(128) if seed is None else seed
    rng = random.Random(seed)
    namespace=digest({'private_campaign_seed':seed})[:16]
    arms = list('IACD');rng.shuffle(arms)
    # Four Williams orders balance positions and first-order carryover. Six
    # passage blocks use all four plus two: position counts differ by at most1.
    orders = ((0,1,3,2),(1,2,0,3),(2,3,1,0),(3,0,2,1))
    tasks = []
    def add(phase, passage, arm, seconds=None, gap=False):
        p = passages[passage]
        duration = p['seconds'] if seconds is None else seconds
        require(0 < duration <= 120, 'Diagnostic window exceeds120s')
        tasks.append(dict(id=f'{namespace}-trial-{len(tasks)+1:03d}', phase=phase, passage=passage,
            song=p['song'], song_key=p.get('source_sha256', p['mixture']['sha256']),
            arm=arm, seconds=duration, diagnostic_seconds=0 if gap else duration,
            media={'path':p['mixture']['playback_path'],'sha256':p['mixture']['playback_file_sha256']},
            media_seconds=p['seconds'], image='donor' if arm=='I' else 'native'))
    for pilot in PILOTS:
        for arm in ('I','A','D'):add('pilot',pilot,arm)
    for block, passage in enumerate(s+'-'+str(n)+'s' for s in SONGS for n in (30,60)):
        for i in orders[block%4]:add('comparison',passage,arms[i])
    # Playback runs independently across diagnostic boundaries. Seventeen
    # complete approved60s files cover the970s collector plus bounded margin;
    # a five-second diagnostic gap is never represented as a playable60s file.
    for i in range(17):add('endurance_playback',list(SONGS)[i%3]+'-60s','LIVE',gap=True)
    diagnostics=[dict(kind='measure',seconds=60,live_source='A' if i%2==0 else 'D',observer_enabled=bool(i%2)) for i in range(15)]
    totals=Counter()
    for task in tasks:totals[task['song_key']]+=task['seconds']
    require(max(totals.values())<900, 'Planned per-song playback reaches15minutes')
    labels=list(range(1,len(tasks)+1));rng.shuffle(labels)
    public=[]
    for task,label in zip(tasks,labels):
        task['review_label']=f'Clip-{label:03d}'
        public.append({k:task[k] for k in ('id','phase','passage','song','seconds','diagnostic_seconds','review_label')})
    rng.shuffle(public)
    private=dict(schema='titan.music.campaign.private.v1',scope='PREPARED_ONLY; no playback, admission or owner ratings',
                 freeze=binding(freeze_path),freeze_sha256=frozen['freeze_sha256'],seed=seed,tasks=tasks,
                 endurance_diagnostics=dict(kind='endurance',windows=diagnostics,gap_seconds=5),
                 planned_seconds_by_song=dict(totals),counterbalance='Six passage blocks; four Williams orders plus two, position imbalance at most1',
                 acquisition_order_distinct_from_review_order=True)
    private['campaign_sha256']=digest(private)
    write_new(output/'private-key.json',private)
    write_new(output/'masked-schedule.json',dict(schema='titan.music.campaign.masked.v1',scope='PREPARED_ONLY',trials=public,
               ratings=['percussion_relationship','quiet_space','coherence_enjoyment','overall_appearance','severe_artifacts'],ties_allowed=True))
    budget=dict(campaign=binding(output/'private-key.json'),ledger=str(PLAYBACK_LEDGER))
    write_new(output/'endurance-request.json',dict(completion=dict(private['endurance_diagnostics'],playlist=budget)))
    # Bind the existing real AEL request examples to this private schedule. Their
    # output gates remain in the existing gateway, unchanged by preparation.
    for arm in ('A','C','D'):
        template=freeze_path.parent/'ael-requests'/('03-30s-'+arm+'.json')
        if template.is_file():
            request=json.loads(template.read_text())
            require(request['evaluation_drive']['freeze']==binding(freeze_path),'Stale prepared stream request')
            task=next(t for t in tasks if t['phase']=='comparison' and t['passage']=='03-30s' and t['arm']==arm)
            request['evaluation_drive']['playback_budget']=dict(budget,trial_id=task['id'])
            write_new(output/('03-30s-'+arm+'-request.json'),request)
    return private


class PlaybackLedger:
    """Append-only hash chain under one file lock; reservations never refunded.

An interrupted or failed player keeps its entire reserved duration charged.
Completion records add actual player evidence but cannot erase prior usage.
"""
    def __init__(self, path, campaign):
        self.path=Path(path);require(self.path.is_absolute(),'Absolute playback ledger required')
        self.campaign_file=bound(campaign);self.campaign=json.loads(self.campaign_file.read_text())
        c=self.campaign
        require(c.get('schema')=='titan.music.campaign.private.v1' and c.get('campaign_sha256')==digest({k:v for k,v in c.items() if k!='campaign_sha256'}),'Invalid private campaign key')
        self.freeze=json.loads(bound(c['freeze']).read_text())
        require(self.freeze['freeze_sha256']==c['freeze_sha256'],'Campaign freeze changed')
        self.tasks={t['id']:t for t in c['tasks']}
        require(len(self.tasks)==len(c['tasks']),'Duplicate campaign trial')

    def _read(self, stream):
        stream.seek(0);raw=stream.read()
        require(not raw or raw.endswith(b'\n'),'Interrupted playback ledger write')
        events=[];previous='0'*64
        reserved=set();completed=set()
        for line in raw.splitlines():
            event=json.loads(line)
            require(event.get('previous')==previous and event.get('sequence')==len(events) and
                    event.get('sha256')==digest({k:v for k,v in event.items() if k!='sha256'}) and
                    isinstance(event.get('campaign_sha256'),str) and len(event['campaign_sha256'])==64,'Playback ledger chain changed')
            trial=event.get('trial_id')
            require(isinstance(trial,str) and trial,'Missing ledger trial identity')
            if event.get('event')=='reserve':
                require(trial not in reserved and type(event.get('reserved_ms')) is int and 0<event['reserved_ms']<=120000,'Duplicate/invalid ledger reservation')
                reserved.add(trial)
            else:
                require(event.get('event')=='complete' and trial in reserved and trial not in completed and type(event.get('success')) is bool,'Invalid ledger completion')
                completed.add(trial)
            previous=event['sha256'];events.append(event)
        return events

    def _append(self, build):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            events=self._read(stream);event=build(events)
            event.update(sequence=len(events),previous=events[-1]['sha256'] if events else '0'*64,
                         campaign_sha256=self.campaign['campaign_sha256'])
            event['sha256']=digest(event)
            stream.write(json.dumps(event,sort_keys=True,allow_nan=False).encode()+b'\n');stream.flush();os.fsync(stream.fileno())
            return event

    def reserve(self, trial_id, media, *, arm=None, seconds=None):
        require(trial_id in self.tasks,'Unknown music/trial')
        task=self.tasks[trial_id]
        require(binding(media)==task['media'] and (arm is None or arm==task['arm']),'Trial media/arm changed')
        if seconds is not None:require(seconds==task['seconds'],'Trial duration changed')
        # All review passages and pilots are inherited from the validated freeze.
        passage=next((p for p in self.freeze['passages'] if p['id']==task['passage']),None)
        require(passage and task['media']['sha256']==passage['mixture']['playback_file_sha256'],'Unknown frozen music')
        require(task['song_key']==passage.get('source_sha256',passage['mixture']['sha256']) and
                0<task['seconds']<=passage['seconds'],'Wrong song budget identity/duration')
        def event(events):
            reserved=[r for r in events if r['event']=='reserve']
            require(not any(r['trial_id']==trial_id for r in reserved),'Duplicate/spent playback trial')
            total=sum(r['reserved_ms'] for r in reserved if r['song_key']==task['song_key'])
            milliseconds=round(task['seconds']*1000)
            require(0<milliseconds<=120000 and total+milliseconds<900000,'Per-song15minute playback budget exhausted')
            return dict(event='reserve',trial_id=trial_id,song_key=task['song_key'],media=task['media'],
                        reserved_ms=milliseconds,phase=task['phase'],arm=task['arm'])
        return self._append(event)

    def complete(self, trial_id, *, success, player_log=None, acquisition_nonce=None):
        require(type(success) is bool,'Explicit playback completion state required')
        evidence=None
        if player_log is not None and Path(player_log).is_file():evidence=binding(player_log)
        def event(events):
            require(any(r['event']=='reserve' and r['trial_id']==trial_id for r in events),'Playback completion lacks reservation')
            require(not any(r['event']=='complete' and r['trial_id']==trial_id for r in events),'Duplicate completion')
            return dict(event='complete',trial_id=trial_id,success=success,player_log=evidence,acquisition_nonce=acquisition_nonce,charged_duration='full-reservation-retained')
        return self._append(event)

    def records(self):
        if not self.path.exists():return []
        with self.path.open('rb') as stream:
            fcntl.flock(stream,fcntl.LOCK_SH);return self._read(stream)


def playback_budget(prepared):
    spec=prepared['spec'].get('playback_budget')
    require(isinstance(spec,dict),'Physical playback requires a durable campaign budget')
    require(Path(spec['ledger']).resolve()==PLAYBACK_LEDGER.resolve(),'Playback must use the shared durable song ledger')
    ledger=PlaybackLedger(spec['ledger'],spec['campaign'])
    require(ledger.campaign['freeze_sha256']==prepared['freeze']['freeze_sha256'],'Playback campaign is stale')
    trial=spec['trial_id']
    ledger.reserve(trial,prepared['media'],arm=prepared['arm'],seconds=prepared['hops']*64/12800)
    class Reservation:
        def complete(self,success,player_log):ledger.complete(trial,success=success,player_log=player_log)
    return Reservation()


class CampaignPlaylist:
    """One owned, bounded playlist using AEL's existing media-clock Player.

    Constructing is read-only. Only explicit start() begins playback; the admitted
    endurance collector calls it after obtaining its existing sole target owner.
    """
    def __init__(self,spec,out,*,player_factory=None,now=time.monotonic,pause=time.sleep):
        require(isinstance(spec,dict),'Explicit playlist binding required')
        require(Path(spec['ledger']).resolve()==PLAYBACK_LEDGER.resolve(),'Playlist requires shared durable ledger')
        self.ledger=PlaybackLedger(spec['ledger'],spec['campaign'])
        self.tasks=[t for t in self.ledger.campaign['tasks'] if t['phase']=='endurance_playback']
        require(len(self.tasks)==17 and all(t['seconds']==t['media_seconds']==60 for t in self.tasks) and
                len({t['song_key'] for t in self.tasks})==3,'Expected17 approved60s tracks fromthree songs')
        if player_factory is None:
            from ael.prism_drive import Player
            player_factory=Player
        from ael.prism_drive import host_boot_session
        self.host_boot_session=host_boot_session();self.acquisition_nonce=secrets.token_hex(32)
        self.factory=player_factory;self.now=now;self.pause=pause;self.out=Path(out)
        self.cancel=threading.Event();self.thread=None;self.error=None;self.completed=[]

    def start(self):
        require(self.thread is None,'Playlist already started')
        self.out.mkdir(parents=True,exist_ok=False)
        self.thread=threading.Thread(target=self._run,name='titan-approved-playlist',daemon=True)
        self.thread.start();return self

    def _run(self):
        started=self.now()
        try:
            for index,task in enumerate(self.tasks):
                require(not self.cancel.is_set(),'Playlist cancelled')
                require(self.now()-started<1100,'Playlist exceeded bounded campaign time')
                log=self.out/f'track-{index+1:02d}.jsonl'
                self.ledger.reserve(task['id'],task['media']['path'],seconds=60)
                player=None;success=False
                try:
                    player=self.factory(Path(task['media']['path']),log,input_gain=1.0,cancel_event=self.cancel)
                    metadata=player.start
                    require(metadata.get('clock')=='CLOCK_UPTIME_RAW' and metadata.get('input_gain')==1 and
                            metadata.get('file_rate',0)>0 and metadata.get('frames',0)/metadata['file_rate']==60,'Playlist player gain/rate/duration changed')
                    track_start=self.now()
                    while not player.done:
                        require(not self.cancel.is_set(),'Playlist cancelled')
                        require(self.now()-track_start<=70,'Playlist track exceeded70s deadline')
                        if player.error:raise ValueError('Playlist player failed: '+str(player.error))
                        self.pause(.02)
                    if player.error:raise ValueError('Playlist player failed: '+str(player.error))
                    player.close();player=None;success=True
                    self.completed.append(task['id'])
                finally:
                    try:
                        if player is not None:player.abort()
                    finally:self.ledger.complete(task['id'],success=success,player_log=log,acquisition_nonce=self.acquisition_nonce)
            write_new(self.out/'result.json',dict(completed=self.completed,ledger=str(self.ledger.path),scope='PLAYER_ONLY; no acoustic or optical claim'))
        except Exception as exc:
            self.error=exc
            write_new(self.out/'failure.json',dict(error=str(exc),completed=self.completed,ledger=str(self.ledger.path)))

    def check(self):
        if self.error:raise ValueError('Approved playlist failed: '+str(self.error)) from self.error
        return dict(completed=len(self.completed),running=self.thread is not None and self.thread.is_alive())

    def finish(self,timeout=60):
        require(self.thread is not None,'Playlist was not started')
        self.thread.join(timeout);self.check()
        require(not self.thread.is_alive() and len(self.completed)==17,'Playlist remains incomplete')
        return self.check()

    def stop(self):
        self.cancel.set()
        if self.thread is not None:self.thread.join(8)
        require(self.thread is None or not self.thread.is_alive(),'Owned playlist did not stop')


def verify_endurance(window_logs, gap_files, *, playback_ledger=None, acquisition_nonce=None):
    """Check actual bounded window/gap evidence; retain optical/music limits."""
    from ael.prism_completion import require_healthy
    require(len(window_logs)==15 and len(gap_files)==14,'Missing fifteen endurance windows/fourteen gaps')
    windows=[];sources=set();identity=None;bridges=[];host_intervals=[];host_boots=set();nonce_valid=True
    def point(p):
        nonlocal identity
        info=p['identity'];require_healthy(info,identity)
        if identity is None:identity=info
        snap,tx,drive=p['snapshot'],p['transmitter'],p['drive']
        require(not drive.get('active') and drive.get('phase')=='idle' and drive.get('live_source') in (0,1),'Replay active or source missing during endurance')
        sources.add(drive['live_source'])
        require(tx.get('schema')=='prism.titan.transmitter.v2' and all(tx.get(k)==0 for k in ('first_fault','failures','last_fsp_error','pattern_requested')),'Endurance transmitter fault')
        for key in ('capture_time_us','sample_end','hops','rejected_hops','logical_frame','epoch'):
            require(type(snap.get(key)) is int and snap[key]>=0,'Missing endurance snapshot counter')
        require(type(tx.get('wire_reset_completions')) is int and tx['wire_reset_completions']>=0,'Missing transmitter progress')
        return p
    def link(a,b,advance=False):
        x,y=a['snapshot'],b['snapshot']
        require(x['epoch']==y['epoch'] and x['rejected_hops']==y['rejected_hops'],'Endurance capture epoch/fault changed')
        for key in ('capture_time_us','sample_end','hops','logical_frame'):
            require(y[key]>=x[key] and (not advance or y[key]>x[key]),'Endurance counter regression/stall')
        require(b['transmitter']['wire_reset_completions']>=a['transmitter']['wire_reset_completions'] and
                (not advance or b['transmitter']['wire_reset_completions']>a['transmitter']['wire_reset_completions']),'Endurance output reset/stall')
    for path in window_logs:
        rows=[json.loads(l) for l in Path(path).read_text().splitlines()]
        begins=[r for r in rows if r.get('event')=='begin'];ends=[r for r in rows if r.get('event')=='result']
        require(len(begins)==len(ends)==1 and not any(r.get('event')=='failure' for r in rows),'Failed/incomplete endurance window')
        begin=begins[0];require(begin.get('hardware_access') is True and begin['request'].get('kind')=='measure','Host-only/non-measure evidence cannot qualify endurance')
        nonce_valid=nonce_valid and acquisition_nonce is not None and begin['request'].get('acquisition_nonce')==acquisition_nonce
        result=ends[0]['data'];require(all(result.get(k) is True for k in ('proxy_budget_met','hop_deadline_met','render_deadline_met')),'Endurance timing budget failed')
        before=next(r for r in rows if r.get('event')=='progress_before')
        after=next(r for r in rows if r.get('event')=='progress_after')
        source=0 if begin['request']['live_source']=='A' else 1
        drive=dict(active=False,phase='idle',live_source=source)
        first=point(dict(identity=begin['identity'],snapshot=before['snapshot'],transmitter=before['transmitter'],drive=drive))
        last=point(dict(identity=result['final_identity'],snapshot=after['snapshot'],transmitter=after['transmitter'],drive=drive))
        health=[point(r) for r in rows if r.get('event')=='health']
        require(health,'No measured endurance health samples')
        require(all(r['drive']['live_source']==source for r in health),'Live source differs from requested endurance window')
        if all(r.get('host_clock')=='CLOCK_UPTIME_RAW' and type(r.get('host_uptime_ns')) is int for r in (before,after)):
            require(after['host_uptime_ns']>before['host_uptime_ns'],'Endurance host clock regressed')
            host_intervals.append((before['host_uptime_ns'],after['host_uptime_ns']))
            host_boots.update(r.get('host_boot_session') for r in (before,after))
        ordered=[first,*health,last]
        for a,b in zip(ordered,ordered[1:]):link(a,b)
        link(first,last,True)
        elapsed=last['snapshot']['capture_time_us']-first['snapshot']['capture_time_us']
        require(59000000<=elapsed<=61000000 and begin['request']['seconds']==60,'Endurance requires measured sixty-second windows')
        windows.append((first,last,elapsed))
    covered=sum(w[2] for w in windows)
    for index,path in enumerate(gap_files):
        gap=json.loads(Path(path).read_text())
        require(gap.get('schema')=='titan.endurance.gap.v1' and gap.get('hardware_access') is True,'Missing actual autonomous gap evidence')
        nonce_valid=nonce_valid and gap.get('acquisition_nonce')==acquisition_nonce
        first,last=point(gap['before']),point(gap['after']);link(first,last,True)
        if first.get('host_clock')==last.get('host_clock')=='CLOCK_UPTIME_RAW':
            a,b=first.get('host_after_uptime_ns'),last.get('host_before_uptime_ns')
            require(type(a) is int and type(b) is int and b>a,'Invalid gap host acquisition bracket')
            host_intervals.append((a,b))
            host_boots.update(p.get('host_boot_session') for p in (first,last))
        require(4000000<=last['snapshot']['capture_time_us']-first['snapshot']['capture_time_us']<=6000000,'Endurance requires five-second sampled gaps')
        covered+=last['snapshot']['capture_time_us']-first['snapshot']['capture_time_us']
        for a,b in ((windows[index][1],first),(last,windows[index+1][0])):
            link(a,b)
            unobserved=b['snapshot']['capture_time_us']-a['snapshot']['capture_time_us']
            bridges.append(unobserved)
    require(covered>=900000000,'Less than15minutes of evidenced endurance coverage')
    music={'status':'UNMEASURED','reason':'No completed approved playback ledger provided'}
    if playback_ledger is not None:
        records=playback_ledger.records();completed=[r for r in records if r['event']=='complete' and r['success'] and r['player_log'] and r.get('acquisition_nonce')==acquisition_nonce and acquisition_nonce is not None]
        seconds=0;heard=set();playback_intervals=[];song_intervals=[]
        for event in completed:
            if event['trial_id'] not in playback_ledger.tasks:continue
            task=playback_ledger.tasks[event['trial_id']]
            if task['phase']!='endurance_playback':continue
            rows=[json.loads(l) for l in bound(event['player_log']).read_text().splitlines()]
            starts=[r for r in rows if r.get('event')=='start'];ends=[r for r in rows if r.get('event')=='end']
            require(len(starts)==len(ends)==1 and starts[0]['frames']==ends[0]['frames'],'Incomplete player evidence')
            require(starts[0].get('input_gain')==1 and starts[0].get('clock')=='CLOCK_UPTIME_RAW','Unbound player gain/clock')
            host_boots.add(starts[0].get('host_boot_session'))
            require(starts[0].get('wav')==task['media']['path'] and binding(starts[0]['wav'])==task['media'],'Player used other media')
            require(starts[0]['frames']/starts[0]['file_rate']<=task['seconds']+.01,'Playback exceeded reserved duration')
            seconds+=starts[0]['frames']/starts[0]['file_rate'];heard.add(task['song_key'])
            clocks=[r for r in rows if r.get('event')=='clock']
            require(clocks,'Player has no measured render-clock history')
            require(all(type(r.get('render_uptime_ns')) is int and math.isfinite(r.get('render_sample',float('nan'))) for r in clocks),'Malformed player clock')
            require(all(b['render_uptime_ns']>=a['render_uptime_ns'] and b['render_sample']>=a['render_sample'] for a,b in zip(clocks,clocks[1:])),'Player clock regressed')
            origins=[r['render_uptime_ns']-r['render_sample']/starts[0]['file_rate']*1e9 for r in clocks]
            # Conservative overlap of actual render-clock estimates. This is
            # player output timing; no acoustic or photon timing is inferred.
            interval=(max(origins),min(origins)+starts[0]['frames']/starts[0]['file_rate']*1e9)
            playback_intervals.append(interval);song_intervals.append((task['song_key'],*interval))
        require(seconds>=900 and len(heard)>=3,'Missing15minute varied approved playback evidence')
        merged=[]
        for a,b in sorted(playback_intervals):
            require(b>a,'Invalid player coverage interval')
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        host_merged=[]
        for a,b in sorted(host_intervals):
            if host_merged and a<=host_merged[-1][1]:host_merged[-1]=(host_merged[-1][0],max(b,host_merged[-1][1]))
            else:host_merged.append((a,b))
        overlap=sum(max(0,min(b,d)-max(a,e)) for a,b in host_merged for e,d in merged)/1e9
        overlapping_songs={song for song,a,b in song_intervals if any(min(b,d)>max(a,e) for e,d in host_merged)}
        same_acquisition=nonce_valid and len(host_boots)==1 and None not in host_boots
        music={'status':'PLAYER_COMPLETION_EVIDENCE','seconds':seconds,'distinct_songs':len(heard),
               'distinct_songs_overlapping_observation':len(overlapping_songs),
               'overlap_with_observed_host_seconds':overlap,'temporal_alignment':'HOST_RENDER_CLOCK_OVERLAP' if overlap>=900 and len(overlapping_songs)>=3 and same_acquisition else 'UNMEASURED_OR_INSUFFICIENT',
               'acoustic_alignment':'UNMEASURED'}
    return dict(scope='CONTINUOUS_COUNTER_HISTORY_WITH_SAMPLED_GAPS; no optical proof',covered_seconds=covered/1e6,
                boundary_unobserved_us=bridges,source='LIVE_A' if sources=={0} else 'LIVE_D' if sources=={1} else 'MIXED_LIVE_A_D',
                music=music,optical_verified=False,identity=identity)


def main():
    parser=argparse.ArgumentParser(description='Offline Titan comparison preparation; no hardware/playback')
    parser.add_argument('--freeze',required=True,type=Path);parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();result=prepare_campaign(args.freeze,args.out)
    print(json.dumps(dict(scope='PREPARED_ONLY',trials=len(result['tasks']),planned_seconds_by_song=result['planned_seconds_by_song'])))


if __name__=='__main__':main()
