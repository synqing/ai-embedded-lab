# PRISM lane automation

This extends the existing AEL runner, adapter registry, evidence writer and zero-retry policy. It does not install a second test framework. Results distinguish the named PRISM scaffold from externally referenced donor firmware. See the [validated three-lane report](../reports/lanes-2026-10-03/README.md) and [reusable procedure](skills/prism_lane_bench.md).

## Native product candidates

`product-build` executes the lane's recorded `scripts/build.py` against its
canonical tagged Core pin. It creates fresh native images and dependency maps,
then verifies source, object, compiler, runtime-library and image hashes. Donor
and sibling-lane sources, reference archives, development Core overrides and
source changes during compilation are rejected. The result is classified
`PRODUCT_CANDIDATE`: native compilation does not close missing musical/effect
behaviour, controls, timing or physical qualification.

Each application has its own required ELF and map: ARM RT1062 and Xtensa S3
for DualMCU, ARM M85 for Titan. Swapped, missing or extra applications fail.
The RT1062 and M85 maps must contain the shared musical Runtime; the radio
companion map must not. This checks image ownership, not complete semantics.

```bash
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane dualmcu --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-DualMCU --action product-build --out _scratch/prism-dualmcu-product
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan --action product-build --out _scratch/prism-titan-product
```

Each lane must have committed its owned source and pin before these commands;
each `--out` must be unused. No serial connection, programming, reset or recovery
occurs. Existing `build`, `flash` and `recover` refusal guards remain until the
corresponding product and deployment admission requirements are met.

`product-test` runs the existing lane-owned native host checks:
`scripts/native_test.py` for DualMCU and `scripts/native_check.py` for Titan.
It binds the committed source and pinned Core, positive compile/execution
records and rejected compiled faults. The result is
`NATIVE_HOST_CANDIDATE_CHECKS`; it does not mark the untested behaviour inventory
complete. Reference-capsule inputs, failed checks, surviving or uncompiled
faults, development Core, changed logs and false hardware/admission claims fail.

```bash
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane dualmcu --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-DualMCU --action product-test --out _scratch/prism-dualmcu-native-tests
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan --action product-test --out _scratch/prism-titan-native-tests
```

## PRISM-owned reference builds — migration increment

The migration adds `bench-build`, `regression` and read-only `diagnose` to the
same adapter. The first two execute each lane's recorded `scripts/bench.py`
against its immutable dependency capsule, without an old firmware checkout.
They retain `BENCH_ONLY` qualification. Neither grants clean product admission
or a physical deployment verdict. `build`, `flash` and `recover` continue to
refuse until an admitted native product/deployment profile exists.

Run with the existing Python environment from this repository. Every AEL output
must be fresh. AEL stages lane inputs and binaries in a separate fresh directory
under that lane's `_scratch/ael/`; the AEL evidence directory may be elsewhere.

```bash
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane dualmcu --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-DualMCU --action bench-build --target rt1062_production --out /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-DualMCU/_scratch/ael-rt41
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan --action bench-build --out /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/_scratch/ael-titan-build
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane dualmcu --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-DualMCU --action regression --out /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-DualMCU/_scratch/ael-dual-tests
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan --action regression --out /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/_scratch/ael-titan-tests
```

The adapter requires an executed operation receipt with a recognised schema,
successful command and receipt exit codes, explicit bench classification and
false product/device claims. Firmware bytes must match the receipt hashes.
Missing receipts, missing firmware, source drift, unrecorded or linked entry
points, wrong target IDs and false admission claims fail. AEL does not restart
hardware or retry these operations. `core-test` remains a separate check of the
tagged dependency; lane reference builds are not PRISM-Core admissions.

The following donor-baseline procedure and observations are historical. The
current capsule builds above use the PRISM lane scripts: Titan preserves
`SOURCE_DATE_EPOCH` and enforces the compiler hash/version and FSP header lock.
Donor-baseline nondeterminism and scaffold descriptions below describe the
earlier run, rather than the newly admitted component/reference-build capability.

Use the existing Python 3.11 environment. The workstation's default Homebrew Python 3.14 currently has an incompatible `pyexpat` linkage; it is not the validated interpreter.

