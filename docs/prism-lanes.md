# PRISM lane automation

This extends the existing AEL runner, adapter registry, evidence writer and zero-retry policy. It does not install a second test framework. Results distinguish the named PRISM scaffold from externally referenced donor firmware. See the [validated three-lane report](../reports/lanes-2026-10-03/README.md) and [reusable procedure](skills/prism_lane_bench.md).

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

Native `build`, `flash` and `recover` for the PRISM scaffolds fail closed: neither contains a board application, startup configuration or deployable target. DualMCU `observe` also refuses the single S3 Emotiscope as a substitute for both chips. These refusals are tested. A donor build is never automatically flashed, and hardware side effects are never retried by AEL.

For Titan image recovery, preserve the existing donor's `scripts/programme_rfp_swd.py`, E2 Lite identity and current image-bound admission procedure; this run validates owner recovery only. For standard image recovery, use the preserved [original recovery procedure](../reports/emotiscope-baseline-2026-10-03/README.md). Never write a Titan/Teensy image to `/dev/tty.usbmodem12201`.
