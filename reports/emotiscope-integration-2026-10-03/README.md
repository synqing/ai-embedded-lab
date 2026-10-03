# AEL → Emotiscope implementation closeout

Six applicable component groups are implemented and physically verified. The
remaining seven groups are explicitly rejected or not applicable in
[MATRIX.md](MATRIX.md), with all 4,048 upstream implementation/configuration/tool
files assigned once in [component-inventory.json](component-inventory.json).
The requested separate Deep Research report is no longer a dependency.

## What works

`python -m ael.emotiscope` now uses AEL's existing runner, result/evidence schema
and UART evaluator to operate the real Emotiscope. The pack builds the existing
application, flashes through its native identity guard, monitors it, exercises
native waveform/palette controls, tests rejection paths, resets it, measures
runtime behaviour and verifies restoration. It never generates replacement
firmware or writes a model to the device.

AEL contains a host-agent engineering workflow, not an embedded ML engine. Its
model.py files describe device/instrument metadata; no model binary, tensor
pipeline or embedded inference implementation exists in the pinned source.
Inference/model measurements are therefore NOT APPLICABLE, not omitted tests.

## Source authority and history

- Preserved starting checkpoint: `d4c3282`; recovery evidence is unchanged.
- AEL upstream: `a95dd2639019c6366c92d2bdb78561a9f89855eb`.
- Matrix and fresh legacy baseline: `c097378`.
- Working AEL adapter/pack/tests: `dc50c3b`; strict steady-state error rejection: `9be9928`.
- During execution the old firmware tree explicitly handed ownership to
  `/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-S3`.
  The guard detected the concurrent device identity change before controls.
  [AUTHORITY.md](AUTHORITY.md) preserves this sequence and the stale lane finding.
- Final tested/deployed firmware:
  `181cb92a4e660eaeae281ad3c081cf1b420f81f3`, epoch `1790997874`,
  `k1_emotiscope_live`. PRISM-Core v0.3.0 is pinned by that source.
- K1-S3 deployment record and copied raw device evidence were committed as
  `a15b39b`. That later documentation commit is not the running firmware identity.

No legacy firmware algorithm, device task or driver was changed by AEL. The
native guard/build/test code remains in K1-S3. Its immutable GPL-lineage bench
capsule and shared Core provenance remain distinct from new host integration.

## Actual execution evidence

| Check | Observed result | Evidence |
|---|---|---|
| Fresh build from old current source | RAM 159252 B, application flash 1024974 B | fresh-baseline-build.log |
| Fresh legacy guarded flash | 85 host tests; b05cbd2c verified on device | fresh-baseline-flash-retry.log |
| AEL guarded current-lane build and flash | 85 host tests; byte-identical build/flash binary; correct source identity | lane-build/, lane-flash/ |
| New and existing AEL boundary tests | 24 passed, including planted failure cases | integration-host-tests-final.log |
| Full real-music device run | PASS | live-03/result.json and logs/emotiscope.raw.log |
| Modes 18, 11 and 32 | Changing CRC-valid 128-pixel frames, both halves lit, mirrored output, PCM96/history present, invalid=0 | live-03/artifacts/emotiscope-test.json |
| Controls | Palette changes affect actual output; forbidden palettes rejected without state change; desaturation and brightness output checks pass; mode-dependent controls reject invalid context | same |
| Reset and storage | Three explicit resets, each one ROM boot, saved image 3351 B / CRC62851093 returns | same |
| Stability and resources | No unexpected reset/fault; frame count progresses; no heap loss in final 60-second window | measurements.json |
| Standalone observation | PASS; original controls/mode restored | observe-final/result.json; observe-reviewed/result.json |
| Concurrent AEL access | Second real-port process refused before serial open, as intended | concurrent-refusal/result.json |

The successful full run contains 59 complete timing samples in each 60-second
passive window. Reset windows and intrusive frame dumps are kept separate.
Captain confirmed real music was playing at the Emotiscope. AEL did not play
synthetic audio, change calibration, touch Titan or erase saved storage.