```bash
cd /Users/spectrasynq/ai-embedded-lab
PY=/Users/spectrasynq/.platformio/penv/bin/python
PRISM=/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM
DUAL=/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-DualMCU-Firmware
TITAN=/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001
"$PY" -m pip install -r requirements-emotiscope.txt
"$PY" -m pytest -q tests/test_prism_lane.py tests/test_emotiscope.py tests/test_pack_loader.py tests/test_runner_nonretryable.py tests/test_runner_retry_policy.py tests/test_pack_transport_abort.py tests/test_evidence_contract.py tests/test_failure_recovery_contract.py

"$PY" -m ael.prism --lane dualmcu --source "$PRISM/K1-DualMCU" --action discover --out _scratch/reproduce-dual-discovery
"$PY" -m ael.prism --lane dualmcu --source "$PRISM/K1-DualMCU" --core-source "$PRISM/PRISM-Core" --action core-test --out _scratch/reproduce-dual-core
"$PY" -m ael.prism --lane titan --source "$PRISM/Kx-Titan" --core-source "$PRISM/PRISM-Core" --action core-test --out _scratch/reproduce-titan-core

"$PY" -m ael.prism --lane dualmcu --source "$PRISM/K1-DualMCU" --donor-source "$DUAL" --action donor-build --target rt1062_production --out _scratch/reproduce-rt41
"$PY" -m ael.prism --lane dualmcu --source "$PRISM/K1-DualMCU" --donor-source "$DUAL" --action donor-build --target rt1062_k1_migration_t40_ws2812_128 --out _scratch/reproduce-rt40
"$PY" -m ael.prism --lane dualmcu --source "$PRISM/K1-DualMCU" --donor-source "$DUAL" --action donor-build --target s3_radio_bridge_ble --out _scratch/reproduce-s3-bridge
"$PY" -m ael.prism --lane titan --source "$PRISM/Kx-Titan" --donor-source "$TITAN" --action donor-build --out _scratch/reproduce-titan-build

"$PY" -m ael.prism --lane titan --source "$PRISM/Kx-Titan" --donor-source "$TITAN" --build-receipt _scratch/reproduce-titan-build/build/receipt.json --action observe --seconds 30 --out _scratch/reproduce-titan-live
# Explicit recovery of the existing host owner only; does not reset/flash Titan.
"$PY" -m ael.prism --lane titan --source "$PRISM/Kx-Titan" --donor-source "$TITAN" --build-receipt _scratch/reproduce-titan-build/build/receipt.json --action donor-recover --seconds 30 --out _scratch/reproduce-titan-owner-recovery

# Existing native donor bridge tests, no hardware I/O:
(cd "$DUAL" && "$PY" harness/run_native_env_gxx.py native_bridge_protocol native_bridge_transport native_s3_radio_core native_ble_dualmcu_host)

# Standard lane: existing verified build/flash/test adapters, unchanged.
"$PY" -m ael.emotiscope --source "$PRISM/K1-S3" --action build --out _scratch/reproduce-standard-build
"$PY" -m ael.emotiscope --source "$PRISM/K1-S3" --action flash --out _scratch/reproduce-standard-flash
"$PY" -m ael.emotiscope --source "$PRISM/K1-S3" --action observe --seconds 30 --out _scratch/reproduce-standard-observe
"$PY" -m ael.emotiscope --source "$PRISM/K1-S3" --action test --seconds 30 --resets 1 --real-music-confirmed --out _scratch/reproduce-standard-regression
```

Every `--out` must be unused. Use the real-music flag only when music is audible at the microphone. Core checks require Node/npm and a C++ compiler; Acorn is installed from the pinned lock into a disposable copy, never the read-only vendor directory. AEL serialises these checks because upstream v0.2.0 uses `/tmp/k1live_cases`. Do not run that upstream script independently at the same time.

DualMCU builds use the installed PlatformIO packages and the donor's declared dependencies; fresh workspace/build/library directories prevent reuse of old object files. The exact installed versions are recorded in the build logs. The dirty WS2812 driver is explicitly fingerprinted; this is not a claim to reproduce that build from the donor commit alone. Its preserved patch is in the report.

