"""Continuous-owner device observation in bounded diagnostic windows.

The admitted gateway owns the port throughout. An optional bound playlist uses
the existing player and durable song ledger; its actual clock evidence is checked
against this run. Without a playlist, approved music remains unmeasured.
No optical or musical-value verdict is inferred from software counters.
"""
import hashlib
import json
import math
from pathlib import Path
import struct
import time

from ael.prism_drive import Refusal, uptime_ns


def prepare(spec):
    if not isinstance(spec, dict) or spec.get('kind') != 'endurance':
        raise Refusal('Expected endurance operation')
    windows = spec.get('windows')
    if not isinstance(windows, list) or len(windows) != 15:
        raise Refusal('Endurance requires fifteen bounded sixty-second windows')
    from ael.prism_completion import prepare as prepare_window
    for row in windows:
        if row.get('kind') != 'measure' or row.get('seconds') != 60:
            raise Refusal('Endurance window must measure sixty seconds')
        prepare_window(row)
    if spec.get('gap_seconds') != 5:
        raise Refusal('Endurance uses five-second diagnostic-free gaps')
    if 'playlist' in spec:
        from ael.prism_campaign import CampaignPlaylist
        CampaignPlaylist(spec['playlist'], Path('.')/'unused-playlist-preflight')
    return dict(spec)


