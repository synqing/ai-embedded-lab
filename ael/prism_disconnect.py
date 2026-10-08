"""Bounded client loss proof under the gateway's existing sole-owner lock.

No port scanning, reset, programming, audio playback or second owner is created.
The caller supplies actual close/reopen callbacks for the same Serial instance.
A closed host descriptor alone is insufficient: firmware must witness its CDC
DTR falling edge, clear the session and continue advancing microphone/render and
hardware wire-completion counters. Optical output is explicitly unmeasured.
"""
import json
import math
from pathlib import Path
import struct
import time

from ael.prism_completion import require_healthy
from ael.prism_drive import Refusal

STATUS = 0x50524403
SELECT = 0x50524405
TRANSMITTER = 0x50524C02


def prepare(spec):
    if not isinstance(spec, dict) or set(spec) != {'seconds'}:
        raise Refusal('Disconnect check requires only the bounded seconds field')
    seconds = spec['seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise Refusal('Disconnected autonomous interval must be 1..30 seconds')
    return dict(spec)


def _counter(row, key):
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise Refusal('Missing or invalid counter: ' + key)
    return value


def _idle(status, boot, source):
    if (status.get('boot_id') != boot or status.get('active') is not False or
            status.get('phase') != 'idle' or status.get('queue_depth') != 0 or
            status.get('weight') != 0 or status.get('live_source') != source):
        raise Refusal('Replay active or unexpected live source/session state')


def execute(exchange, close_owner, reopen_owner, manifest, spec, out, initial,
            *, monotonic=time.monotonic, pause=time.sleep):
    """Operate only after the gateway has admitted the image and acquired its lock.

    The two callbacks return observed port/is_open/dtr/rts from the SAME Serial
    instance. Reopen checks external ownership before opening the exact path,
    retains sequence/cookie and asserts DTR (RTS remains false). No blind retry.
    The final gateway finally block remains responsible for releasing the port.
    """
    spec = prepare(spec)
    from ael.prism_native import UID, SCHEMA, bind_payload, snapshot, window
    start = monotonic()
    boot = initial.get('boot_id')
    with (Path(out) / 'titan-disconnect.jsonl').open('x') as log:
        def record(event, **data):
            log.write(json.dumps({'event': event, 'host_monotonic_s': monotonic(), **data},
                                 allow_nan=False) + '\n')
            log.flush()

        def deadline():
            if monotonic() - start > 120:
                raise Refusal('Disconnect check exceeded the 120-second case limit')

        def identity(label):
            deadline()
            value = json.loads(exchange(1))
            record(label, identity=value)  # Preserve the response before checking.
            require_healthy(value, initial)
            if (value.get('uid') != UID or value.get('schema_sha256') != SCHEMA or
                    value.get('build_source_sha256') != manifest['source_binding_hash'] or
                    type(boot) is not int or boot <= 0):
                raise Refusal('Disconnect identity/source mismatch')
            if value.get('usb_dtr') is not True:
                raise Refusal('CDC client connection was not asserted')
            _counter(value, 'usb_disconnect_events')
            return value

        def state(label, source):
            value = json.loads(exchange(STATUS, struct.pack('<I', boot)))
            record(label, drive=value)
            _idle(value, boot, source)
            _counter(value, 'disconnects')
            return value

        def progress(label):
            # exchange() persists original binary response before snapshot decoding.
            snap = snapshot(exchange(23), manifest['source_binding_hash'])
            tx = json.loads(exchange(TRANSMITTER, struct.pack('<I', boot)))
            record(label, snapshot=snap, transmitter=tx)
            if tx.get('schema') != 'prism.titan.transmitter.v2' or any(
                    type(tx.get(k)) is not int or tx[k] != 0
                    for k in ('first_fault', 'failures', 'last_fsp_error', 'pattern_requested')):
                raise Refusal('Transmitter fault or fixture pattern active')
            _counter(tx, 'wire_reset_completions')
            return snap, tx

        def owner(label, callback, opened):
            observed = callback()
            record(label, owner=observed)
            if (not isinstance(observed, dict) or observed.get('port') != manifest['port'] or
                    observed.get('is_open') is not opened or
                    (opened and (observed.get('dtr') is not True or observed.get('rts') is not False))):
                raise Refusal('Serial owner did not close/reopen the exact path without reset lines')

        def continuous(first, last):
            audio = window(first[0], last[0])
            if audio['rejected_hop_delta'] != 0 or audio['logical_frame_delta'] <= 0:
                raise Refusal('Capture/render fault during client disconnect')
            count = last[1]['wire_reset_completions'] - first[1]['wire_reset_completions']
            if count <= 0:
                raise Refusal('Wire completion counter stalled or reset')
            return audio, count

        record('begin', request=spec, initial=initial, hardware_access=True)
        try:
            require_healthy(initial)
            before_info = identity('identity_before')
            prior = json.loads(exchange(STATUS, struct.pack('<I', boot)))
            record('prior_drive', drive=prior)
            _idle(prior, boot, prior.get('live_source'))
            if prior.get('live_source') not in (0, 1):
                raise Refusal('Unknown live source')
            exchange(SELECT, struct.pack('<II', boot, 1))
            before = state('drive_before', 1)
            first = progress('progress_before')
            owner('owner_closed', close_owner, False)
            closed_at = monotonic()
            pause(spec['seconds'])
            closed_seconds = monotonic() - closed_at
            if closed_seconds < spec['seconds']:
                raise Refusal('Autonomous interval ended early')
            deadline()
            owner('owner_reopened', reopen_owner, True)
            after_info = identity('identity_after')
            if after_info['usb_disconnect_events'] != before_info['usb_disconnect_events'] + 1:
                raise Refusal('Device did not witness exactly one actual CDC disconnect')
            # Identity first; only then bind the same boot after session cleanup.
            exchange(0x50520001, bind_payload(boot))
            after = state('drive_after', 0)
            if after['disconnects'] != before['disconnects'] + 1:
                raise Refusal('Evaluation owner did not observe the disconnect')
            for key in ('trial', 'accepted', 'opens', 'initial_state_resets'):
                if _counter(after, key) != _counter(before, key):
                    raise Refusal('Replay history changed on reconnect: ' + key)
            second = progress('progress_after')
            audio, completions = continuous(first, second)
            pause(.25)
            final_info = identity('identity_settled')
            final_drive = state('drive_settled', 0)
            for key in ('disconnects', 'trial', 'accepted', 'opens', 'initial_state_resets'):
                if _counter(final_drive, key) != _counter(after, key):
                    raise Refusal('Replay or another disconnect appeared after reconnect')
            if final_info['usb_disconnect_events'] != after_info['usb_disconnect_events']:
                raise Refusal('USB connection changed after reconnect')
            continuous(second, progress('progress_settled'))
            deadline()
            result = {'kind': 'disconnect_check', 'owner_closed_seconds': closed_seconds,
                      'requested_closed_seconds': spec['seconds'],
                      'device_disconnect_events': 1, 'reconnected_live_source': 'A',
                      'replay_revived': False, 'audio_window': audio,
                      'wire_reset_completion_delta': completions,
                      'final_identity': final_info, 'optical_verified': False,
                      'physical_latency': 'UNMEASURED',
                      'scope': 'Actual CDC client close/reopen with cumulative telemetry; '
                               'continuous physical light during the unobserved interval is unmeasured'}
            record('result', result=result)
            return result
        except Exception as exc:
            record('failure', message=str(exc))
            raise