Titan uses the donor's native `scripts/build_scalar.py`, installed Arm GNU 13.3.1 and existing RT-Thread/FSP BSP. The builder verifies its pins and emits source hashes, ELF/HEX, link map and size report. Its compiler date/time strings remain nondeterministic because the staged SCons compiler environment drops `SOURCE_DATE_EPOCH`; matching build IDs bind source/configuration, not identical HEX bytes.

Titan observations require the existing `com.spectrasynq.titan-broker` owner and `/tmp/titan-emotiscope-control/live-stats.json`. The adapter checks USB identity, exact owner arguments, source/build/schema, freshness of each device topic, continuing audio/LED counters, changing frame CRCs and no new capture/LED faults. The broker's admission boolean is recorded, not rewritten. A read-only observation PASS does not grant control or programming admission.

At the original scaffold baseline, neither lane contained a native application.
The current native `product-build` and `product-test` entries above now execute
owned applications and their tests. `build`, `flash` and `recover` still fail
closed because full product/deployment admission remains open. DualMCU
`observe` refuses a single S3 Emotiscope as a substitute for both chips. A donor
build is never automatically flashed; hardware side effects are never retried.

For Titan image recovery, preserve the existing donor's `scripts/programme_rfp_swd.py`, E2 Lite identity and current image-bound admission procedure; this run validates owner recovery only. For standard image recovery, use the preserved [original recovery procedure](../reports/emotiscope-baseline-2026-10-03/README.md). Never write a Titan/Teensy image to `/dev/tty.usbmodem12201`.

## Titan native flash: off-product output proof required (8 October 2026)

AEL currently holds **all native candidate flashes** before any lock or hardware
access. The structural `output_qualification` input uses a JSON proof with schema
`prism.titan.output-qualification.v1` for the exact image SHA-256, `off_product: true`,
`method` in `pin-loopback` / `logic-capture` / `dummy-load-bench`, `lanes_verified`
`["A","B"]`, `frames_completed >= 100`, `stuck_high_detected: false` and bound raw
evidence. These v1 fields are structural assertions. AEL currently has no independent
acquisition verifier for any of these methods, so even structurally complete proofs
refuse with `OUTPUT_QUALIFICATION_UNAVAILABLE`: native flash remains HOLD. A two-row
CSV cannot establish 120 completed frames or electrical timing.

Recovery (`bench-trial-recover`) is exempt only for the scope-locked known donor
HEX SHA256 `df7a33785ac2a12b01e5065722ba9ce8bb758802e1bbd0d78e4bfc92007dd776`,
UID `545433931bd25436593630352d068363`. Its recovery object must bind `derivation`
and `qualification_receipt` files in addition to `image`, recipe and provenance.
AEL checks the actual immutable derivation and successful executed recovery receipt
and rejects a candidate disguised as recovery before owner or hardware access.

Why: on 8 October 2026 three host-qualified native images were flashed onto the
owner's Titan. The first never started capture or LEDs; the second drove the B half
full white (lane B on GPT8 output A instead of GTIOC8B); the third completed no LED
frame (141 timeouts) and drove the whole strip full white. The owner's strip is never
the detector. Record: Kx-Titan `docs/migration/NATIVE-FIRST-BOOT-2026-10-08.md`.

## Explicit native development bench trials

`bench-trial-plan`, `bench-trial-flash`, `bench-trial-recover`,
`bench-trial-observe` and Titan-only `bench-trial-control` run through the
existing `check.prism_lane` runner with retry budget zero. They are development
operations; general `flash`/`recover` and product-release refusal remain intact.
Dual diagnostic profiles retain **BENCH_ONLY** classification. The adapter
validates the actual build receipt, committed source, generated inputs, compiler,
linked objects, image/map hashes and target before constructing a command.

Use the Python3.11 installation used by the existing tools:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism \
  --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan \
  --action bench-trial-plan --target titan-native \
  --deployment-manifest /absolute/path/titan-native.json --out /fresh/output
