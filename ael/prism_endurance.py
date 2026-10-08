"""Continuous-owner device observation in bounded diagnostic windows.

The admitted gateway owns the port throughout. This collector does not start
music: actual approved playback evidence is a separate campaign requirement.
No optical or musical-value verdict is inferred from software counters.
"""
import hashlib
import json
from pathlib import Path
import struct
import time

from ael.prism_drive import Refusal


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
    return dict(spec)


def execute(exchange, manifest, spec, out, initial, *, monotonic=time.monotonic,
            pause=time.sleep, measure=None):
    from ael.prism_completion import execute as measure_default, require_healthy
    from ael.prism_native import snapshot, window
    prepared = prepare(spec)
    require_healthy(initial)
    measure = measure or measure_default
    root = Path(out) / 'endurance'
    root.mkdir(exist_ok=False)
    started = monotonic()
    boot = initial['boot_id']
    segments, gaps = [], []

    def save(name, row):
        p = root/name
        with p.open('x') as f:
            json.dump(row, f, indent=2, allow_nan=False)
        return {'path':str(p.resolve()), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

    def observe(source):
        identity = json.loads(exchange(1))
        require_healthy(identity, initial)
        snap = snapshot(exchange(23), manifest['source_binding_hash'])
        tx = json.loads(exchange(0x50524c02, struct.pack('<I',boot)))
        drive = json.loads(exchange(0x50524403, struct.pack('<I',boot)))
        if (tx.get('schema') != 'prism.titan.transmitter.v2' or
            any(tx.get(k) != 0 for k in ('first_fault','failures','last_fsp_error','pattern_requested')) or
            type(tx.get('wire_reset_completions')) is not int):
            raise Refusal('Endurance transmitter fault or missing completion evidence')
        if drive.get('active') or drive.get('phase') != 'idle' or drive.get('live_source') != (source=='D'):
            raise Refusal('Endurance live source changed or replay revived')
        return {'identity':identity, 'snapshot':snap, 'transmitter':tx, 'drive':drive}

    try:
        for index, request in enumerate(prepared['windows']):
            # One continuous owner; no session close, rebind, boot or counter reset.
            child = root/f'window-{index+1:02d}'
            child.mkdir()
            result = measure(exchange, manifest, request, child, initial,
                             monotonic=monotonic, pause=pause)
            path = child/'titan-completion.jsonl'
            segments.append({'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            save(f'window-{index+1:02d}-result.json',result)
            if not all(result.get(k) is True for k in ('proxy_budget_met','hop_deadline_met','render_deadline_met')):
                raise Refusal('Endurance stage timing budget failed')
            if index == len(prepared['windows'])-1:
                break
            before = observe(request['live_source'])
            gap_start = monotonic()
            pause(prepared['gap_seconds'])  # Deliberately no diagnostic exchanges here.
            after = observe(request['live_source'])
            gap = {'schema':'titan.endurance.gap.v1','hardware_access':True,'before':before,'after':after,
                   'host_elapsed_seconds':monotonic()-gap_start,
                   'diagnostic_queries_between_endpoints':0,
                   'optical_verified':False}
            gaps.append(save(f'gap-{index+1:02d}.json',gap))
            audio = window(before['snapshot'],after['snapshot'])
            if (audio['rejected_hop_delta'] or audio['logical_frame_delta']<=0 or
                after['transmitter']['wire_reset_completions'] <= before['transmitter']['wire_reset_completions']):
                raise Refusal('Endurance stalled or lost audio during diagnostic gap')
            if monotonic()-started > 1100:
                raise Refusal('Endurance observation exceeded bounded campaign duration')
        result = {'kind':'endurance','segments':segments,'gaps':gaps,
                  'diagnostic_seconds_requested':900,'elapsed_host_seconds':monotonic()-started,
                  'continuous_serial_owner':True,'playback_evidence':'REQUIRED_SEPARATELY',
                  'physical_latency':'UNMEASURED','optical_verified':False,
                  'endurance_pass':False,
                  'disposition':'AWAITING_RAW_CONTINUITY_AND_APPROVED_PLAYBACK_VERIFICATION'}
        save('collection.json',result)
        return result
    except Exception as exc:
        save('failure.json',{'error':str(exc),'segments':segments,'gaps':gaps,
                             'elapsed_host_seconds':monotonic()-started,'endurance_pass':False})
        raise