def execute(exchange, manifest, spec, out, initial, *, monotonic=time.monotonic,
            pause=time.sleep, measure=None, verifier=None, playlist_factory=None,
            deadline=None, cancel_event=None, cleanup_seconds=8):
    from ael.prism_completion import execute as measure_default, require_healthy
    from ael.prism_native import snapshot, window
    from ael.prism_campaign import verify_endurance, CampaignPlaylist
    from ael.prism_drive import host_boot_session
    started = monotonic()
    cutoff = started + 1100
    if deadline is not None:
        if type(deadline) not in (int,float) or not math.isfinite(deadline):
            raise Refusal('Invalid endurance absolute deadline')
        cutoff = min(cutoff,deadline)
    if type(cleanup_seconds) not in (int,float) or not 0 < cleanup_seconds <= 8:
        raise Refusal('Owned playlist cleanup reserve must be bounded by eight seconds')
    prepared = prepare(spec)
    require_healthy(initial)
    measure = measure or measure_default
    verifier = verifier or verify_endurance
    playlist_factory = playlist_factory or CampaignPlaylist
    host_boot = host_boot_session()
    root = Path(out) / 'endurance'
    root.mkdir(exist_ok=False)
    boot = initial['boot_id']
    segments, gaps = [], []
    playlist = None
    nonce = None
    primary_failure = False
    def check_deadline():
        if cancel_event is not None and cancel_event.is_set():
            raise Refusal('Endurance cancelled; preserve recovery reserve')
        if monotonic() >= cutoff:
            raise Refusal('Endurance absolute deadline exhausted; bounded campaign duration')

    original_exchange = exchange
    def exchange(opcode,payload=b'',*,absolute_deadline=None,cancel_event=None):
        check_deadline()
        child_cutoff = min(cutoff,absolute_deadline) if absolute_deadline is not None else cutoff
        reply = original_exchange(opcode,payload,absolute_deadline=child_cutoff,
                                  cancel_event=cancel_event or collector_cancel)
        check_deadline()
        return reply
    exchange.__wrapped__ = original_exchange
    collector_cancel = cancel_event

    def monitored_pause(seconds):
        check_deadline()
        if playlist is not None: playlist.check()
        if seconds > cutoff-monotonic():
            raise Refusal('Endurance wait exceeds absolute deadline')
        if cancel_event is not None and pause is time.sleep:
            if cancel_event.wait(seconds):
                raise Refusal('Endurance cancelled during wait')
        else:
            pause(seconds)
        check_deadline()
        if playlist is not None: playlist.check()

    def save(name, row):
        p = root/name
        with p.open('x') as f:
            json.dump(row, f, indent=2, allow_nan=False)
        return {'path':str(p.resolve()), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

    observation_count = 0
    def observe(source):
        nonlocal observation_count
        observation_count += 1
        row = {'host_before_uptime_ns':uptime_ns(),'host_clock':'CLOCK_UPTIME_RAW',
               'host_boot_session':host_boot,'raw_replies':{},'source':source}
        try:
            for label,opcode,payload in (('identity',1,b''),('snapshot',23,b''),
                    ('transmitter',0x50524c02,struct.pack('<I',boot)),
                    ('drive',0x50524403,struct.pack('<I',boot))):
                reply = exchange(opcode,payload)
                row['raw_replies'][label] = reply.hex()
                row[label] = snapshot(reply,manifest['source_binding_hash']) if label == 'snapshot' else json.loads(reply)
        except BaseException as exc:
            row['observation_error'] = str(exc)
            if hasattr(exc,'partial'):row['raw_partial_reply'] = exc.partial.hex()
            raise
        finally:
            row['host_after_uptime_ns'] = uptime_ns()
            save(f'health-{observation_count:03d}.json',row)
        # The decoded observation is durable before any acceptance decision.
        require_healthy(row['identity'],initial)
        tx,drive = row['transmitter'],row['drive']
        if (tx.get('schema') != 'prism.titan.transmitter.v2' or
            any(tx.get(k) != 0 for k in ('first_fault','failures','last_fsp_error','pattern_requested')) or
            type(tx.get('wire_reset_completions')) is not int):
            raise Refusal('Endurance transmitter fault or missing completion evidence')
        if drive.get('active') or drive.get('phase') != 'idle' or drive.get('live_source') != (source=='D'):
            raise Refusal('Endurance live source changed or replay revived')
        return row

    try:
        check_deadline()
        if 'playlist' in prepared:
            prior=json.loads(exchange(0x50524403,struct.pack('<I',boot)))
            if prior.get('active') or prior.get('phase')!='idle' or prior.get('live_source') not in (0,1):
                raise Refusal('Endurance must start from idle live input before playback')
            save('before-playlist.json',observe('D' if prior['live_source'] else 'A'))
            playlist = playlist_factory(prepared['playlist'], root/'playlist', now=monotonic,
                                        absolute_deadline=cutoff,cancel_event=cancel_event)
            nonce = playlist.acquisition_nonce
            playlist.start()
        for index, request in enumerate(prepared['windows']):
            # One continuous owner; no session close, rebind, boot or counter reset.
            child = root/f'window-{index+1:02d}'
            child.mkdir()
            request = dict(request, acquisition_nonce=nonce)
            result = measure(exchange, manifest, request, child, initial,
                             monotonic=monotonic, pause=monitored_pause,
                             deadline=cutoff,cancel_event=cancel_event)
            path = child/'titan-completion.jsonl'
            segments.append({'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            save(f'window-{index+1:02d}-result.json',result)
            check_deadline()
            if not all(result.get(k) is True for k in ('proxy_budget_met','hop_deadline_met','render_deadline_met')):
                raise Refusal('Endurance stage timing budget failed')
            if index == len(prepared['windows'])-1:
                break
            before = observe(request['live_source'])
            gap_start = monotonic()
            monitored_pause(prepared['gap_seconds'])  # Deliberately no diagnostic exchanges here.
            after = observe(request['live_source'])
            gap = {'schema':'titan.endurance.gap.v1','hardware_access':True,'before':before,'after':after,
                   'host_elapsed_seconds':monotonic()-gap_start,'acquisition_nonce':nonce,
                   'diagnostic_queries_between_endpoints':0,
                   'optical_verified':False}
            gaps.append(save(f'gap-{index+1:02d}.json',gap))
            audio = window(before['snapshot'],after['snapshot'])
            if (audio['rejected_hop_delta'] or audio['logical_frame_delta']<=0 or
                after['transmitter']['wire_reset_completions'] <= before['transmitter']['wire_reset_completions']):
                raise Refusal('Endurance stalled or lost audio during diagnostic gap')
            check_deadline()
        if playlist is not None:
            playlist.finish(timeout=max(0,min(60,cutoff-monotonic())))
            check_deadline()
            save('after-playlist.json',observe(prepared['windows'][-1]['live_source']))
        check_deadline()
        verification = verifier([r['path'] for r in segments], [r['path'] for r in gaps],
                                playback_ledger=playlist.ledger if playlist is not None else None,
                                acquisition_nonce=nonce)
        result = {'kind':'endurance','segments':segments,'gaps':gaps,
                  'diagnostic_seconds_requested':900,'elapsed_host_seconds':monotonic()-started,
                  'absolute_deadline':cutoff,'owned_cleanup_reserve_seconds':cleanup_seconds,
                  'continuous_serial_owner':True,'acquisition_nonce':nonce,'verification':verification,
                  'playback_evidence':verification.get('music',{}),
                  'physical_latency':'UNMEASURED','optical_verified':False,
                  'device_counter_history_pass':True,
                  'approved_music_coverage_pass':verification.get('music',{}).get('temporal_alignment')=='HOST_RENDER_CLOCK_OVERLAP',
                  'endurance_pass':False,
                  'disposition':'DEVICE_COUNTER_HISTORY_VERIFIED; OPTICAL_CONFIRMATION_AND_ANY_MISSING_MUSIC_EVIDENCE_REMAIN'}
        save('collection.json',result)
        return result
    except BaseException as exc:
        primary_failure=True
        save('failure.json',{'error':str(exc),'segments':segments,'gaps':gaps,
                             'elapsed_host_seconds':monotonic()-started,'absolute_deadline':cutoff,'endurance_pass':False})
        raise
    finally:
        if playlist is not None:
            try:
                cleanup_cutoff = monotonic()+cleanup_seconds
                playlist.stop(timeout=cleanup_seconds,absolute_deadline=cleanup_cutoff)
            except Exception as cleanup_error:
                save('cleanup-failure.json',{'error':str(cleanup_error),'endurance_pass':False})
                if not primary_failure:raise