```

Replace `bench-trial-plan` with the explicit operation only after its receipt
inputs and scoped hardware prerequisites have been resolved. `bench-trial-plan`
never opens hardware; successful planning does not mean a write is authorised.
Plans lacking a resolved S3 interface deliberately emit no uploader argv.
Supported targets are `prism_rt1062_t40_bench128_diag`,
`prism_s3_ble_bench16_diag` and `titan-native`. No active dirty lane is built.

The manifest schema `prism.bench-trial.v1` is a deployment input, **not** a task
registry or formal certificate. It binds `source_commit`, `build_receipt`
(path/hash), `image` (path/hash), exact `target`/`identity`, `permitted_range`,
`port`, `recovery` (image, provenance, restore method), and actual `authority`
decisions. Dual observation also binds `diagnostic_binding` and
`source_binding_hash`; S3 permits only app0 at0x10000 with an erase end below
0x650000. Titan binds the original RFP backend path/hash and reuses its sealed
UID, SWD speed, E2Lite selection, power-off flags, range and `-run` command
builder with the **native** image and receipt. No donor metadata is fabricated.
The existing `K1_RFP_SWD_EXECUTE_OK=1` execution gate is retained.

Before hardware use, `preflight` must bind a fresh (≤120seconds) JSON receipt
with observed target/identity/port, `owner_clear`, actual observation `method`,
and hashed `raw_evidence`. Teensy writing additionally requires
`loader_targets:["20731830"]`, exact exclusive loader ownership and accepted
settings-loss/recovery decisions. A product name alone is insufficient. Do not
manufacture a preflight or set authority flags from assumptions. The operator
must re-identify the interface immediately before use. AEL serialises hardware
transactions with one process lock and refuses an existing serial owner.
Opening S3 CDC may reset it; this must be accounted for before observation.

For the isolated Titan fixture, Captain's explicit instruction that the wiring
remains unchanged until he reports a change or the agent requests one may be
retained in the existing physical-confirmation record as
`validity: "until-wiring-change"`, with `continuity_quote` copied from the bound
original message. Keep its original observation time. This instruction changes
the validity of that physical fact only: live target/owner preflight still needs
fresh evidence, image scope must still match, each transaction authority remains
single use, and programming/capture/recovery deadlines are unchanged. Retire the
record immediately when a wiring change is reported or requested; records marked
`wiring_change_reported` or `wiring_change_requested` are rejected. Without the
explicit standing instruction, the existing 120-second physical freshness check
continues to apply. Neither form releases the connected-strip HOLD.

Recovery consumes separately bound actual recovery bytes, never the candidate
as a substitute current backup. S3 recovery is restricted to a covered app-slot
slice; no bootloader/partition/NVS/full-flash erase is supported. Tool exit status
and actual invocation/image hash are recorded separately from runtime boot and
optical proof. Programming has no blind retry and its process is not killed by
an arbitrary timeout midway through a flash.

Titan observation uses native `K1S1/K1R1` CRC framing, INFO1, observation21/23/24/26,
and UID/source/schema/boot checks. It records raw packets, decoded snapshots and
rates computed from device capture timestamps/sample counts, never buffered
host arrival times. Unsupported source scalar fields and per-half physical DMA
rate remain unmeasured. For an explicit atomic control/save operation:

```sh
# request.json: {"fields":{"9":6,"15":100},"save":true}
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism \
  --lane titan --source /absolute/Kx-Titan --target titan-native \
  --action bench-trial-control --deployment-manifest /absolute/manifest.json \
  --native-request /absolute/request.json --seconds 60 --out /fresh/control-output
```

Field9 is mode, field15 physical brightness, as defined by native ControlOwner;
these are **not** historical control IDs or MIDI CC numbers. Atomic controls use
current boot/revision, a fresh request identity and native binding0x50520001;
save0x50520002 is a separate checked operation. Accepted/rendered/emitted remain
distinct. Dual controls stay on the real selected BLE-MIDI path; the diagnostic
collector is not a replacement control injector. Neither helper resets or
reconnects hardware automatically, changes playback, or takes another owner.


## Source-bound Titan evaluation-drive replay (host implementation)

Prepared donor `I` requests use the existing campaign, Player, durable playback
ledger and `observe_titan` consumer. Validate a prepared request without starting
playback or writing the ledger:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism_campaign \
  --incumbent-request /absolute/comparison-requests/trial-I.json \
  --out /fresh/donor-consumer-validation
```