## Resource and performance results

| Measurement | Before | After |
|---|---:|---:|
| Static RAM | 159252 B | 159252 B |
| Application flash | 1024974 B | 1024974 B |
| Firmware binary | 1025376 B | 1025376 B |
| PSRAM allocated | 0 B | 0 B |
| Additional ML model/tensor arena | 0 B | 0 B |
| Live median FPS, real music | 82 | 92 |
| Minimum reported FPS | 78 | 85 |
| Median frame average | 12148 µs | 10900 µs |
| Maximum reported frame time | 16937 µs | 16919 µs |
| Median audio active average | 5512 µs | 5616 µs |
| Maximum reported audio active time | 8242 µs | 8254 µs |

The final stability window began and ended with 18608 B free heap and a 7156 B
largest block. Live frames advanced from 1456 to 7160. Saved code and all seven
control values were preserved. Firmware SHA-256:
`a676991b476030938f6f867b242e964ddd9e4a66ebe770fba5fc092a0ab294ef`.

The two windows use changing real music, so differences are descriptive and
cannot establish a causal speed improvement. This bench does not sustain 120
FPS in the saved Live workload. The host integration adds no device scheduling,
interrupt, DMA, bus, timer, storage or allocation workload outside explicit
queries/controls; those queries are exercised in the physical run. No claim is
made about radio coexistence, unexposed stack high-water marks or waveform timing.

## Failures observed and repaired

1. First fresh flash attempt stopped because the selected Python lacked pytest.
   Installed pinned pytest8.3.5; the full host gate then passed. No flash occurred
   in the failed attempt. Both logs retained.
2. Another workstream migrated source/deployment ownership while this task ran.
   live-01 rejected mixed-source evidence before control writes. Reconciled the
   explicit new owner and switched to its guarded scripts; never relaxed USB or
   firmware identity checks.
3. live-02 received a truncated native status line. It failed and restored the
   original controls. Added bounded retries only for incomplete read-only
   snapshots. Planted tests verify genuine invalid-input faults are not retried.
   live-03 then passed all modes and resets. Raw failed replies remain preserved.

## Genuine limitations

- The existing no-PSRAM board still emits the SDK's absent-PSRAM probe errors.
  Source diagnosis is in AUTHORITY.md. Every boot's original AEL diagnostic
  result remains FAIL with its errors intact; functional readiness is a separate
  check allowing only these known errors. This is characterised, not fixed.
- Post-current-limit frame dumps prove device-generated output bytes. They do
  not prove emitted light, LED wire timing or optical quality. No analyser or
  camera result is claimed.
- Serial status can truncate under load. Bounded read-only recovery is verified;
  the firmware transport itself was not changed. Unrecoverable truncation fails.
- Validation is bounded functional/stability testing. The current lane's
  90-minute endurance HOLD remains intact; long-term qualification is not claimed.
- Workflow bind and verify refused this project as outside configured workspace
  roots. Actual commands ran directly with preserved evidence. Registry tasks
  retain their original unadmitted governance state alongside explicit domain
  dispositions. No workflow acceptance certificate is claimed. The diagnostic
  advisory call succeeded (738 input / 130 output tokens); it did not grant
  operation authority or test acceptance.
- No AEL model/inference pipeline exists to validate. The host AI workflow and
  existing Emotiscope DSP/renderer are the capabilities actually integrated.

## Reproduce and recover

[Exact setup/build/test/flash/monitor commands](../../docs/emotiscope-bench.md).
[Reusable bench skill](../../docs/skills/emotiscope_guarded_bench.md).
[Original recovery procedure](../emotiscope-baseline-2026-10-03/README.md).
The private full-flash image remains unchanged and excluded from Git. Normal
current-lane reflashing is the first recovery route; restoring the original full
image also restores the original firmware/configuration and must be followed by
identity and saved-program verification. No irreversible settings were changed.

`SHA256.json` records the committed evidence files. This closeout, the pack,
configuration, tests and raw observations are the deliverables; generated build
objects remain in ignored scratch directories.
