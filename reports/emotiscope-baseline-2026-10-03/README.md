# Emotiscope AEL execution checkpoint — 3 October 2026

Status: **INCOMPLETE — required Deep Research report and checklist not supplied or located.**
This is discovery and baseline evidence, not an implementation-completion claim.
No AEL-derived firmware capability has been selected, implemented or flashed.

## Verified target and source

- Requested device: `/dev/tty.usbmodem12201`; callout interface `/dev/cu.usbmodem12201`.
- Live USB: VID/PID `303A:1001`, serial `DC:54:75:EA:36:14`.
- Live `:build`: version `40103`, Git `45470057`, epoch `1790965821`, environment `k1_emotiscope_live`.
- Actual source: `/Users/spectrasynq/SpectraSynq_K1_Firmware`, branch `wip/emotiscope-perf`, HEAD `b05cbd2c`.
- `git diff --exit-code 45470057 HEAD -- SPECTRASYNQ_K1_FIRMWARE platformio.ini` exits 0. The current firmware/configuration matches the installed revision; this is not a fresh build.
- Existing `/Users/spectrasynq/Workspace_Management/Software/Emotiscope.HIL` is the older reference tree, HEAD `7f86939bd7c16c4a6dd5789813e9d551246ed134`, with unrelated dirty files preserved. Its Arduino CLI instructions do not apply to the currently installed K1 firmware.
- Current control authority: `SpectraSynq_K1_Firmware/docs/handover/2026-10-03-emotiscope-controls.md`. Preserve existing PRISM Studio controls and saved program.
- AEL upstream pinned to `a95dd2639019c6366c92d2bdb78561a9f89855eb`, origin `https://github.com/EZ32Inc/ai-embedded-lab.git`.

## Actual operations and results

| Operation | Result | Evidence |
|---|---|---|
| USB discovery and existing source inspection | Device matches Emotiscope documentation | `usb-identity.json` |
| 12-second serial observation, 115200 baud | 8,580 bytes; a USB UART reset occurred; application returned to saved program | `serial-passive.bin` |
| Read-only identity and control commands | Current build and saved program identified | `runtime-readback.json`, `runtime-readback.log` |
| AEL host baseline | 14 tests passed | `ael-host-tests.log`, `command-results.json` |
| AEL evaluation of physical serial capture | FAIL: PSRAM boot error; no fatal crash or reboot loop detected under one ROM marker per boot | `ael-baseline-evaluation.json` |
| Firmware repository bootstrap | FAIL: active branch metadata says `lane/chromatic-score`, checkout is `wip/emotiscope-perf` | `firmware-source-gate.json` |
| Fresh firmware compile / flash / regression | NOT RUN | Missing research input; source-lane metadata requires reconciliation before firmware work |

The initial serial open used DTR=false/RTS=false; a `USB_UART_CHIP_RESET` occurred in that capture. Subsequent identity/control reads used the current source guard's DTR=true/RTS=false convention. Native controls do not persist across resets in this firmware; the observed post-reset renderer is Live. The pre-reset native mode was not recorded. No original transient mode is claimed restored.

The boot log reports `quad_psram: PSRAM ID read error` and `psramAddToHeap(): PSRAM not initialized!`, followed by successful system initialisation and `KLV boot=saved`. No PSRAM fix or timing qualification is claimed.

## Baseline resources and state

Measured on the device before backup: 128 pixels; saved program 3,351 bytes, CRC `62851093`; renderer Live, mode 0; free heap 18,476 bytes, largest free block 7,156 bytes. One sample is not minimum headroom or an endurance result.

Read settings: palette 43, position 0, brightness 600, saturation 1000, mirror 1, speed 1000, contrast 1000. These were queried, not changed. The serial capture contains observed timing lines; no controlled audio workload or timing distribution has been qualified in this session.

Historical build evidence, explicitly **not a new build**: `_scratch/emo-controls-20261003/firmware/flash-index-fix.log` in the firmware repository records static RAM 159,252 / 327,680 bytes and application flash 1,024,974 / 3,342,336 bytes. Pioarduino platform 54.03.20, Arduino framework 3.2.0, framework libraries 5.4.0+sha.2f7dcd862a, Xtensa compiler 14.2.0+20241119. Board default labels showing 16 MB do not override the 8 MB target configuration or ROM-detected flash.

## Reproduce completed host checks

