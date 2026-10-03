# AEL → Emotiscope implementation matrix

Authoritative derived checklist following Captain’s 3 October continuation. The separate Deep Research report is not required. Original checkpoint is preserved without rewriting historical evidence. Full file denominator and hashes: `component-inventory.json`. Decisions concern this physical target and current application, not the general merit of upstream tools.

## AEL-01 — Deterministic runner, retry budgets and result contracts

Disposition: **ADOPT**. Execution: **PASS**.

Evidence / reasoning: Run guarded build/flash/physical checks in declared order. Disable automatic side-effect retries.

Acceptance / evaluation: Runner returns failure for planted identity, CRC and timeout faults; live pack passes.

Source coverage: 4 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-02 — Evidence and run artefacts

Disposition: **ADOPT**. Execution: **PASS**.

Evidence / reasoning: Use existing evidence schema and JSON pack loading; preserve raw output, hashes and source identity.

Acceptance / evaluation: Every physical check references a raw log and typed facts; no absent data passes.

Source coverage: 3 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-03 — UART observation and boot diagnostics

Disposition: **ADAPT**. Execution: **PASS**.

Evidence / reasoning: Use AEL evaluator with Emotiscope serial line settings and one ROM marker per boot. Keep pre-existing PSRAM errors visible.

Acceptance / evaluation: Repeated boot/readback, saved-program preservation and crash detection on the identified device.

Source coverage: 5 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-04 — Build and flash integration

Disposition: **REPLACE**. Execution: **PASS**.

Evidence / reasoning: Existing IDF/CMake/STM32/Zephyr adapters do not build this Arduino/PlatformIO application. Add narrow adapter calling the existing verified-flash script.

Acceptance / evaluation: Clean source build, host gate, guarded flash, correct post-flash source identity and return to saved program.

Source coverage: 13 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-05 — Target configuration, serial ownership and reset

Disposition: **REPLACE**. Execution: **PASS**.

Evidence / reasoning: Thread locks cannot exclude other processes. Bind exact USB VID/PID/serial and source env; hold an OS file lock, check port owners, use supported S3 USB reset.

Acceptance / evaluation: Wrong device and concurrent owner are refused before writes; repeated physical reset returns saved program.

Source coverage: 4 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-06 — Physical checks and failure attribution

Disposition: **ADAPT**. Execution: **PASS**.

Evidence / reasoning: Mailbox/edge-count checks cannot prove music visualisation. Use existing Emotiscope command protocol and independent frame CRC decoder; measure telemetry and save-state preservation.

Acceptance / evaluation: Live/native control tests, valid changing LED buffers, rejection paths, bounded soak, source-matched timing/resource evidence.

Source coverage: 4 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-07 — Generic orchestration, natural language planner, auto-repair and nightly jobs

Disposition: **REJECT**. Execution: **REJECTED**.

Evidence / reasoning: Planner is rule-based, noop fallback exists, repair modules are placeholders. Existing orchestrator owns diagnosis; autonomous background flashing/git writes add risk without product capability.

Acceptance / evaluation: Source review: planner._noop_runplan and placeholder repair functions; no unattended service adopted.

Source coverage: 20 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-08 — External instruments, GDB, mailbox, meters, FPGA and logic analyser

Disposition: **NOT APPLICABLE**. Execution: **NOT APPLICABLE**.

Evidence / reasoning: Designated setup is native USB Emotiscope with no connected instrument/wiring authority. Software frame evidence cannot substitute electrical measurements.

Acceptance / evaluation: Inventory confirms native USB target. Unrelated Titan is excluded.

Source coverage: 78 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-09 — Firmware templates, peripheral demos and PCNT loopback

Disposition: **REJECT**. Execution: **REJECTED**.

Evidence / reasoning: Demo firmware replaces functioning product and assumes different pins/wiring. Existing microphone/DMA/LED application is the useful regression workload.

Acceptance / evaluation: Source shows PCNT requires jumper and target-specific pin pairs; no functional product increment from transplant.

Source coverage: 3613 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-10 — Embedded web UI browser pattern

Disposition: **NOT APPLICABLE**. Execution: **NOT APPLICABLE**.

Evidence / reasoning: Current device uses USB PRISM Surface and has no embedded HTTP control UI. Preserve existing studio, no duplicate dashboard/browser dependency.

Acceptance / evaluation: Current source handover and browser_automation.py HTTP/browser assumptions.

Source coverage: 3 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-11 — Civilization Engine, cloud APIs, notifications, remote queues

Disposition: **REJECT**. Execution: **REJECTED**.

Evidence / reasoning: Optional external knowledge/service integrations are not needed for deterministic local bench proof; CE is unavailable in accepted baseline.

Acceptance / evaluation: Local tests and source evidence suffice; no new server or outgoing messages.

Source coverage: 11 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-12 — Generic discovery, connection planning and alternate-board pack catalogues

Disposition: **REJECT**. Execution: **REJECTED**.

Evidence / reasoning: Retain upstream utilities unchanged. Existing USB identity manifest/source registry already provide exact target authority; no broad new configuration graph or example pins. Narrow Emotiscope pack uses runner directly.

Acceptance / evaluation: Specific selected functionality is AEL-01..06; remaining generic catalogues would duplicate established product infrastructure.

Source coverage: 290 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## AEL-13 — ML model assets, embedded inference and tensor preprocessing

Disposition: **NOT APPLICABLE**. Execution: **NOT APPLICABLE**.

Evidence / reasoning: No model binaries, inference engine, training pipeline or tensor preprocessing exists in this pinned source; AI refers to host agent workflow. Do not invent a model integration.

Acceptance / evaluation: Tracked filename and source import scan recorded in component-inventory.json; model.py files describe DUT/instrument metadata.

Source coverage: 0 files; paths in inventory. Host-side integration adds no device model, tensor arena, tasks, interrupts or DMA. Dependencies remain the existing Python/pyserial and firmware PlatformIO stack.

## Final execution evidence

All six selected components passed the integrated physical run `live-05/result.json`; `lane-build/result.json` and `lane-flash/result.json` cover the actual native runner build/deployment paths. `integration-host-tests-reconcile.log` covers 25 host tests with planted faults. `concurrent-refusal/result.json` is an expected physical-port ownership refusal while `observe-final` owns the device. Earlier failures remain in live-01 and live-02. Full paths and resource impact are in matrix.json.

PASS here means the declared bench capability passed its tests. It does not relabel the known upstream PSRAM diagnostic FAIL, promise uninterrupted output through reset, certify optical/wire performance, qualify the greenfield K1 product, or assert a governance admission. No embedded ML item was invented.
