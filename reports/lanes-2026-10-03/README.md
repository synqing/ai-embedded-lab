# Standard, DualMCU and Titan — execution closeout, 3 October 2026

Continued from AEL `35c4726` and standard Emotiscope `181cb92a`. The previous integration investigation and recovery capture were not repeated.

**The named PRISM DualMCU and Titan repositories are scaffolds, not alternate Emotiscope firmware configurations.** Both have a working pinned portable pattern engine but no native application, startup/linker configuration, device adapter or firmware build target. Separate donor repositories contain substantial implementations. This run fresh-built those donors, physically exercised the running Titan donor through AEL, repaired its stale host connection, and re-ran the full standard Emotiscope regression. No firmware source, dependency pin or installed firmware was changed.

## Three-lane status matrix

Cells distinguish PRISM lane results from donor results. **S:** [standard physical regression](standard-regression/artifacts/emotiscope-test.json) and [accepted build/flash/recovery evidence](../emotiscope-integration-2026-10-03/README.md). **D:** [DualMCU builds/tests](dualmcu-build/README.md), [AEL RT4.1 build](dualmcu-final-build/artifacts/prism-lane.json), [AEL RT4.0 build](dualmcu-t40-ael-build/artifacts/prism-lane.json), [AEL S3 build](dualmcu-s3-ael-build/artifacts/prism-lane.json). **T:** [Titan fresh build](titan-final-build/artifacts/prism-lane.json), [physical observation/recovery](titan-final-recovery/artifacts/prism-lane.json), [build/source comparison](titan-build/REPORT.md). **I:** [current repository inventories](source-authority.json) and [USB enumeration](discovery.txt).

| Capability | Standard | DualMCU | Titan |
|---|---|---|---|
| Source builds | PASS, accepted K1-S3 source build (S) | PRISM: no native target (I). Three donor targets freshly built (D); [pinned core host build PASS](dualmcu-core/result.json) | PRISM: no native target (I). Fresh donor ARM build PASS (T); [pinned core host build PASS](titan-core/result.json) |
| Deploys | Existing guarded flash already verified; unchanged this run (S) | Not tested: no connected RT1062/paired S3; PRISM flash unsupported (D,I) | Donor already resident; fresh source/config matches. No new flash performed. [PRISM flash correctly refused](titan-scaffold-refusal/result.json) |
| Boots | PASS, saved Live programme returned after reset (S) | Untested on hardware (I) | Existing donor application identified and running (T); fresh-image reboot not tested |
| Hardware exercised | PASS on `/dev/tty.usbmodem12201` (S) | [Refused single-S3 substitution](dualmcu-device-refusal/result.json); both MCUs/SPI untested | PASS for donor M85 audio, microphone and paired LED completion telemetry through separate Titan USB (T) |
| Automated AEL tests | Existing complete pack PASS (S) | Core/build profiles PASS; four native bridge/BLE tests PASS; wrong-hardware refusal tested (D) | Core/build/live/owner-recovery profiles PASS (T); stale/identity/fault negatives covered |
| Core Emotiscope regression | PASS: three waveform modes, controls, CRC buffers, saved programme, cadence and bounded memory checks (S) | Standard remained operational; donor physical parity untested (S,D) | Standard remained operational. Donor real audio/LED pipeline advances without new measured capture/LED faults in bounded window (S,T); not full cross-platform feature parity |
| Recovery verified | Original private 8 MB image and procedure preserved; reset return reverified. Full-image restore not repeated (S) | Not physically verified; missing paired hardware (I) | Host-owner restart verified, identity/control/output preserved (T). Firmware rollback not exercised |
| Remaining blockers | Existing diagnosed absent-PSRAM and optional show-state boot messages; unchanged (S) | RT1062 and paired radio S3/SPI interface missing; PRISM board firmware not implemented (D,I) | PRISM board firmware not implemented; donor timestamp nondeterminism; no optical/wire or fresh-image boot claim (T) |

## What each lane actually provides

**Standard — WORKING within the existing qualified bench scope.** K1-S3 owns the 128-pixel ESP32-S3 Emotiscope capsule, PRISM Live engine, three native waveform modes, controls, source-bound build/flash and saved-programme recovery. Current source HEAD is recorded in I; deployed identity remains `181cb92a`, independent of documentation-only HEAD changes. Core pin is v0.3.0. This is the only named PRISM lane with an implemented board/application build and deployment path.