From `/Users/spectrasynq/ai-embedded-lab`:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m unittest   tests.test_evidence_contract tests.test_runner_retry_policy   tests.test_observe_uart_download_mode_wrapper tests.test_control_reset_serial
```

The exact commands and exit codes are recorded in `command-results.json`. Read-only firmware identity, only after confirming the USB serial and exclusive port ownership:

```sh
/Users/spectrasynq/.platformio/penv/bin/python   /Users/spectrasynq/SpectraSynq_K1_Firmware/scripts/regression-harness/k1_device_identity_guard.py   --port /dev/cu.usbmodem12201 --expect-env k1_emotiscope_live   --expect-git 45470057 --expect-epoch 1790965821
```

## Open dependencies and next execution steps

1. Obtain the completed Deep Research report/checklist. No exhaustive checklist disposition or ML adoption decision can be made without it; do not invent its recommendations.
2. Reconcile the firmware repository's stale lane metadata with this authorised Emotiscope assignment, preserving all historical plans and unrelated dirty files. Build and regression-test the exact baseline.
3. Map each actual research item to current source, implement applicable items, build/flash through the device identity guard, measure and regression-test the physical hardware. Preserve current saved code and controls.
4. Finish with logical implementation commits, reproduction commands, measured resource deltas, all checklist dispositions and the required reusable test-pack skill closeout when a pack exists.

## Tooling limitations encountered

- Agent launch was rejected by the automatic wave guard: `UNINSPECTABLE_BRIEF`; no worker launched. Discovery continued directly; no guard bypass.
- Governance context and suggestion ran using native session `be47f8dffe6aab2ea822f47d`; provider advice was disabled. No task registry was present for this assignment and none was fabricated.
- `workflow_verify` refused the actual AEL project: `Verification project outside configured workspace`. Tests then ran directly with preserved raw outputs. No workflow acceptance claimed.
- Workflow evidence/diagnosis calls returned input errors (`invalid_reference` and `no_permitted_options`); no semantic verdict is treated as evidence.
- The required `docs/agent/AGENT_EXECUTION_STANDARD.md` is absent in AEL; the actual firmware repository's execution standard was read.
- No `.claude/harness/init.sh` exists in AEL or the current firmware repository.

## Civilization Engine usage audit

Queried: `CivilizationEngine.is_available()`, `get_context("emotiscope", "baseline")`, and AEL `golden-reference --target esp32s3 --instrument usb`. Engine unavailable; context empty; no exact golden reference. Reused the actual existing Emotiscope identity protocol and flash/recovery evidence, not a different board's GPIO test. No new experience/pattern record or test pack was created. No new dependencies, model, subscription or global skill was installed.

## Recovery image and application return

Full 8 MB flash read completed with esptool 4.9.0, exit 0, in 104.05 seconds.
Local private backup: `/Users/spectrasynq/ai-embedded-lab/_scratch/emotiscope-baseline/flash-backup.bin` (mode 0600, excluded from Git because it contains device configuration).
SHA-256: `beab0249db4fc98df4fcf593f5a9001790627ceaafcbe195274b0f020e8f335d`.

`flash-image-comparison.json` compares flash readback against the existing deployment binaries in `SpectraSynq_K1_Firmware/.worktrees/emo-controls-20261003/.pio/build/k1_emotiscope_live`: bootloader at 0x0 (20,208 bytes), partitions at 0x8000 (3,072 bytes), application at 0x10000 (1,025,376 bytes). All three match byte-for-byte. This validates readback against independently existing binary artefacts; it is not a newly reproduced build. No new worktree was created or modified.

The first silent buffered read was interrupted with SIGINT before it produced a backup (exit -2). It was not a demonstrated device failure. The second read used unbuffered progress and a 240-second operational timeout; it completed and reset the device normally. No flash write or erase command ran.

`post-backup.log` and `post-backup.json` confirm the original identity, VM up, saved image CRC `62851093`, palette 43 and brightness 600 after the backup/reset. This proves application return and state readback, not optical output, acoustic responsiveness, sustained timing or complete regression coverage.

Restoration command, only after matching the USB serial and backup SHA-256 and releasing all port owners:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m esptool \
  --chip esp32s3 --port /dev/cu.usbmodem12201 --baud 921600 \
  write_flash 0 /Users/spectrasynq/ai-embedded-lab/_scratch/emotiscope-baseline/flash-backup.bin
```

Then rerun the identity check above and query `:klv_status`. Restoration was **not performed** because the original flash contents were never changed. Keep the private backup alongside the repository until implementation is complete; it is not included in a Git clone.