Only the sole hardware execution owner runs the same command with
`--execute-incumbent --donor-observation /absolute/donor-observation.json`.
That observation file supplies the existing `owner_dir`, `donor_source` and
`build_receipt` paths. The consumer reads the existing broker's evidence and
checks its process, UID, source, build, schema, audio progress and transmitter
progress; it opens no serial port and performs no programming or recovery.
The native image admission path is not used for donor playback.

The consumer retains a three-second source-bound donor preflight before making
the full-duration reservation in the shared ledger. A reservation precedes
Player construction and remains charged after failed startup, cancellation or
timeout. The frozen media, passage, campaign, private order and common gains
are checked; once-attenuated playback uses unity engine gain. Observation runs
for the complete requested duration with a five-second execution reserve.
Cancellation stops only this consumer's Player and its observation worker.
The final Player log must report the complete original frame count; changed
media, missing end reports, changed owners and brightness drift are refused.

Results explicitly cover donor broker telemetry and Player completion. The
frozen brightness is checked at 100, but the existing donor telemetry does not
provide the full 18-word control readback. Full donor control parity, acoustic
route timing, connected electrical qualification and optical comparison remain
separate gates. A validation or telemetry result does not award owner ratings.

The implemented replay stays inside `bench-trial-control` and its current
manifest, native-control authority, exclusive owner, lock and zero-retry path.
Prepare a request offline with `python -m ael.prism_drive`: required arguments
are `--trace --freeze --verification --verifier --media --timing --arm --out`.
Each file argument is an actual path; preparation hashes it and refuses changed
source/recomputation evidence. The output is the `--native-request` consumed by
the existing control action. Preparation opens no port and plays no audio.

Trace schema `titan.music_value.trace/2` uses 12800 Hz, 64-sample hops and the
frozen common Analog scene. The original source, once attenuated FLOAT playback,
transformed PCM, level tool, independent source-recomputation receipt, verifier,
trace, freeze and player binary are bound. Input conversion gain is 0.5;
the transformed playback runs with unity engine gain, explicitly checked in
the player's start report. No second attenuation or per-arm normalisation occurs.
B remains unavailable where a genuine designated drum stem is absent; C carries
the offline flag and unqualified teacher status.

Replay uses existing CRC-framed native opcodes 0x50524401–04 after UID, schema,
source and boot binding. Trial IDs increase within a boot; the session header
hash includes source and media identities. It requires the native
`programme-and-precision-reset-on-open-v1` initial-state contract and an exact
reset-counter increment before sending records. Full frozen controls are applied
once; experimental settings are never saved.

Records leave the host only after their media window has played. The audio
render-position clock, reported latency and explicitly declared route offset
define pacing. Device clock offset/drift and uncertainty estimates come from
bounded status-exchange brackets. Defaults bound chunks to four records, host
lateness to 20 ms, clock freshness to 100 ms and pending arrival witnesses to32.
High watermark, old boot, expired session, clock rewind, stale playback and
ambiguous response abort without retry. The owner port closes on exit; the
native 250 ms lease and 150 ms fade preserve finite fallback.

Native v1 is a FIFO consumed by the rendering path; this is not future device
deadline scheduling. Separate pacing and source-bound arrival logs retain
accepted sequence and device timestamps. Consumed, rendered and completed
counters remain native witnesses. Physical timestamps, acoustic route timing
and optical appearance remain unqualified unless independently measured.
A render-only timing file may explicitly use
`{"extra_s":0,"uncertainty_s":null,"basis":"render-only-unqualified"}`.
A measured-route declaration requires a bound evidence file and finite
uncertainty; no offset is inferred from packet arrival.

See [host closeout](../reports/titan-drive-host-2026-10-08/README.md) and the
[existing bench procedure](skills/prism_lane_bench.md). Native output HOLD still
prevents an actual physical experiment.
