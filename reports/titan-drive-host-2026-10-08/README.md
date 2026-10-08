# Titan evaluation-drive host completion — 8 October 2026

**Scope: host implementation and evidence admission only. Physical execution remains
blocked by native output HOLD.** The full Titan brief and amendment remain in force.
No serial, broker, reset, flash, playback, camera or other repository write occurred
in this AEL lane. Teacher promotion remains AUTOMATIC_TEACHER_PROMOTION_HELD.

## Implemented consequence

The prior AEL code provided a media player and due-hop arithmetic but did not send
drive records. Commit `cbe3c14` adds the actual CRC-framed native transport within
the existing single-owner `bench-trial-control` session. UID/schema/source/boot,
monotonic trial and record sequence, frozen source recomputation, exact scene,
offline availability and media identity are validated before a record is sent.
A successful native open must advertise the programme/precision reset contract
and increment its counter. Wrong, lost or expired sessions never reconnect.

Playback uses the source-bound, once attenuated FLOAT WAV produced by EdgeAI:
input transformation0.5, engine gain1. Start reports bind that unity gain, file rate
and frame count. Timing uses audio render position and reported presentation latency;
unknown acoustic route uncertainty stays null. The affine device-clock estimate
records offset, drift and bracket/residual uncertainty and remains unqualified.

Host deadlines, queue headroom, four-record chunks, fresh clock reports and bounded
pending arrival evidence prevent stale backlog dumping. Raw native exchange,
pacing, source-generation arrival and abort records are retained. Native FIFO
arrival, consumption, rendering and completion witnesses are distinct. A failed
exchange receives no retry; closing the owner and native finite lease/fade are the
recovery mechanism. The experiment is never saved as a normal scene.

Commit `13c7edd` closes two independently identified admission holes:
v1 assertions plus a raw-file hash could admit a two-row CSV as120 frames; and an
arbitrary candidate could use the recovery exemption. No independent off-product
acquisition verifier exists, so all native flash proof methods now refuse
OUTPUT_QUALIFICATION_UNAVAILABLE. Recovery instead pins the actual known donor UID,
HEX, derivation and successful executed recovery receipt. Native output HOLD
cannot be bypassed by renaming a candidate.

## Checks actually executed

| Check | Observed result | Limit |
|---|---|---|
| Focused media/wire/session tests |31 passed |Explicit emulated endpoint and audio clock; no hardware |
| Selected existing PRISM regression |223 passed,12 skipped |Skips are deliberate inapplicable receipt-family cases |
| Output/recovery refusal tests |38 passed |Includes all unsupported proof methods and disguised recovery |
| Swift player build |Exit0 |No audio engine was started |
| Eight actual r3 trace files |22 A/C/D arms prepared and frozen scene validated |B unavailable; no playback |
| Existing native receipt consumed by actual AEL validator |30 compiled positive executions,44 compiled faults admitted; restored level_trace compile/sanitised included |HOST candidate checks only; no compiler or hardware rerun |
| Scope-locked actual donor trio |Accepted by read-only provenance checker |No recovery invoked |

The focused emulator checks cover wrong UID/schema/source/boot; old boot, spent
trial, duplicate/out-of-order record; wrong wire sequence/cookie and CRC; stale,
early, expired or backlogged media; client loss and finite fallback; FIFO capacity
and high watermark; drift/offset/uncertainty; source/audio/timing/half swaps; wrong
playback gain; arrival generation binding; and actual existing owner-session
control→stream→close through one emulated serial port. Scene-reset absence rejects
before any record.

The regression command was:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m pytest -q -x tests/test_prism_drive.py tests/test_prism_drive_stream.py tests/test_prism_bench_trial.py tests/test_prism_lane.py tests/test_prism_native_checks.py tests/test_prism_product.py
sh tools/media_clock_player/build.sh
```

Actual preparation syntax was tested with `python -m ael.prism_drive`, passing
the r3 `03-30s` trace, freeze, verification, verifier, transformed playback,
render-only timing file, armA and fresh request output. Concrete output:
`_scratch/titan-drive-03-30s-A-request.json`. This is an offline request, not
permission to run it. The existing control action consumes it only with a current
admitted deployment manifest and owner authority.

Actual r3 source root:
`/Users/spectrasynq/SpectraSynq-EdgeAI-Lab/_scratch/titan_music_value_20261008/r3-open-reset`.
Freeze canonical SHA256:
`a77405f82e9eb14a791ff44877a9d629bfa5f20e5f3002eb64ca580a56334535`.

The existing native check receipt at Kx-Titan
`_scratch/music_visual_value_20261008/takeover/native-integration-check-final/receipt.json`
has SHA256 `52b455d805c1ce0a11e6b5d19553937dacb3e0984f034afd8dc551892d79af11`.
AEL's unchanged `validate_native_checks` consumed it against committed Kx
`70b8c3290ce3f4bf804f278af68779c2214c91e0` and actual `git ls-files`.
The initial pre-commit check correctly refused the then-untracked led_timer_arm.h;
after the owner's commit, the same read-only validator passed. No source list
was fabricated to evade that check. Native.cpp is now in the input hash inventory.

See [source hashes and observed checks](source-and-checks.json) and
[existing native receipt consumer](native-check-consumer.json).

## Unclosed physical requirements

No off-product waveform acquisition verifier/fixture is available. Native flash
remains HOLD. Acoustic alignment, physical timestamps, completed electrical output,
actual musical-value comparison, endurance, autonomous candidate leave-state and
owner appearance ratings remain BLOCKED/NOT TESTED in this lane. Current resident
donor identity and continuing music are the root hardware lane's observations;
host test results do not establish them. No camera capture was attempted.

## Governance and Civilization Engine audit

Actual governance session:57758bd57e56f3683481e439. Context and mandatory workflow
loaded; no applicable existing assignment registry was found. No registry was
invented. Installed verification rejected “Verification project outside configured
workspace”; corrected semantic review rejected “Project is outside allowed roots”.
Trust was not widened. Direct named host checks ran and are reported as such.
The final gate allowed a normal stop with no bound ledger and explicitly said this
is not a completion certificate. Hindsight recall and standing-rule model were
read through supported loopback. Handback retention was attempted but the10-second
request timed out; durable retention is not confirmed.

Civilization Engine was queried for titan-native/evaluation-drive-host and
HIGH_PRIORITY. The external engine is unavailable; context and pattern results
were empty. No hardware pattern was substituted and no success asset promoted.
The reusable bounded host pattern is captured in
[the existing PRISM bench skill](../../docs/skills/prism_lane_bench.md).
