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

## Raw waveform consumer and physical acquisition gap — continuation

The original host takeover remains historical. The new consumer in
`ael/titan_waveform.py` reads shared-clock raw transitions, counts and decodes
every one of3840 bits in at least100 frames on each physical lane, checks exact
payload/order, pulseHIGH/LOW, period, leading/inter-frame/terminal resetLOW and
requires bothP601/P604. Malformed, truncated, one-sided, reordered and altered
captures fail. An independent test decoder compares emitted frame order.
`ael/titan_capture.py patterns` produces the exact documented native
pattern-set-v1 payload: frame-major A then B,480 bytes each. All-ones is strictly
for an electrically isolated fixture. No diagnostic pattern was sent.

[Independent numerical requirements](waveform-requirements.json) come from
Worldsemi's WS2816C-1313v1.1(20210603), page4, manufacturer-authored PDF mirrored
by LCSC C5446703. SHA256
`a9bf86bd23b324918456d39ff4f1e0e7e9a8220815da13605594b405ea41be96`.
The cover saysC while interior headings sayB; fitted-device applicability is
UNRESOLVED and is not certified by this verifier. Primary source URL is in the
requirements. Published values: T0H200–320ns, T1H520–800ns, T0L800–1200ns,
T1L480–1000ns, period>=1250ns, reset>280us. The chosen10ns maximum per-edge
uncertainty is an experiment guard, not a manufacturer limit. Measured intervals,
including two edge uncertainties, must fit inside those bounds. Native constants
do not define the verifier's acceptance values. The source discrepancy exposed
800nsHIGH+450nsLOW at1250ns as outside the published T1L minimum.

The capture manifest binds raw bytes and expected bytes, UID, image/source/build,
programming/readback event, physical pins, original fixture/instrument/settings/
fitted-part records and acquisition time. It rejects mismatching candidate hashes,
changed bytes, stale/future acquisition, capture-before-program and incomplete
time coverage. These original records are bound inputs; their declarations are
never reclassified as observed physical facts. Even a valid raw waveform verdict
reports `physical_qualification:false`. V2 ordinary deployment re-runs the actual
raw consumer, then independently refuses absent supported physical provenance.
V1 paper proofs remain refused; the immutable donor exemption is unchanged.

### Actual remaining capability

**PackageB acquisition and PackageC physical proof are incomplete.**
`bench-trial-qualify-isolated` is an implemented distinct, fail-closed gateway
preflight. It does not yet have an executable programming/acquisition/readback/
recovery backend. No supported adequate local producer was established, so adding
a fake successful orchestrator would misrepresent the available capability.

Read-only repository inventory, USB enumeration and ARP inspection found the
RenesasCDC and E2Lite5AS079228B, with no identified analyser connected to Titan.
Historical ESP32JTAG192.168.2.62 and meter192.168.4.1 are not current connections.
Their endpoints were not contacted. The matching ESP32JTAG firmware source is
documented at `/nvme1t/work/esp32jtag_firmware` on the earlier Linux setup; it is
not available in this Mac checkout. AEL source documents16channels,264MHz max,
`/instant_capture` status-byte+big-endian16 data and about496us at132MHz
(`experiments/esp32jtag/port_d_loopback.py:266`), implying roughly65k samples.
Exact current depth and timebase remain unobserved. Lowering the rate to fit a
complete frame sacrifices pulse resolution: a5.36ms minimum acquisition including
reset at each end needs<=12.2MHz for65k samples, approximately82ns/sample.
The candidate1300ns/bit plus350us leading/trailing reset needs5.692ms.
At100MHz it needs569200 simultaneous samples; the minimum protocol window needs
536001. Even relaxing the experiment guard to30ns per edge leaves the documented
depth inadequate. No local source documents lossless streaming, RLE, expandable
external memory or sufficiently deep segmented capture. This is a documented
interface/access gap, not a claim that FPGA silicon cannot be extended.
The meter exposes aggregate digital/voltage values and has no raw edge API.

Required wiring once a capable owned detector is established: electrically
disconnect BOTH productDIN feeds fromP601/P604 (software emit-off is insufficient),
connect physicalP601 to detectorCH0 andP604 toCH1 with shared signal ground, and
verify detector input-voltage tolerance at that actual measurement point from its
hardware manual before connection. No detector's current electrical tolerance or
connector pinout has been established, so this is a signal mapping, not a
wiring-ready instruction. The owner's sole working Titan must not be disconnected
until its interruption/recovery authority and physical isolation evidence exist.

Next implementation dependency is the identified analyser's current firmware/API
and hardware manual showing shared-clock simultaneous capture of a complete
5.692ms frame with adequate uncertainty (and either continuous100-frame capture
or real lossless, ordered segments). Then implement the actual arm/status/read
backend plus independent isolation observation and bounded acquire/program/
readback/recovery integration. Current tested refusal is
`BLOCKED_CAPTURE_CAPABILITY`, before any owner, serial or programmer access.
No acquisition, flash, broker stop, camera, playback or instrument mutation ran.

### Implemented commands and proof

Run fromAEL with `/Users/spectrasynq/.platformio/penv/bin/python`:

```sh
python -m ael.titan_capture capability --backend esp32jtag-instant-v1
python -m ael.titan_capture isolated-preflight --manifest _scratch/titan-completion-20261008/isolated-request.json
python -m ael.titan_capture patterns --frames 120 --output NEW-expected-pairs.bin
python -m ael.titan_waveform --manifest REAL-capture-manifest.json --output NEW-verdict.json
```

The first two commands were executed and refuse the precise capability gap.
The120-frame pattern command was executed:115200bytes, SHA256
`5e86b640708ef4b8ffc7cdc2f84fee7830369ae00cf040aed41ffe6e489c6053`.
The real verifier CLI is exercised by a full100-frame-per-lane synthetic capture;
that test also proves changing `origin` tophysical cannot admit it. Placeholder
paths in the last two commands must be real evidence paths; no physical capture
manifest currently exists. Read-only instrument status can later be obtained by
`python -m ael.titan_capture status --endpoint https://IDENTIFIED-OWNED-INSTRUMENT`;
only `/api/version` and `/la_status` are allowed, with TLS verification enabled.
It does not arm acquisition or assert isolation.

The focused regression log is
`_scratch/titan-completion-20261008/pytest.log`; separate expanded raw CLI tests
are in `waveform-pytest.log`. Governance `workflow_verify` actually refused
`Verification project outside configured workspace`; suggestion reported
`session_project_mismatch`. No registry was found/bound and no trust was widened.
The exact executed checks are host evidence; no device or product acceptance.
Images are N/A for these source/parser edits: the producing agent inspected
source diff, decoded consumer results and actual command refusals.