**PRISM DualMCU — SCAFFOLD.** `1e71eeabfa4cb72fed68b7b6cbee74f40fa23778` has thirteen non-vendor files: documentation, licences, dependency lock and session scripts. Its forty pinned Core v0.2.0 files match `e9e6aebbc552186bffd53dbee3e14888b38e50b7`. No SPI server, hardware audio/LED driver, radio application or native build target lives in this lane.

**DualMCU donor — PARTIAL, current source builds; hardware unverified this run.** The reference tree `SpectraSynq-K1-DualMCU-Firmware@21de29be` implements RT1062 audio/visual/LED processing plus an S3 radio/control companion. `platformio.ini` defines `rt1062_production` (Teensy 4.1), `rt1062_k1_migration_t40_ws2812_128` (Teensy 4.0) and `s3_radio_bridge_ble`; all freshly built. `firmware/rt1062/main.cpp` starts `ProductionRuntime`; `firmware/s3_ble/main.cpp` starts SPI and BLE, services bridge traffic and exposes diagnostic display/touch support. `contract/bridge_protocol.h` and `bridge/bridge_transport.h` define CRC-checked commands/state/telemetry, 82-byte logical slots and 84-byte DMA transfers. Four native environments exercise protocol, transport, radio core and BLE replication. This is not an Emotiscope mode selectable on the single S3 board.

The donor has two existing modified files. Their exact patch and before/after identities are preserved in D. Builds did not overwrite either. No donor source was imported into the clean-room PRISM lane.

**PRISM Titan — SCAFFOLD.** `87d9fac` has the same v0.2.0 Core pin and no RA8P1 application/build. Portable VM availability does not establish a Titan VM installation.

**Titan donor — PARTIAL overall, running Emotiscope pipeline physically exercised.** The actual owner uses existing authorised worktree `titan-emotiscope-port-001@119ba2c`. Its matching build is `becb0186f0a66fbb04b0e0f4a79c0480b8b963db0fe3f518a91af9bb2dd2b5c7`, identified on UID `545433931bd25436593630352d068363`. The M85 runs RT-Thread/FSP scalar Emotiscope v1.1 audio/visual processing; the M33 is not started and U55 inference is disabled. Onboard PDM capture is measured-rate adapted to 12,800 Hz / 64-sample hops. Native 128-pixel output maps explicitly onto a continuous 160-pixel surface, split 80+80 over P601/GPT6/DMA0 and P604/GPT8/DMA3; microphone DMA1/2 remain separate. USB CDC supplies identity/control/telemetry. This donor has no PRISM bytecode VM integration. Exact compiled call-chain evidence is in T.

**What they buy:** DualMCU offers processor separation: radio/control work can move off the chip doing audio and LEDs, at the cost of a second board, SPI protocol and dual-image recovery. That isolation benefit is architectural, not a measured speed improvement here. Titan already runs an Emotiscope port with onboard PDM acquisition and paired 16-bit LED transport on an M85. Its M33/U55 capabilities are unused potential, not delivered acceleration. Neither scaffold currently adds functionality to the existing single-S3 Emotiscope.

## Physical failure, repair and measurements

The initial Titan owner was alive but stuck writing to an obsolete serial handle after USB re-enumeration. [Retained failure](titan-stale-tail.jsonl): `Errno 6 Device not configured`, device topic age over 11,000 seconds despite a fresh host publication. AEL never accepted this as current hardware. Restarting only `com.spectrasynq.titan-broker` reacquired the same UID/build. Firmware counters continued; no board reset or flash was required. The explicit guarded AEL `donor-recover` action reproduced this owner restart and checked controls/output after return.

Final bounded observation (T): **200.036 audio hops/s**, **100.020 completed LED frames/s**, microphone peak maximum **5,810**, **2,921** completed frames across **29.204 s** of palette-topic time. Frame CRCs changed. No new audio rearm/recovery/starvation/drop, LED error or pair fault appeared in the window. Historical audio `rearm_denied=8` remains visible; these short tests do not explain or clear earlier long-run events. Rates use each topic's own timestamp, not the asynchronously updated host publication clock. Brightness remained the resident value **100/255**, as required by the donor's later explicit default directive; this task did not write brightness or resolve unrelated historical global text by changing hardware.

