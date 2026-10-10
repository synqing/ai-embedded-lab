# Titan evaluation-drive host completion — 8 October 2026

**Current scope: host implementation plus isolated device fault isolation and verified
donor recovery. Native connection to the product remains on HOLD.** The opening
8October work was host-only; the subsequent actual hardware attempts are recorded
below. The full Titan brief and sequencing amendment remain in force. Teacher
promotion remains AUTOMATIC_TEACHER_PROMOTION_HELD.

## Current state — final integrated continuation

The runnable onboard raw acquisition backend and isolated programming/recovery
transaction are implemented; see [the latest implementation](#implemented-onboard-raw-acquisition--latest-continuation).
Earlier sections below retain the chronological evidence and describe the code at
those earlier checkpoints. Their statements that acquisition was absent or
unimplemented are historical, not the current implementation status.

Actual isolated execution occurred on 9–10 October. Across 29 candidate transactions,
the latest exact image completed the frozen 100-pair digital campaign: 100 patterns
in order, exact expected payloads and four complete, ordered, unique streams per
pair. Collection took 53.581 seconds; no new microphone faults or restarts occurred.
One recovered output-supervision timeout preceded the campaign and did not recur
during it. Donor programming and subsequent application identity were verified;
broker telemetry resumed. Original physical confirmation and standing interruption
authority remain valid. The product harness stays OFF.
Latest source/device evidence is retained locally under
`_scratch/titan-completion-20261008/isolated-direct-full100/`;
see [attempts 28–29](#attempts2829--complete-frozen100-digital-campaign-pass).
Ignored raw evidence is not part of a normal source clone. Earlier partial and
failed acquisitions below remain historical evidence.

Fitted-LED applicability, representativeDIN electrical path and capture error
bounds still block electrical release. They do not block isolated diagnostic or
computation work. Historical sections below describe their dated checkpoints.

## Historical initial implementation

### Revision2 isolated target computation — 10 October continuation

The existing isolated gateway now binds exactly one golden or measure request by
file hash and includes its kind/hash in the immutable operation scope. Raw capture
manifests retain their prior scope. The same owner, programming lock, 80-second
candidate cutoff and conditional donor recovery execute the request; no separate
serial or programmer route was introduced. Mixed requests, unknown fields, SAVE,
endurance, tampering and consumed authority are refused.

The absolute deadline reaches the existing completion consumer and its framed
exchanges. A full measurement window must fit; it is never silently shortened.
Expired or non-finite deadlines fail before opening CDC. Partial wire responses,
cancellation and first failure logs are retained while the sole owner closes.
Startup faults remain refusals; no output counter or acceptance limit was changed.
Candidate firmware and the successful 100-pair raw baseline are unchanged.

Actual affected host suite: **381 passed, 12 existing skips**. The native
workflow verification receipt is
`/Users/spectrasynq/.local/state/spectrasynq-agents/verification/917fc5e04aa1a3dd3192529fce23fc2272bca5d308462dddcbdb18d96518c474.json`
(SHA256 `5309f2ccc51b6393859957129e84d05176aa99034b751b7956fd964458c77753`).
Tests include the real framed serial consumer against an explicit emulator,
startup refusal, partial response, deadline during exchange, cancellation,
request/scope corruption, replay and conditional recovery. The diff and consumer
logs were inspected. Images are N/A for this host transport change.
This is host execution evidence; target golden/cost results and electrical release
remain separate device requirements under the full 94-task Revision2 plan.

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

The final read-only capability check also inspected the channel configuration:
`experiments/esp32jtag/portb_reset_test.py:205` disables fifteen trigger channels,
then still reads two bytes per sample at line245. The `channels` array selects
trigger modes; no available contract says that selecting two or eight channels
increases capture depth. The golden instrument manifest is a template containing
placeholder identity values, not evidence of a deeper connected instrument.

### Existing Titan input-capture alternative — source-supported, unimplemented

The retained donor source `platform/ra8p1/ws281x_p601_loopback.c` samples the actual
PORT6 input register using GPT2 and DMA4. It is a coarse, one-shot GPIO sampler,
not an adequate two-lane timestamp backend. Its scorer separately requires
`uniform_sampling_qualified`; its source does not establish that qualification.
No donor implementation was copied.

There is a more capable documented route within the existing MCU. RA8P1 manual
R01UH1064EJ0130, section23.3.1.3/page994 and Table23.21/page1006 describe hardware
input capture on both edges of each GPT input. The RA8P1 datasheet pin tables
map P603/P602 to GPT7 A/B. The actual Titan Mini schematic sheet13 was rendered
and visually inspected (`_scratch/titan-completion-20261008/u18-readonly.png`):
U18 pin7 is P601, pin12 P604, pin33 P603 and pin35 P602. Proposed loopback jumpers
would therefore be 7→33 and12→35. **These are proposed new connections, not
existing wiring or evidence of isolation.** The schematic is
`sdk-bsp-ra8p1-titan-mini/docs/Titan_Mini_schematic_v1.0.pdf`.

Current native source allocates GPT0/1/6/8 and DMA0..3. GPT7 with DMA4/5 could
retain two streams of physically captured timestamps without sharing those
channels. FSP `bsp_elc.h` exposes GPT7 captureA/B events0x1C0/0x1C1 and ELC E/F
peripherals4/5. Manual page910 documents GTUPSR bits20/21 for counting E/F events;
source-unallocated GPT2/3 could count every input-capture event independently of
DMA and continue through the terminal reset. This is a concrete route to detect
DMA loss: GTCCRA/B overwrite on new captures and DMA status alone has no event
overrun counter. Native interrupt vectors4/5 already belong to microphone
errors; a recorder must not reuse the existing `irq=channel` allocation for
DMA4/5. New vectors or a documented polled configuration would be needed.

A frame pair requires 7680 timestamps per lane, 61440 bytes total. A bounded
capture→host-drain→rearm protocol could retain 100 separate windows without a 6MB
allocation. Every window would need observed initial LOW, physical edge counts,
DMA residual/status, complete terminal reset observation, clock/configuration
readback and its own acquisition epoch. Separate windows cannot be joined with
invented inter-window timestamps to satisfy the present continuous-file parser.
Fixture-only stepping, raw chunk transport and segmented verification are not
implemented. Outside that isolated operation, autonomous music must continue.

This route remains insufficient for physical qualification today. The board
schematic labels the crystal24MHz without a component identity or tolerance;
the shared transmitter/capture clock does not independently prove absolute
nanoseconds. The documented native configuration is nominally GPTCLK300MHz and
PCLKD250MHz, not a measured frequency. Datasheet Table2.58/page143 also bounds
the minimum detectable input pulse; it is not an analogue glitch detector.
An existing-resource calibration avenue is the USB hardware frame number:
manual section37.3.13/page2066 says missing full-speed SOF does not advance
FRMNUM, whereas the SOFR interrupt can be interpolated locally. Consecutive
hardware FRMNUM changes bracketed by GPT reads could therefore supply an
independent reference, subject to authoritative host SOF tolerance, bounded read
brackets and rejection of reset, suspend or missed frames. That calibration and
its uncertainty propagation are not implemented or measured here.
Finally, U18 observes MCU pads, not the post-level-shifter DIN signal. A direct 5V DIN-to-MCU
jumper is not authorised or electrically qualified. Fitted-part applicability,
safe observation at the actual DIN measurement point, timebase bounds and fresh
physical isolation remain unresolved. This investigation establishes a possible
implementation path using existing resources, not a requirement to buy hardware
and not an adequate implemented backend. No pins were connected or reconfigured.

Required wiring once a capable owned detector is established: electrically
disconnect BOTH productDIN feeds fromP601/P604 (software emit-off is insufficient),
connect physicalP601 to detectorCH0 andP604 toCH1 with shared signal ground, and
verify detector input-voltage tolerance at that actual measurement point from its
hardware manual before connection. No detector's current electrical tolerance or
connector pinout has been established, so this is a signal mapping, not a
wiring-ready instruction. The owner's sole working Titan must not be disconnected
until its interruption/recovery authority and physical isolation evidence exist.

An external-analyser implementation depends on its identified current firmware/API
and hardware manual showing shared-clock simultaneous capture of a complete
5.692ms frame with adequate uncertainty (and either continuous100-frame capture
or real lossless, ordered segments). Then implement the actual arm/status/read
backend plus independent isolation observation and bounded acquire/program/
readback/recovery integration. The internal-capture alternative has the distinct
implementation and qualification gaps above. Current tested refusal is
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

### Completion session integration

Waveform/preflight commit`73f19cc`; completion consumer integration`3989b86`
follows parent module`0705200`. `prism_native.run_session` prepares a completion
request before creating a serial object, forbids SAVE, fieldsPATCH and descriptor
replay combinations, binds the existing native identity/session and calls the
completion consumer through that same owner. A failed proxy/hop/render timing
budget now raises a refusal after its measured evidence is preserved, preventing
a successful AEL session result from concealing a failed budget.

`tests/test_prism_completion_measure.py` exercises the actual measurement branch
and framed serial-owner integration. It checks A/D source and observer controls,
clock/cost distributions, missing stage data, identity/boot/counter changes,
revived replay, frozen transmitter completion, changed audio epoch, rejected
hops, transmitter firstfault and active fixture patterns. Snapshot opcode23
reads current application state directly; opcode21 is not a refresh command.
The measured timing scope is stage execution: it does not establish scheduler
response deadlines, physical added delay or optical correctness.

Executed results, without summing overlapping suites:

- Selected fullPRISM suite before the final progress checks:300passed,12intentional
  receipt-family skips; `_scratch/titan-completion-20261008/final-pytest.log`.
- After final snapshot/transmitter checks:110affected tests passed;
  `completion-pytest-final-repaired.log`. The preceding missing schema in the
  test fixture remains recorded in `completion-pytest-final.log`; the fixture
  was corrected to the actual `prism.titan.transmitter.v2` schema.
- Expanded waveform/realCLI suite:42passed before moving four completion
  preflight tests into the dedicated measurement file; `waveform-pytest.log`.
- Actual compiled C++ nativepattern helper and independent Python generator
  emitted identical115200bytes for120frames/lane; `native-pattern-parity.json`
  records the exact headerhash and compiler command. This is host byte equality.

All logs are under`_scratch/titan-completion-20261008/`. No device command was
sent. AEL's schema pin is source-readback-bound to Kx native-contract hash
`7b371dd282b0120bd929afdcfb3e7004334f64b4bab52a34b8ce6f319960b540`;
a subsequent native contract edit requires a new exact pin and affected check.

## Implemented onboard raw acquisition — latest continuation

Captain confirmed that no logic analyser or oscilloscope is available. The
existing-resource alternative above now has an executable implementation:
`ael/titan_loopback.py` consumes the native GPT7 external-input capture interface,
and `ael/titan_isolated.py` runs the isolated transaction through the existing
AEL gateway. The preceding statements that no acquisition backend exists are
historical; **physical execution and positive timing qualification remain open**.
The donor has not been touched in this work.

The backend reads 100–120 separately identified capture epochs. Each retains
both raw timestamp arrays, the independently counted input edges, original
register/status bytes, raw USB frame brackets, ordered wire chunks and host
times. It verifies 7680 physical edges and 3840 decoded bits per lane, the exact
indexed pattern payload, observed initial/terminal LOW and reset intervals,
counter/DMA agreement and the actual capture/counting resource configuration.
It does not invent timestamps between epochs. Fault-state raw data is drained
and saved before reporting failure. Truncated wire replies, including bytes
received before a device disappearance, remain in the original transaction log.
A secondary cancellation failure does not erase the first error.

The timebase uses at least 128 consecutive actual USB FRMNUM transitions,
continuing through a bracket after capture ends. USB2.0 section7.1.12,
printed page159, bounds each full-speed frame to999500–1000500ns. The official
[USB-IF specification archive](https://www.usb.org/sites/default/files/usb_20_20250603.zip)
contains `usb_20.pdf`, SHA256
`d39698a33486c399124af92bd02e4f978fd9a836b5cf4e52e6e4633eb1d89f61`.
It is retained under `_scratch/titan-completion-20261008/`. The verifier derives
a frequency interval from original read brackets and propagates it separately
for each measured duration; it never applies a uniform10ns error to a5ms frame.

**The pin-to-capture timing error remains unqualified.** RA8P1's minimum input
pulse specification does not supply a maximum pad/synchroniser timing error.
The raw collector therefore uses a clearly labelled quantisation-only model
for consistency checks and returns
`timing_qualification: UNQUALIFIED_PIN_TO_CAPTURE_ERROR`,
`measured_waveform_pass:false` and `physical_qualification:false`, even when all
raw counts and payloads are consistent. Changing a saved verdict or `origin`
field cannot clear ordinary deployment: the consumer re-reads the raw files and
retains HOLD. A manufacturer-supported or independently established bound for
that input path is still needed, as are fitted-LED applicability and safe
observation at the eventual DIN measurement point. This is not a request to
approve an invented engineering allowance.

### Isolated transaction and authority boundary

Before any programming, the existing source/build/image validator, fresh target
identity/owner checks and exact known-donor recovery checks still apply. The new
operation additionally binds an original operator physical-confirmation message
to the exact UID, image/source/build, named fixture, both excluded productDIN
feeds and the proposed U18 jumpers7→33 and12→35. Software emit-off is rejected.
This route observes3.3V MCU pads; it does not authorise connecting a5V DIN output
to a MCU input. A hash binds the operator's original record; it does not establish
physical truth or authorship by itself. The invoking owner must obtain that
record from the real operator rather than generate an attestation.

The completion directive's literal detector-readiness-before-programming rule
remains explicit. The first candidate cannot show its runtime detector readiness
before it has run. The operation therefore requires either fresh exact-image
prior raw readiness, or an original, exact-scope
`first-isolated-bootstrap-readiness-exception` decision covering runtime readiness
after programming but before stimulus. **That exception has not been granted.**
It is not a general-approval boolean. Its decision identifier is consumed once;
replay fails. Exact-scope operator authorisation does not expire merely because
preparation took time; physical observations and current ownership remain fresh
requirements.

After admission the gateway makes one candidate RFP `-pv` attempt, checks actual
write-and-verify log coverage, waits read-only for the exact admitted CDC path,
and opens one native owner. INFO/bind and detector resource readiness precede
the first bounded stimulus. All native owners assert DTR and leave RTS false;
closing the real owner supplies the native client-loss signal. Every exchange
shares the transaction's absolute deadline, including writes, partial reads and
cancellation. Capture ends by80s, reserving35s for one known-donor recovery
attempt plus5s margin within the120s interruption scope. Failure still takes
the recovery path. Recovery failure, including a missing/changed recovery file,
is preserved; no second programming attempt or owner takeover occurs.

The original successful donor RFP1.17 log was read, not rerun. The new parser
accepted its actual target-memory verification range and original log SHA256
`1cd9dbe2118363a23d08ebc758fc419445b7e1d58113a095ce4737214a602fc7`.
`-pv` is a target-memory comparison, not a separately exported memory dump;
exit0 without the actual verification stage, complete range, named probe,
target and probe-power-OFF evidence fails.

The agent prepares a template offline with:

```sh
python -m ael.titan_capture isolated-template --manifest EXACT-BENCH-MANIFEST.json --output NEW-ISOLATED-MANIFEST.json
python -m ael.titan_capture isolated-preflight --manifest NEW-ISOLATED-MANIFEST.json
```

The template deliberately contains no physical confirmation or bootstrap
authority and refuses until original records are supplied. Once actual authority
and connection exist, the single existing gateway action is
`python -m ael.prism --lane titan --source KX-TITAN --target titan-native --action bench-trial-qualify-isolated --deployment-manifest ADMITTED-MANIFEST.json --out NEW-RUN`.
This is agent-facing tooling, not another sequence of programmer chores for
Captain. No invocation against hardware has occurred.

### Current host evidence

New tests exercise the actual framed single-owner session, 100 complete paired
epochs, independent ordered payload decoding, stale/malformed/status/register/
edge-count failures, USB calibration faults, strict raw chunk identities,
fault draining, partial header/body retention, device disappearance, delayed
INFO/bind/chunk/cancel, single-use authority and recovery after failure.
The actual C++ native Session helper also emits a host-model fixture into this
independent Python parser under ASan/UBSan. That pairing exposed and fixed the
initial-FRMNUM baseline versus first-transition distinction; it is explicitly
HOST_MODEL_ONLY, never physical evidence.

Controls now verify all requested and unchanged fields plus a fresh GET after
PATCH through the same owner. The disconnect-check helper uses an actual
close/reopen of that owner with DTR semantics and an ownership check; no reset
or second writer is introduced. All tests use emulated endpoints.

The final schema pin is source-readback-bound to
`5dda123060c60de0ff6777b63ab6c3cdc96ddd2ab4298b2501d781c8ab20c0b1`.
The native helper pairing and retained RFP parser results are
`native-capture-model-pair.json` and `retained-rfp-log-parser.json` in the AEL
scratch directory. Source/diff and actual consumer outputs were inspected;
images are N/A for these software changes. The physical connector schematic
inspection is recorded separately above.

The actual final Kx checkout `6f21ea543fbb8eebe8895a1f7f409e2ca95111e6`
was clean when the existing AEL validators consumed both final receipts. They
accepted 34 sanitised positive cases plus two passthrough comparison executions
(36 positive execution rows), 69 compiled faults and the actual bound native
build. This remains host/build evidence. The image SHA256 is
`b8faf6da7febe8133291d16ceaeef204c50547724d08c2e08e653d142e91d7e9`;
source-profile SHA256 is
`942db38d24a54c678ec9305c6d813d1df2eb10ba2c7fd57ff32658c3d6c8f18b`.
Original final records are in `current-native-consumers-final.json` and
`native-capture-model-pair-reviewed.json` under the AEL scratch directory.

The concrete offline files `candidate-bench-manifest.json` and
`isolated-candidate-manifest.json` bind that image/build/source and the sealed
donor recovery. All authority flags are false; port, fresh identity preflight,
physical confirmation and bootstrap authority are absent. The actual gateway
command was executed with this manifest and refused the missing original
physical-exclusion record before any hardware action. Its retained result is
`isolated-final-refusal/result.json`. This demonstrates the real resume command
and its current gate, rather than claiming fixture readiness from a template.

The isolated acquisition/parser/transaction/session suite passed 101 host tests,
including the compiled native helper and actual template/preflight CLI paths.
These overlap earlier suites and are not added to their totals.


### Final integrated host checkpoint

The sixteen affected PRISM/drive/control/completion/endurance/campaign/waveform/
loopback/isolated-session test modules passed **583 tests, with12 intentional
skips**, in46.94s. The first integrated run retained one stale ownership-test
mock failure (missing stderr); the repaired mock supplies empty stderr and the
production owner-clear check remains strict. Logs are
`_scratch/titan-completion-20261008/final-integrated-pytest.log` and
`final-integrated-pytest-repaired.log`.

After that full run, commit `fccc4ce` moved candidate-attempt accounting to the
actual subprocess boundary. A changed image or pre-existing invocation/raw log
now refuses with zero candidate or donor programming; an ambiguous launch still
attempts the sealed donor recovery. Hardware access, attempt and verified -pv
readback are distinct facts. All42 affected isolated tests passed after this
refinement (`final-isolated-invocation-boundary.log`); the full-suite count above
is explicitly the preceding integrated source checkpoint.

The Swift player rebuilt successfully without starting audio
(`final-player-build.log`). Its binary hash remained
`5145e61539dea4a71fe470e1388bd5e5fc9c864f6d806e84a542505bc5da80fd`.
The actual r4-v2 A/C/D requests then passed `prepare_request` plus frozen-scene
validation; the fifteen-window endurance request passed the real completion
preparer. Their source-bound player hash did not change, so the requests were
retained without a new revision. Readback is
`campaign-r4-v2/post-player-build-preflight.json` under the same scratch root.

The final Kx source/build receipts were consumed through the actual AEL
validators at clean Kx HEAD `6f21ea543fbb8eebe8895a1f7f409e2ca95111e6`.
`current-native-consumers-final.json` retains the result; the count is34 sanitised
positive cases plus2 passthrough comparison executions,69 compiled fault cases
and210 build/run rows. The exact candidate offline manifests retain null physical
confirmation and bootstrap authority. The real isolated CLI refused before any
hardware access (`isolated-final-refusal/result.json`). No capture, programming,
serial owner change, playback or optical observation occurred.

Remaining path: obtain the exact physical exclusion/jumper confirmation and
scoped first-bootstrap authority; execute the bounded isolated transaction and
retain genuine100-epoch raw results; establish a defensible pin-to-capture timing
error bound and fitted LED timing applicability before positive electrical
qualification; then pass the existing output gate and complete the separately
admitted music/value/endurance and optical checks. Raw capture can expose count
or payload failures before timing qualification is available. Host evidence
cannot clear the conditional native-output HOLD. Images are not applicable to
this source/CLI checkpoint: the final diff and actual consumer output were
inspected; the earlier connector feasibility used the separately inspected
schematic render.

## 10 October: implemented split-edge recorder, first measured attempt

Firmware implementation `35e9362`, startup boundary test `e4e37e1`, and active
mutation coverage `2312262`; AEL collector/transaction `aaf83ef` and backend
dispatch `f2b15e2`. The matching build3 HEX is
`effacfa64ac8cf6a778126af1ada44e6bad7dc51c5a5919ec385c38aed9eecd5`,
source profile `18bbfe0614214c4ca5d405f1bbe8cc578438bd1560657215cec21df4411cd615`.
The 158 affected host tests and native-check4's 214 build/execution rows pass.
Earlier regression failures are preserved: obsolete mutation anchors and an
unused helper mutation were corrected to test the actual four-stream paths.

Actual transaction 16: `_scratch/titan-completion-20261008/isolated-split-edge-fast`.
Candidate programming/readback and native startup succeeded. Both input lanes
counted 256 edges, with exactly 128 timestamps in EACH of four polarity streams;
there were no adjacent duplicate timestamps. The short diagnostic nevertheless
FAILED with recorder fault5 (deadline). No complete frame or campaign acceptance
is claimed. Rising intervals were 389 ticks (95 occurrences) and 393 (32);
falling intervals were exactly390 (127), on both lanes. These raw results are
retained unchanged; the exact-period verifier has not been relaxed to accept them.
Microphone DMA callbacks advanced290 to414 on both channels at threshold encoding1.

The final SOF lower bound42675102 already covered trailing_end42569598, but the
owner reached its timeout check at44720240 before consuming the queued evidence.
A bounded service-latency repair is being investigated; the20ms limit and actual
audio workload remain unchanged. Source-derived IRQ/ELC timing uncertainty is a
separate unresolved acceptance question.

The transaction restored and verified the sealed donor in32.823s total internal
transaction time; fresh application INFO identified full donor build
`becb0186f0a66fbb04b0e0f4a79c0480b8b963db0fe3f518a91af9bb2dd2b5c7`.
`recovered-donor-confirmed/handoff-info.json` and `recovered-broker-live.json`
retain recovery identity and active broker evidence. Orange harness remains
excluded under Captain's standing physical confirmation; no wiring request or
optical-restoration claim is made. The connected-product HOLD continues.

### Split-edge service repair and second measured attempt

Commit `8bc1e0721388b11e6208508ea4088b534083c388` services the recorder before
and after audio processing, retaining end-of-loop service. Audio processing and
20ms acquisition deadline are unchanged. Affected sanitised lifecycle regression
passes, including refusal of genuinely late completion. Build4 HEX:
`e70cc38ddad8b0a4873a9a98f2c43f601e3371adc3f501e220610318faccb287`;
profile `fea1e97a236b56273658b5d70c6202e25f9fcf0cbc5047264492403d45a21adc`.

Transaction17 evidence: `_scratch/titan-completion-20261008/isolated-split-edge-service`.
Native identity matched, boot17, recorder state6/fault0. All four streams contain
128 timestamps; both counters256; zero duplicate entries. Capture arm-to-end
was12.465ms. Both falling streams have127 intervals of390 ticks. A rising:
96 intervals389 and31 intervals393; B rising:95 intervals389 and32 intervals393.
The verifier correctly retained FAIL at `Lane 0 first rising period mismatch at
bit 0`. No acceptance threshold was changed. Microphone callbacks315→400 each;
the collector's unchanged audio-health checks passed before this interval failure.

The short capture is therefore NOT ACCEPTED; complete streamed frame and frozen
100-pair campaign are NOT TESTED on this image. The completion/service defect is
repaired in this bounded test; complete payload and sustained audio reliability
remain unproved. Total candidate-programming transactions are17, with zero
accepted full-frame pairs. Neither short run exercised streamed LED DMA payload.

Manual R01UH1064EJ0130 Rev1.30 §20.4.4 pp845–846 documents the asynchronous ELC
path; §23.2.47 p985 and actual GTCLKCR0 confirm asynchronous GPTCLK. The formula
5 source-clock cycles +4 destination-clock cycles does not specify a complete
pad→IRQ→capture min/max jitter bound. §14.2.12/§14.5.6's three-sample filter rule
applies only when enabled; observed IRQCR1 has filtering OFF. Enabling that filter
would not independently establish downstream timing uncertainty. No invented ±5,
±28 or fitted-offset allowance was applied. The precise missing evidence is a
manufacturer-supported maximum edge-to-edge IRQ27/28→ELC→GPT4 timing variation,
or a source-justified capture configuration that removes this uncertainty. This
blocks the declared interval acceptance, not all isolated diagnostic work.

Donor programming/readback completed within32.747s internal transaction time,
then fresh application INFO identified the sealed full becb0186 build. Broker
was restored; evidence is `recovered-donor-confirmed/handoff-info.json` and
`recovered-broker-live.json`. Product harness remains OFF; two loopbacks unchanged.
Next engineering action: establish that timing bound/configuration, retain the
failed captures, then rerun the short acceptance before the full transition-rich
frame and100-pair schedule. No third GPIO or owner wiring intervention is justified
by these results. Electrical/product qualification remains separate.

### Direct GPT7/GPT12 redesign prepared — 10 October 2026

Supersedes the preceding next-action paragraph, preserving both failed captures.
Firmware commits b2bb689 and 003565e implement direct GPT7/GPT12 split-edge
capture; host commits fd6bb97 and daa03aa implement explicit version3 readiness,
collection, lane-local boundaries, strict verification and partial-failure retention.
LED and microphone resource ownership and the declared audio workload remain unchanged.

Candidate HEX SHA256: `0c8b72cd76c8052f25cc2dd5698a544af9828b64337fc0020f1ff609c00e2489`.
Source profile: `5dee68c81d903140183a5172543062ba7dcde88d8c9004a37dc14ada6dfdac95`.
KX evidence: `_scratch/music_visual_value_20261008/direct-capture/`.
Build PASS; native-check2 PASS (220 cases); final collector/isolation tests PASS
(195 tests). These are host results. Short device capture, full paired frame and
frozen 100-pair campaign on this candidate are NOT TESTED. No programming or
broker interruption occurred in this preparation. Existing transaction count remains17.

The new receiver endpoint is U18.36/P714 in the v1.0 reference schematic. Actual
fitted board revision is not established from the supplied enclosed-board photos.
Captain has been asked for that one physical fact. The prepared HTML connection
card is marked NOT RELEASED. Existing interruption authority remains valid; the
new physical wiring confirmation, preflight and bootstrap records remain null in
the draft manifest. Old wiring confirmation cannot admit the new endpoint.
Orange harness remains excluded under the standing owner statement; no optical
restoration is claimed. Last verified recovery remains the sealed donor identified
after transaction17, with broker restored.

The parallel transmitter review is `direct-capture/tx-service-review.md` in KX.
The 640 ns refill deadline has no demonstrated worst-case bound under the actual
combined workload. Counts and constant pulses do not establish payload correctness.
After direct short capture passes, the decisive test is a complete simultaneous
transition-rich frame. A trustworthy repeated payload/service failure triggers
the documented output-engine decision, with SPI_B evaluated against refill/tail,
pin-routing and ownership requirements; no audio reduction or threshold widening
is an acceptable repair. Electrical and product HOLD remains unchanged.

### Direct receiver attempt18 — actual hardware failure, donor recovered

Run: `_scratch/titan-completion-20261008/isolated-direct-fast`. Candidate HEX
`0c8b72cd76c8052f25cc2dd5698a544af9828b64337fc0020f1ff609c00e2489`,
source profile `5dee68c81d903140183a5172543062ba7dcde88d8c9004a37dc14ada6dfdac95`,
source HEAD `e155c88f0d2b1c0ec867225aa314a8cc64e9fb24`. Exact native identity
and initial resource readiness passed (boot18, schema3). Captain confirmed the
receiver repositioning; board revision remains unknown, not fabricated.

First epoch failed state7/fault7 (High) before stimulus. All four raw streams
are empty, both edge counts zero, stimulus ticks zero;128 SOF rows retained.
P603 PFS0x03010000 reads LOW; P714 PFS0x03010002 reads HIGH, matching initial
LOW mask1. Final LOW fields are unobserved, not evidence that both pins were HIGH.
No short pulse or streamed payload was emitted by this diagnostic. This failure
does not establish a transmitter service-deadline failure. The existing strict
HIGH guard correctly stopped stimulus. Capture configuration matches the intended
input/no-pullup/no-output-drive configuration. Actual P604 source level was not
sampled at that instant, so a source-idle fault and receiver connection/bias
mismatch remain distinguishable alternatives. Next bounded instrument change:
freeze both source and receiver pin levels and output timer state at the failure.
No threshold relaxation, receiver output drive or new wiring is justified yet.

Sealed donor programming/verification completed; internal transaction33.218s.
Fresh application INFO identified full becb0186 donor; broker restored with
updating telemetry (`recovered-donor-confirmed/handoff-info.json`,
`recovered-broker-live.json`). Orange harness remains OFF. No optical restoration
claim. Short acquisition FAIL; complete paired frame and100-pair campaign
NOT TESTED; zero accepted complete pairs overall. All failed raw records retained.

### Attempt19 — source/receiver discrepancy isolated

Firmware commit `e2a2e99` adds an immutable first-HIGH-fault witness before cleanup,
cleared only at next ARM. No pin-driving or acceptance changes. Build and JSON
writer checks passed. Candidate HEX
`01087fa563e342ee1059a75239fe605987c7efb0b57924459b46375f07029a95`;
source profile `8736b2c6340a4b8f1d76cfd01814a805b17eeb37078a660dd48ca062196909c8`.
Run: `_scratch/titan-completion-20261008/isolated-direct-idle-witness`.

Exact native boot19 and readiness succeeded; epoch1 again failed HIGH before
stimulus. Frozen witness: P601=LOW, P604=LOW, P603=LOW, P714=HIGH; all PinRead
return codes0. Both output GPT6/8 GTCR0, owner pending=false/ready=true. Reads
span2260 CPU cycles at1GHz (sequential, not an atomic electrical measurement).
This contradicts the expected connected P604-to-P714 idle path. It supports a
receiver connection/mapping/contact/bias problem, not a proven DMA service failure
or proof of which physical mistake exists. No new waveform was emitted.
The next required physical evidence is a clear view of actual header endpoints;
no repeated programming, tolerance widening or receiver output drive is justified.

Donor program/verify completed in33.140s internal transaction time. Fresh INFO
identified full becb0186 donor; broker restored. Saved paired broker observations
show audio hops4420→5024. Orange harness remains OFF; no optical restoration.
Short capture FAIL; full frame/campaign NOT TESTED, accepted full pairs remain0.
Total candidate-programming transactions19. This physical receiver discrepancy
blocks the current capture experiment, not all later independent computation.
The transmitter640ns budget and engine-exit decision remain open; this pre-stimulus
failure does not supply payload/service evidence for an engine verdict.

### Corrected fixture: short PASS, complete raw payload with deadline FAIL

Captain supplied photos showing both orange terminations near the microphone end,
then explicitly confirmed: “Done. 12 is connected to 36”. This supersedes the
previous inferred endpoint confirmation. A source/receiver mismatch was physical
fixture evidence, not grounds to weaken the HIGH gate.

Attempt20 `isolated-direct-corrected-fast` used unchanged e2a2e99 image
01087fa563e342ee1059a75239fe605987c7efb0b57924459b46375f07029a95.
Short128-pulse acquisition PASS: four complete streams; exact78-tick HIGHs;
raw consistency verified; no electrical timing qualification. Donor restored and
application identity verified;33.227s internal transaction.

Attempt21 `isolated-direct-pattern2` used the same image, frozen pattern2.
Complete raw data: four streams of3840 strictly increasing unique timestamps;
all rising periods390ticks; HIGH widths78/198ticks; falling intervals270/510.
Independent diagnostic decoding matches480 bytes AA on laneA and480 bytes55 on
laneB exactly, zero mismatches. However original state7/fault5 Deadline is FAIL
and is retained unchanged. This is not an accepted full pair. Captured payload
consistency does not establish a worst-case transmitter service bound.

Timing review identified redundant SOF barriers: trailing waits for a timing
row beyond its quiet boundary before freezing, then finishing waits for another
row beyond actual freeze. Bounded repair removes the intermediate wait while
retaining350us quiet, final timing coverage of actual freeze, and20ms deadline.
New candidate proof is required. No acceptance tolerances change.

Attempt21 donor recovery/application identity verified,34.555s internal time;
broker restored with fresh telemetry saved. Orange harness remains OFF. Total
candidate programming transactions21; full campaign NOT TESTED; accepted full
pairs0. Root/independent review decoded retained raw files without changing the
failed status or manufacturing a PASS.

### Attempt22 — redundant-barrier repair did not resolve completion

Commit `2125df1` removed the intermediate SOF wait while retaining the final
SOF bracket,350us quiet and unchanged20ms deadline. Candidate HEX
`4ac596eb8543fdf5879d264538e829e720c1c219aa749b32415f0a1fa7a60cd7`.
Run: `_scratch/titan-completion-20261008/isolated-direct-single-barrier`.
Actual result remains state7/fault5 Deadline: four3840-entry streams and
7680 counted edges per lane. The repair did not establish an accepted pair.

The deadline check precedes queued SOF consumption. Failure cleanup overwrites
the initial DMA-freeze timestamp; retained records therefore cannot distinguish
a late owner-service interval from absent timing callbacks. USB raw drain begins
after terminal failure and cannot explain this preceding timeout. No supported
USB-blocking diagnosis exists. The next bounded experiment adds immutable
pre-cleanup stage/queue timing evidence; it does not extend deadlines, reduce
audio workload or weaken acceptance.

Donor programming verification and fresh application identity succeeded; internal
transaction34.444s. Broker restored, PID29770; saved paired observations show
audio hops42026→42632 (`recovered-broker-live.json`). Orange product harness
remains OFF; corrected12→36 and7→33 remain fitted. No optical restoration claim.
Total candidate-programming transactions22; accepted full pairs0;100-pair campaign
NOT TESTED.

Independent run22 diagnostic decode: all four streams unique and strictly
increasing; HIGH widths1920×78 and1920×198 per lane; rising periods390;
exact A=AA×480/B=55×480 payloads with zero mismatches. Microphone callbacks
273→808 on each lane; errors[0,0], clock rejections0, restart attempts/failures0.
Output timeout/recovery counters remained1→1; transmitter failures0→0. These
observations preserve the original Deadline FAIL and do not qualify timing.

### Attempts23–24 — first valid pair, then measured scheduling failure

Firmware `66a7f25`, AEL `dc95fac`, candidate HEX
`60a867a53e523aad5b9017960bcc64d970902f07dd45c10a7ac7dcae43158ea8`.
The immutable timing witness preserves pre-cleanup queue state and original
DMA-freeze time. Focused firmware/host tests and independent review passed.

Attempt23 `isolated-direct-timing-witness`: full frozen pattern2 pair PASS for
raw digital consistency,3840 bits/lane, exact payload and healthy microphone
progress. Completion14.753ms within unchanged20ms window. Maximum audio stage
5.663076ms, polling gap5.668388ms, USB87.032us. Queue575/575, no drops.
Electrical timing remains unqualified. Donor recovered and freshly identified.

Attempt24 `isolated-direct-campaign`: frozen sequence began at pattern0 and
passed epochs1–6; epoch7/pattern6 failed Deadline. Campaign FAIL, not6/100 PASS.
Terminal witness:20.427ms window; initial freeze GPT7 tick43100158; terminal
45033661; queue600 produced/577 consumed, no drops, latest producer45000126.
Latest audio stage5.646064ms; maximum5.662640ms. This directly supports delayed
foreground completion servicing while timing callbacks continued; it does not
support missing reference callbacks or USB drain as the cause.

Next bounded repair: cooperative fixture service checkpoints between existing
audio stages, preserving workload/order, production inputs and frozen deadlines.
No reduction of audio work or acceptance relaxation. Full100-pair campaign also
has a distinct transaction-throughput constraint: observed about1.7s per epoch
cannot fit100 epochs into the current collection budget. Resolve that runner
constraint explicitly after scheduling proof; never select successful epochs
from failed campaigns.

Attempt24 donor programme/verify and fresh application identity succeeded,
44.619s internal transaction. Broker restored with advancing telemetry saved.
Orange product harness remains OFF; both loopbacks unchanged. Candidate-programming
transactions24; seven individually accepted digital pairs across attempts23–24,
zero completed100-pair campaigns. No electrical or optical qualification.

### Attempt25 — cooperative service repair passes prior failing pattern

Firmware `c1f75cbf16e79208841de814b04c082bed76533b`; host `af4c2e8`.
Candidate HEX `c92c37ba54c678f267ab268c1a49359a5493a9391daa8181fe2877c2c0d3022e`.
Run: `isolated-direct-cooperative`; frozen pattern6 full paired raw consistency
PASS with healthy microphone progress. Completion13.175ms; longest uninterrupted
audio segment3.271883ms and poll gap3.278420ms. Queue571/571, no drops.
The preserved audio workload now has foreground recorder/output service points
between stages. Sanitised nonzero audio/state/output equivalence tests passed.
This single pass supports the repair but is not sustained qualification.

Terminal drain uses negotiated1000-word chunks in the existing4096-byte response
buffer, with no enlarged capture buffers. Actual epoch acquisition/drain1.1244s,
still too slow for100pairs within60s collection. Transport throughput remains
a concrete campaign blocker; no deadline or acceptance relaxation is authorised
by this result. The next action is source-bound throughput repair and measurement.

Donor programming verification, application identity and broker restoration
confirmed; internal transaction34.295s. Saved fresh broker observations advance.
OrangeOFF/loopbacksunchanged.25 candidate transactions;8 accepted individual
digital pairs across attempts23–25; no completed100-pair campaign or electrical
qualification. Known timing offsets may only be accounted for with justified
error bounds; missing/duplicated events are not correctable by a tolerance.

### Attempt26 — bounded USB driver progress improves transfer

Firmware `2dbfa861fe16d1ae1ff71c799d7cf3f6ec32b141`; candidate HEX
`f5ce8a01fa10fdbe30db68effca96eb98c2553d8a3e314b2eedb0795f33ef60f`.
Run `isolated-direct-usb-progress`: fullpattern6 raw consistency PASS, capture
12.243ms. Terminal-only driver progress performs at most4 task steps per audio
checkpoint and defers all command/disconnect handling to the outer owner loop.
333 pump calls; maximum123452cycles at1GHz (123.452us).

Epoch arm-to-drain span0.741789s versus1.124423s previously, but this excludes
final status/audio/verification overhead. Whole single acquisition0.967711s.
17 DRAIN calls554.859ms; body reads15.7–41ms remain dominant. Therefore full100
still does not fit the unchanged60s acquisition limit at observed throughput.
This is a concrete transfer-budget blocker, not justification to widen timing
tolerances or hide errors. Next: source/map-bound larger transport batching and
fixed task-service capacity assessment; do not expand raw buffers to conceal loss.

Donor program/verify and fresh application identity confirmed; internal34.129s.
Broker restored and paired advancing telemetry saved.26 candidate transactions;
9 accepted individual digital pairs; no complete100-pair campaign. Orange product
harness OFF and loopbacks unchanged. Native-to-product HOLD remains.

### Attempt27 — terminal-session service lifecycle verified

Firmware `b036a26804df56d07907ee9c4c3b98001d9b06d4`, HEX
`340a87b5a790a3eff9e625f32af07919274a04d3b4ba90c021b2d9e689d39256`.
Run `isolated-direct-usb-terminal`: fullpattern6 raw consistency PASS; capture
12.413ms. Explicit admitted terminal-session flag keeps USB service through
final observations and closes on validatedCANCEL/disconnect. Maximum8 steps
per checkpoint, measured max230288cycles=230.288us;245calls.
Arm-to-drain0.600866s (excludes terminal checks/verification), improved from
0.741789s but still insufficient100-pair margin under unchanged60sbudget.
No further blind step-count tuning justified; next source-bound decision must
identify driver servicing frequency or remaining batching/host overhead.
Donor programming/application identity verified; internal33.767s; broker restored
with advancing paired telemetry saved.27transactions,10 accepted individual
digitalpairs, no completed100-pair campaign. ProductharnessOFF unchanged.

### Attempts28–29 — complete frozen100 digital campaign PASS

Firmware `6af1e7d6a8603c3f1fe2fd51e769471a883c2f10`, candidate HEX
`640906014b0f2192ff349b03a017ef83ebaf6d607e6c379b8336982ebf39d593`;
host collector implementation `af4c2e8` and exact file hashes in manifests.
Native-owned source and tempo calculations now permit bounded USB-only progress
after completed groups of8bins/kernels during terminal drain. Arithmetic/input/
workload/order unchanged, noCore/vendor edits. Sanitised actual nonzero state,
array and output equivalence plus callback-cadence tests and review passed.

Attempt28 `isolated-direct-usb-inner`: pattern6 full raw pair PASS;12.487ms
capture;0.474654s arm-to-drain; measured steady estimate0.559964s including
terminal observations and host verification. Donor freshly identified/restored.

Attempt29 `isolated-direct-full100`: COMPLETE FROZEN DIGITAL CAMPAIGN PASS.
Exactly100epochs/patterns0..99 in original order,100 consistent outcomes.
Each pair requires3840bits on each lane, exact independent expected payload,
strict polarity/order/count and terminal/rearm checks. No selected-success merge;
one exact image and boot29. Arm-first to last-drain53.581154s, within unchanged
60s collection and80s candidate cutoff. Internal transaction including donor
program/verify86.736690s, within120s. Fresh donor application identity separately
verified; broker restored and advancing observations saved.

Microphone capture errors[0,0], clock rejections0, restart attempts/failures0.
Callbacks274→17644 on each lane. Transmitter failures0→0; no first-fault snapshot.
INFO output_timeouts1→1 and recovery_attempts1→1 record one real, recovered
pre-campaign supervision timeout. Source ordering supports delayed foreground
completion recognition; the exact startup blocking stage was not recorded.
There was no additional timeout or output recovery during the campaign.
MaxUSBpump257292cycles. Absolute timing remains unqualified: all epochs retain
the calibration error `Unbounded USB observation bracket` and physical
qualification false. Fresh donor readback identifies UID/build; its wrapper
does not claim an accepted checkpoint, and a skipped lsof check is not evidence
of a freshly observed free port.

This establishes raw digital consistency for this exact measured campaign, not
nanosecond accuracy, representative DIN voltage/level-shifter performance or
product electrical release.29candidate transactions;111accepted individual
digitalpairs including this complete100. Historicalfailedruns retained unchanged.
Orange product harness remains OFF; both corrected loopbacks unchanged.

Next original-assignment operations: existing target golden/proxy computation
and dedicated estimator cost under their actual isolated prerequisites; separately
resolve fittedLED/outputpath electrical evidence before native product connection,
then physicalI/A/C/D, liveD, controls/fault/disconnect, endurance and ownerreview.
No A-minus-D estimatorcost inference and no newSAM/research campaign.
