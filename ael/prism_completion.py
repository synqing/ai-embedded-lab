"""Titan golden/cost operations inside AEL's existing, admitted serial owner.

This module never opens a port, programmes a target, plays audio or admits an
image. The gateway provides the identity-checked exchange and output gate.
"""
import hashlib
import json
import math
from pathlib import Path
import struct
import time

from ael.prism_drive import Refusal, bound_file, digest, uint

PROBE, COST, PREAMBLE = 0x50524406, 0x50524407, 0x50524408
STAGES = ('capture', 'resample', 'analysis', 'proxy', 'observer', 'hop_total',
          'render_including_pack', 'pack', 'usb', 'active_loop')
ATOL, RTOL = 1e-5, 1e-4


def prepare(spec):
    if not isinstance(spec, dict) or spec.get('kind') not in ('golden', 'measure'):
        raise Refusal('Unknown Titan completion operation')
    result = dict(spec)
    if spec['kind'] == 'golden':
        pcm = bound_file(spec.get('pcm')).read_bytes()
        path = bound_file(spec.get('reference'))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if not rows or rows[0].get('schema') != 'titan-level-trace.v1':
            raise Refusal('Frozen level_trace reference required')
        meta, expected = rows[0], rows[1:]
        if meta.get('sample_rate') != 12800 or meta.get('hop_samples') != 64:
            raise Refusal('Golden PCM must be12800Hz/64 samples')
        if not pcm or len(pcm) % 128 or len(pcm) > 24000 * 128 or len(expected) != len(pcm)//128:
            raise Refusal('Empty, oversized, partial or mismatched golden PCM')
        if spec.get('reference_pcm_sha256') != hashlib.sha256(pcm).hexdigest():
            raise Refusal('Golden reference is not bound to PCM bytes')
        proxy_hash = digest(spec.get('proxy_source_sha256'))
        if meta.get('percussion_proxy_h_sha256') != proxy_hash:
            raise Refusal('Golden proxy source mismatch')
        for i, row in enumerate(expected):
            if row.get('hop') != i or row.get('core_valid') is not True:
                raise Refusal('Golden probe needs ordered Core-accepted hops')
            if any(type(row.get(k)) not in (float, int) or not math.isfinite(row[k]) for k in ('d_raw', 'd_level')):
                raise Refusal('Non-finite or absent golden value')
        result.update(pcm_bytes=pcm, expected=expected, trial=uint(spec.get('trial'), positive=True))
    else:
        seconds = spec.get('seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 120:
            raise Refusal('Measurement window must be1..120seconds')
        if spec.get('live_source') not in ('A', 'D') or type(spec.get('observer_enabled')) is not bool:
            raise Refusal('Explicit live source and observer state required')
    return result


def decode_probe(body, trial, sequence, active):
    if len(body) != 48:
        raise Refusal('Incomplete golden response')
    header = struct.unpack_from('<4I', body)
    if header != (trial, sequence, int(active), 12800):
        raise Refusal('Golden response identity/order/rate mismatch')
    values = struct.unpack_from('<8f', body, 16)
    if not all(math.isfinite(x) for x in values):
        raise Refusal('Non-finite target golden result')
    return dict(zip(('r_low', 'r_high', 'f_low', 'f_high', 't_low', 't_high', 'd_raw', 'd_level'), values))


def bin_bounds(index):
    if index < 8:
        return index, index
    if index < 24:
        raise Refusal('Unused histogram bin is populated')
    exponent, sub = divmod(index, 8)
    width = 1 << (exponent - 3)
    return (1 << exponent) + sub * width, (1 << exponent) + (sub + 1) * width - 1


def decode_cost(body, stage):
    if len(body) != 1064:
        raise Refusal('Incomplete cost response')
    which, hz, count, total, maximum, overflow, bins, version = struct.unpack_from('<IIQQIIII', body)
    histogram = list(struct.unpack_from('<256I', body, 40))
    if which != stage or not hz or bins != 256 or version != 1 or overflow or sum(histogram) != count:
        raise Refusal('Invalid cost identity/count/overflow')
    for i, n in enumerate(histogram):
        if n:
            lo, hi = bin_bounds(i)
            if lo > maximum:
                raise Refusal('Histogram exceeds measured maximum')
    if count:
        lo,hi=bin_bounds(max(i for i,n in enumerate(histogram) if n))
        if not lo<=maximum<=hi or not sum(n*bin_bounds(i)[0] for i,n in enumerate(histogram) if n)<=total<=sum(n*bin_bounds(i)[1] for i,n in enumerate(histogram) if n):
            raise Refusal('Cost maximum/sum inconsistent with histogram')
    elif maximum or total:
        raise Refusal('Nonzero cost without samples')
    return dict(stage=STAGES[stage], clock_hz=hz, count=count, sum_cycles=total,
                maximum_cycles=maximum, histogram=histogram)


def cost_delta(before, after):
    if before['stage'] != after['stage'] or before['clock_hz'] != after['clock_hz']:
        raise Refusal('Cost clock/stage changed')
    hist = [b-a for a,b in zip(before['histogram'],after['histogram'])]
    count = after['count'] - before['count']
    total = after['sum_cycles'] - before['sum_cycles']
    if min(hist) < 0 or count < 0 or total < 0 or sum(hist) != count or after['maximum_cycles'] < before['maximum_cycles']:
        raise Refusal('Counter reset or inconsistent cost history')
    factor = 1e6 / after['clock_hz']
    percentiles = {}
    for percentile in (50,95,99):
        threshold = (count*percentile + 99)//100
        cumulative = 0
        percentiles[f'p{percentile}_us_interval'] = None
        if count:
            for i,n in enumerate(hist):
                cumulative += n
                if cumulative >= threshold:
                    percentiles[f'p{percentile}_us_interval'] = [x*factor for x in bin_bounds(i)]
                    break
    return dict(stage=after['stage'], count=count, mean_us=total/count*factor if count else None,
                cumulative_max_us=after['maximum_cycles']*factor,
                max_scope='since boot; upper bound for this window', **percentiles)


def require_healthy(info, before=None):
    if info.get('initialisation_failed') is not False or info.get('output_timeouts') != 0:
        raise Refusal('Native startup/output fault')
    if info.get('capture_errors') != [0,0] or info.get('output_last_fsp_error') != 0:
        raise Refusal('Native capture/driver fault')
    if before:
        for key in ('uid','boot_id','build_source_sha256','schema_sha256','clock_hz'):
            if info.get(key) != before.get(key):
                raise Refusal('Native identity/boot/clock changed')
        for key in ('capture_clock_rejections','capture_restart_attempts','output_recovery_attempts'):
            if type(info.get(key)) is not int or info[key] != before.get(key):
                raise Refusal('Native counter fault: '+key)


def execute(exchange, manifest, spec, out, initial, *, monotonic=time.monotonic, pause=time.sleep):
    """Caller holds the one AEL lock and has bound UID/schema/source/boot."""
    prepared = prepare(spec)
    require_healthy(initial)
    boot = initial['boot_id']
    start = monotonic()
    path = Path(out)/'titan-completion.jsonl'
    def current():
        info = json.loads(exchange(1));require_healthy(info,initial);return info
    with path.open('x') as log:
        def record(row):
            log.write(json.dumps(row,allow_nan=False)+'\n');log.flush()
        record({'event':'begin','identity':initial,'request':spec,'hardware_access':True})
        try:
            preamble = json.loads(exchange(PREAMBLE,struct.pack('<I',boot)))
            record({'event':'preamble','data':preamble})
            if prepared['kind'] == 'golden':
                # Exact proxy source binding comes from the admitted build's
                # lane-input hashes, not an arbitrary request declaration.
                build = json.loads(bound_file(manifest['build_receipt']).read_text())
                inputs = build.get('inputs', {}).get('lane', {})
                if inputs.get('platform/titan/percussion_proxy.h') != prepared['proxy_source_sha256']:
                    raise Refusal('Admitted image does not bind the golden proxy source')
                trial = prepared['trial']
                def command(op,seq,pcm=b''):
                    body=exchange(PROBE,struct.pack('<6I',boot,op,trial,seq,12800,64 if pcm else 0)+pcm)
                    return decode_probe(body,trial,seq+(op==1),op!=2)
                command(0,0)
                errors={'d_raw':0.,'d_level':0.}
                for i,expected in enumerate(prepared['expected']):
                    if monotonic()-start>120:
                        raise Refusal('Golden acquisition exceeded120s')
                    actual=command(1,i,prepared['pcm_bytes'][i*128:(i+1)*128])
                    record({'event':'golden','hop':i,'actual':actual,'expected':expected})
                    for field in errors:
                        error=abs(actual[field]-expected[field]);errors[field]=max(errors[field],error)
                        if error>ATOL+RTOL*abs(expected[field]):
                            raise Refusal('Target golden mismatch at hop '+str(i)+' '+field)
                command(2,len(prepared['expected']))
                result={'kind':'golden','hops':len(prepared['expected']),'maximum_absolute_error':errors,
                        'absolute_tolerance':ATOL,'relative_tolerance':RTOL,
                        'scope':'isolated production proxy computation, not microphone/input or optical parity'}
            else:
                state=json.loads(exchange(0x50524403,struct.pack('<I',boot)))
                if state.get('active') or state.get('phase') != 'idle':
                    raise Refusal('Descriptor session must finish before live measurement')
                exchange(0x50524405,struct.pack('<II',boot,0 if prepared['live_source']=='A' else 1))
                exchange(PREAMBLE,struct.pack('<II',boot,int(prepared['observer_enabled'])))
                from ael.prism_native import snapshot, window
                def progress():
                    snap=snapshot(exchange(23),manifest['source_binding_hash'])
                    tx=json.loads(exchange(0x50524c02,struct.pack('<I',boot)))
                    if tx.get('schema')!='prism.titan.transmitter.v2' or any(tx.get(k)!=0 for k in ('first_fault','failures','last_fsp_error','pattern_requested')):
                        raise Refusal('Transmitter fault or fixture pattern active')
                    if type(tx.get('wire_reset_completions')) is not int:
                        raise Refusal('Missing sampled transmitter completion count')
                    return snap,tx
                first_snapshot,first_tx=progress()
                record({'event':'progress_before','snapshot':first_snapshot,'transmitter':first_tx})
                before=[decode_cost(exchange(COST,struct.pack('<II',boot,i)),i) for i in range(len(STAGES))]
                record({'event':'cost_before','data':before})
                end=monotonic()+prepared['seconds'];samples=0
                while monotonic()<end:
                    info=current();status=json.loads(exchange(0x50524403,struct.pack('<I',boot)))
                    if status.get('active') or status.get('live_source') != (0 if prepared['live_source']=='A' else 1):
                        raise Refusal('Replay revived or live source changed')
                    snap,tx=progress()
                    if snap['epoch']!=first_snapshot['epoch'] or snap['rejected_hops']!=first_snapshot['rejected_hops'] or tx['wire_reset_completions']<first_tx['wire_reset_completions']:
                        raise Refusal('Capture gap, rejected hop or transmitter counter reset')
                    record({'event':'health','identity':info,'drive':status,'snapshot':snap,'transmitter':tx});samples+=1
                    pause(min(.25,max(0,end-monotonic())))
                after=[decode_cost(exchange(COST,struct.pack('<II',boot,i)),i) for i in range(len(STAGES))]
                record({'event':'cost_after','data':after})
                final_snapshot,final_tx=progress()
                record({'event':'progress_after','snapshot':final_snapshot,'transmitter':final_tx})
                audio_window=window(first_snapshot,final_snapshot)
                if audio_window['rejected_hop_delta']!=0 or audio_window['logical_frame_delta']<=0 or final_tx['wire_reset_completions']<=first_tx['wire_reset_completions']:
                    raise Refusal('Lost/rejected audio or stalled render/transmitter')
                costs=[cost_delta(a,b) for a,b in zip(before,after)]
                required=('capture','resample','analysis','proxy','hop_total','render_including_pack','pack','usb','active_loop')
                if any(c['count']==0 for c in costs if c['stage'] in required):
                    raise Refusal('Missing stage measurement')
                result={'kind':'measure','health_samples':samples,'costs':costs,'physical_latency':'UNMEASURED',
                        'audio_window':audio_window,'sampled_wire_reset_completion_delta':final_tx['wire_reset_completions']-first_tx['wire_reset_completions'],
                        'timing_scope':'Measured stage execution only; scheduler response deadlines and physical latency require separate verification',
                        'proxy_budget_met':costs[3]['p99_us_interval'][1]<=1000,
                        'hop_deadline_met':costs[5]['cumulative_max_us']<=5000,
                        'render_deadline_met':costs[6]['cumulative_max_us']<=10000,
                        'optical_verified':False}
            result['final_identity']=current();record({'event':'result','data':result})
            return result
        except Exception as exc:
            record({'event':'failure','message':str(exc)})
            raise


def advancement(ratings):
    """Frozen founder rule; ties are valid ratings but do not count as wins."""
    if len(ratings)!=3 or len({r.get('song') for r in ratings})!=3:
        return {'decision':'AWAITING_OWNER_REVIEW','reason':'Three distinct song ratings required'}
    for row in ratings:
        if row.get('reviewer')!='Captain' or row.get('compared_against')!='I' or not row.get('physical_evidence'):
            return {'decision':'AWAITING_OWNER_REVIEW','reason':'Actual incumbent physical ratings required'}
        if any(row.get(k) not in ('candidate','incumbent','tie') for k in ('musical_relationship','overall_appearance')) or type(row.get('severe_artifact_regression')) is not bool:
            raise Refusal('Missing or invalid owner rating')
    wins=sum(r['musical_relationship']==r['overall_appearance']=='candidate' for r in ratings)
    return {'decision':'ADVANCE_ELIGIBLE' if wins>=2 and not any(r['severe_artifact_regression'] for r in ratings) else 'RETAIN_DONOR',
            'songs_won_on_both_axes':wins,'scope':'founder preference only; engineering gates remain separate'}
