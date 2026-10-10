"""Titan golden/cost operations inside AEL's existing, admitted serial owner.

This module never opens a port, programmes a target, plays audio or admits an
image. The gateway provides the identity-checked exchange and output gate.
"""
import hashlib
import base64
import json
import math
from pathlib import Path
import struct
import time

from ael.prism_drive import Refusal, bound_file, digest, uint, uptime_ns, host_boot_session

PROBE, COST, PREAMBLE = 0x50524406, 0x50524407, 0x50524408
STAGES = ('capture', 'resample', 'analysis', 'proxy', 'observer', 'hop_total',
          'render_including_pack', 'pack', 'usb', 'active_loop')
ATOL, RTOL = 1e-5, 1e-4
READINESS_MAX_SECONDS, FINAL_READOUT_RESERVE_SECONDS = 10., 5.


def prepare(spec):
    if isinstance(spec, dict) and spec.get('kind') == 'endurance':
        from ael.prism_endurance import prepare as prepare_endurance
        return prepare_endurance(spec)
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


def execute(exchange, manifest, spec, out, initial, *, monotonic=time.monotonic, pause=time.sleep, deadline=None):
    """Caller holds the one AEL lock and has bound UID/schema/source/boot."""
    if isinstance(spec, dict) and spec.get('kind') == 'endurance':
        if deadline is not None:
            raise Refusal('Endurance cannot use the bounded isolated completion deadline')
        from ael.prism_endurance import execute as execute_endurance
        return execute_endurance(exchange, manifest, spec, out, initial, monotonic=monotonic, pause=pause)
    prepared = prepare(spec)
    boot = initial['boot_id']
    start = monotonic()
    cutoff = start + 120
    if deadline is not None:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise Refusal('Invalid completion absolute deadline')
        cutoff = min(cutoff, deadline)
    exchange_cutoff = cutoff
    def check_deadline():
        if monotonic() >= min(cutoff,exchange_cutoff):
            raise Refusal('Completion absolute deadline exhausted; preserve donor recovery reserve')
    original_exchange = exchange
    def exchange(opcode, payload=b''):
        check_deadline()
        response = original_exchange(opcode, payload)
        check_deadline()
        return response
    host_boot = host_boot_session()
    path = Path(out)/'titan-completion.jsonl'
    def current():
        return json.loads(exchange(1))
    with path.open('x') as log:
        def record(row):
            row['host_uptime_ns']=uptime_ns()
            row['host_clock']='CLOCK_UPTIME_RAW'
            row['host_boot_session']=host_boot
            log.write(json.dumps(row,allow_nan=False)+'\n');log.flush()
        record({'event':'begin','identity':initial,'request':spec,'hardware_access':True})
        try:
            require_healthy(initial)
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
                    check_deadline()
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
                from ael.prism_native import snapshot, window, capture_queue, CAPTURE_QUEUE
                def decoded(row, key, opcode, decoder, payload=b''):
                    raw=exchange(opcode,payload)
                    try:
                        row[key]=decoder(raw)
                    except BaseException as exc:
                        record({'event':'decode_failure','observation_event':row['event'],
                            'field':key,'opcode':opcode,'raw_reply_base64':base64.b64encode(raw).decode(),
                            'message':str(exc)})
                        raise
                def observe(event, phase):
                    row={'event':event,'phase':phase,'observation_complete':False}
                    try:
                        decoded(row,'identity',1,json.loads)
                        decoded(row,'drive',0x50524403,json.loads,struct.pack('<I',boot))
                        decoded(row,'snapshot',23,lambda raw:snapshot(raw,manifest['source_binding_hash']))
                        decoded(row,'transmitter',0x50524c02,json.loads,struct.pack('<I',boot))
                        decoded(row,'capture_queue',CAPTURE_QUEUE,capture_queue,struct.pack('<I',boot))
                        row['observation_complete']=True
                    finally:
                        # Preserve even the first failing/partially decoded observation.
                        # Acceptance checks below never precede this durable row.
                        record(row)
                    return row
                def healthy(row):
                    require_healthy(row['identity'],initial)
                    status=row['drive'];tx=row['transmitter'];queue=row['capture_queue']
                    if status.get('active') or status.get('phase')!='idle' or status.get('live_source') != (0 if prepared['live_source']=='A' else 1):
                        raise Refusal('Replay revived or live source changed')
                    if tx.get('schema')!='prism.titan.transmitter.v2' or any(tx.get(k)!=0 for k in ('first_fault','failures','last_fsp_error','pattern_requested')):
                        raise Refusal('Transmitter fault or fixture pattern active')
                    if type(tx.get('wire_reset_completions')) is not int or tx['wire_reset_completions']<0:
                        raise Refusal('Missing sampled transmitter completion count')
                    if queue['clock_hz']!=row['identity']['clock_hz']:
                        raise Refusal('Capture witness clock changed')
                    if queue['interval_overflow'] or any(stage['overflow'] for stage in queue['stages']):
                        raise Refusal('Capture witness interval/cost overflow')
                def ready(row):
                    snap=row['snapshot'];queue=row['capture_queue']
                    return (snap['capture_valid'] is True and snap['warming'] is False and snap['stale'] is False
                        and all(type(snap.get(k)) is int and snap[k]>0 for k in ('epoch','capture_time_us','sample_end','hops'))
                        and 14000<=snap['source_rate']<=64000 and queue['source_rate']==snap['source_rate'])
                def advancing(before_row, after_row):
                    a,b=before_row['snapshot'],after_row['snapshot']
                    window(a,b)
                    if a['rejected_hops']!=b['rejected_hops'] or b['logical_frame']<=a['logical_frame']:
                        raise Refusal('Rejected hop or stalled render')
                    a,b=before_row['transmitter'],after_row['transmitter']
                    if b['wire_reset_completions']<=a['wire_reset_completions']:
                        raise Refusal('Transmitter stopped or counter reset/wrap')
                    a,b=before_row['capture_queue'],after_row['capture_queue']
                    for key in ('overwrite_events','dropped_blocks','copy_races','preroll_blocks'):
                        if b[key]!=a[key]: raise Refusal('Capture loss or counter reset/wrap: '+key)
                    if b['consumed_blocks']<=a['consumed_blocks']:
                        raise Refusal('Input consumption stopped or counter reset/wrap')
                    if b['first_fault_valid']!=a['first_fault_valid'] or (a['first_fault_valid'] and any(
                            b[key]!=a[key] for key in ('first_time_us','first_cycles','first_producer',
                                'first_consumer','first_rate','first_coefficient_builds','first_stage',
                                'first_last_stage','first_history_count','first_history_overwritten',
                                'first_history_copy_race','first_history'))):
                        raise Refusal('New capture first fault or frozen witness changed')
                readiness_start=monotonic()
                readiness_cutoff=min(readiness_start+READINESS_MAX_SECONDS,
                    cutoff-prepared['seconds']-FINAL_READOUT_RESERVE_SECONDS)
                if readiness_cutoff<=readiness_start:
                    raise Refusal('Full measurement and final readout cannot fit completion absolute deadline')
                record({'event':'readiness_begin','absolute_cutoff':cutoff,
                    'readiness_cutoff':readiness_cutoff,'full_window_seconds':prepared['seconds'],
                    'final_readout_reserve_seconds':FINAL_READOUT_RESERVE_SECONDS})
                exchange_cutoff=readiness_cutoff
                previous_ready=None;startup_faults=[];readiness_samples=0
                while True:
                    if monotonic()>=readiness_cutoff:
                        record({'event':'boot_to_ready','status':'FAIL','reason':'never ready within admitted cutoff',
                                'faults':startup_faults,'observations':readiness_samples})
                        raise Refusal('Capture never ready within completion absolute deadline/readiness cutoff')
                    row=observe('readiness_health','startup');readiness_samples+=1
                    healthy(row)
                    snap=row['snapshot'];queue=row['capture_queue']
                    fault={'last_invalidate_reason':snap['last_invalidate_reason'],
                        'last_invalidate_reason_name':snap['last_invalidate_reason_name'],
                        **{k:queue[k] for k in ('overwrite_events','dropped_blocks','copy_races','first_fault_valid')}}
                    if any(fault[k] for k in ('last_invalidate_reason','overwrite_events','dropped_blocks','copy_races','first_fault_valid')) and fault not in startup_faults:
                        startup_faults.append(fault)
                    if ready(row):
                        if previous_ready is not None:
                            advancing(previous_ready,row)
                            first=row
                            break
                        previous_ready=row
                    else:
                        previous_ready=None
                    pause(min(.25,max(0,readiness_cutoff-monotonic())))
                startup={'status':'FAIL' if startup_faults else 'PASS','faults':startup_faults,
                    'observations':readiness_samples,'readiness_seconds':monotonic()-readiness_start,
                    'valid_stream_boundary_us':first['capture_queue']['valid_stream_boundary_us'],
                    'planned_preroll_blocks':first['capture_queue']['preroll_blocks'],
                    'scope':'boot-to-ready witness; two observations establish readiness, not endurance'}
                record({'event':'boot_to_ready',**startup})
                exchange_cutoff=cutoff
                first_snapshot,first_tx=first['snapshot'],first['transmitter']
                record({'event':'progress_before','snapshot':first_snapshot,'transmitter':first_tx,
                        'capture_queue':first['capture_queue']})
                before=[decode_cost(exchange(COST,struct.pack('<II',boot,i)),i) for i in range(len(STAGES))]
                record({'event':'cost_before','data':before})
                end=monotonic()+prepared['seconds'];samples=0
                if end+FINAL_READOUT_RESERVE_SECONDS >= cutoff:
                    raise Refusal('Full measurement and final readout cannot fit completion absolute deadline')
                record({'event':'measurement_begin','full_window_seconds':prepared['seconds'],
                        'measurement_end_monotonic':end})
                previous=first
                while monotonic()<end:
                    check_deadline()
                    # The first visit follows cost collection without assuming that
                    # its query duration advanced audio. Wait for a sampled interval.
                    pause(min(.25,max(0,end-monotonic()),max(0,cutoff-monotonic())))
                    check_deadline()
                    row=observe('health','measurement');samples+=1
                    healthy(row)
                    if not ready(row): raise Refusal('Invalid capture metadata after readiness')
                    advancing(previous,row);previous=row
                after=[decode_cost(exchange(COST,struct.pack('<II',boot,i)),i) for i in range(len(STAGES))]
                record({'event':'cost_after','data':after})
                final=observe('progress_after','final')
                healthy(final)
                if not ready(final): raise Refusal('Invalid final capture metadata')
                # Final reads can follow immediately; require nondecreasing progress
                # from the last sample and advancing progress over the whole window.
                for key in ('capture_time_us','sample_end','hops','logical_frame'):
                    if final['snapshot'][key]<previous['snapshot'][key]:
                        raise Refusal('Final capture counter reset/wrap: '+key)
                for key in ('consumed_blocks',):
                    if final['capture_queue'][key]<previous['capture_queue'][key]:
                        raise Refusal('Final input counter reset/wrap: '+key)
                if final['transmitter']['wire_reset_completions']<previous['transmitter']['wire_reset_completions']:
                    raise Refusal('Final transmitter counter reset/wrap')
                advancing(first,final)
                final_snapshot,final_tx=final['snapshot'],final['transmitter']
                audio_window=window(first_snapshot,final_snapshot)
                if audio_window['rejected_hop_delta']!=0 or audio_window['logical_frame_delta']<=0 or final_tx['wire_reset_completions']<=first_tx['wire_reset_completions']:
                    raise Refusal('Lost/rejected audio or stalled render/transmitter')
                costs=[cost_delta(a,b) for a,b in zip(before,after)]
                required=('capture','resample','analysis','proxy','hop_total','render_including_pack','pack','usb','active_loop')
                if any(c['count']==0 for c in costs if c['stage'] in required):
                    raise Refusal('Missing stage measurement')
                result={'kind':'measure','health_samples':samples,'costs':costs,'physical_latency':'UNMEASURED',
                        'startup':startup,'live_continuity_met':True,'measurement_seconds':prepared['seconds'],
                        'capture_queue_before':first['capture_queue'],'capture_queue_after':final['capture_queue'],
                        'audio_window':audio_window,'sampled_wire_reset_completion_delta':final_tx['wire_reset_completions']-first_tx['wire_reset_completions'],
                        'timing_scope':'Measured stage execution only; scheduler response deadlines and physical latency require separate verification',
                        'proxy_budget_met':costs[3]['p99_us_interval'][1]<=1000,
                        'hop_deadline_met':costs[5]['cumulative_max_us']<=5000,
                        'render_deadline_met':costs[6]['cumulative_max_us']<=10000,
                        'optical_verified':False}
            final_preamble=json.loads(exchange(PREAMBLE,struct.pack('<I',boot)))
            record({'event':'preamble_after','data':final_preamble})
            result['memory_before']=preamble
            result['memory_after']=final_preamble
            result['final_identity']=current();record({'event':'final_identity','identity':result['final_identity']})
            require_healthy(result['final_identity'],initial)
            record({'event':'result','data':result})
            return result
        except BaseException as exc:
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