Standard final regression (S): frame-rate median **103 before / 105 after**, audio-active median **5,078 / 5,075 µs**; free heap **18,608 → 18,476 bytes** across the post-reset window, largest block unchanged **7,156 bytes**, within the existing 256-byte acceptance bound. The earlier passive observation also measured the 18,476-byte floor. Saved programme remained **3,351 bytes, CRC `62851093`**. Input music changes over time; these figures are not an architecture performance comparison or proof of indefinite stability.

Fresh build resources:

| Image | Static/build measurement |
|---|---|
| Standard, unchanged | Accepted flash 1,024,974 bytes; static RAM 159,252 bytes. Delta from this host-only integration: zero |
| RT1062 Teensy 4.1 | Flash code 227,068 + data 68,552 + headers 8,504 bytes; RAM1 local-variable headroom 57,696 bytes; RAM2 free 509,024 bytes (D) |
| RT1062 Teensy 4.0 / WS2812-128 | Flash code 232,084 + data 70,600 + headers 8,608 bytes; RAM1 local-variable headroom 21,856 bytes; RAM2 free 459,840 bytes (D) |
| S3 BLE companion | RAM 101,984 bytes; flash 907,057 bytes (D) |
| Titan donor | Text 209,652; data 123,768; BSS 347,892 bytes. Scalar O2, hard-float, D-cache disabled; these are source/build facts, not peak-performance qualification (T) |

No inference/model footprint or acceleration claim is made. No portable firmware code was added, so host AEL automation has no device memory delta.

## Implementation, verification and reproducibility

New `ael/adapters/prism_lane.py`, `ael/prism.py` and `packs/prism_lanes.json` reuse AEL's runner/evidence/registry. They provide lane discovery, pinned-core host tests, fresh external donor builds, read-only Titan observation and explicit owner recovery. Native scaffold deployment fails closed. Recovery does not reflash, erase, change output or automatically retry hardware operations. `tests/test_prism_lane.py` covers stale/future/missing data, wrong UID/build/source/schema, wrong owner, frozen counters, faults, unsupported deployment, local input drift and timeout descendants, including a child ignoring SIGTERM.

The [final host suite](final-host-tests.log) passes **82 tests**, including existing runner/evidence/retry and standard Emotiscope boundaries. Independent review reproduced and corrected owner substring matching, untracked input omissions and incomplete process-group timeout cleanup. Intermediate [missing receipt alias](titan-observe/result.json) and [macOS `/tmp` path alias](titan-observe-02/result.json) failures are retained. Both failed before hardware mutation and were repaired by explicit path resolution. No failure was relabelled as a pass.

Exact setup/build/test/observe/recovery commands: [reproduction guide](../../docs/prism-lanes.md). Existing native scripts and dependency lockfiles remain authoritative. Generated binaries and dependency/staging directories remain ignored on this workstation; logs, source identities, dirty patch, hashes and JSON results are committed. Titan rebuilds differ from the installed HEX in compiler date/time records only in the independently compared first rebuild; the source manifest and map match. Bit-identical rebuilds remain a documented limitation, not falsely claimed.

The original [8 MB recovery image procedure](../emotiscope-baseline-2026-10-03/README.md) and `d4c3282` evidence remain untouched. No fuses, security state, device identity, configuration area or flash image changed. Core's unrelated untracked working files and both donor repositories' unrelated state were preserved.

Governance `workflow_bind`/`workflow_verify` refused the AEL repository as outside configured roots. Actual checks therefore ran directly under the user-authorised task; no formal governance acceptance certificate is claimed. Semantic-advice calls supplied no admissible new evidence. [TASKS.json](TASKS.json) preserves assignments and separately records execution dispositions. Reusable closeout: [PRISM lane bench](../../docs/skills/prism_lane_bench.md).

## Remaining path

1. Connect the actual RT1062/Teensy board and its intended S3 companion, with their established SPI/reset wiring and both programming/serial interfaces. This is the smallest external hardware action needed for a two-MCU boot/link/fault-recovery test. No such RT1062 interface appeared in USB inventory; the known Emotiscope S3 cannot supply the missing processor.
2. Implement the PRISM lanes' native board applications, startup/build configurations and control adapters before they can deploy the shared VM. The existing donor code is not silently adopted; provenance boundaries remain intact. This is unimplemented source work, not an external research dependency.
3. For stronger Titan qualification, use its existing image-bound programmer and recovery procedure for a fresh-image boot/rollback test, address timestamp reproducibility in the donor builder, and separately establish wire/optical and longer-run stability evidence. The present result is bounded live execution and owner recovery, not those unperformed tests.
