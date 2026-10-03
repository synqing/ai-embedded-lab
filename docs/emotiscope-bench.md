# Emotiscope AEL bench integration

This pack applies AEL's deterministic runner, evidence schema and UART analysis
to the existing Emotiscope application. It adds host engineering capability;
there is no embedded ML model or inference library in the evaluated AEL source.
The physical target is USB 303A:1001, serial DC:54:75:EA:36:14, chip 1436EA00.
The requested tty path and macOS cu path identify the same device.

## Source and setup

Use the existing AEL checkout and the existing PRISM K1-S3 lane. The old
`SpectraSynq_K1_Firmware` Emotiscope entry point was retired during this work.
Do not create another development tree on this workstation.

On a different workstation, obtain AEL with this implementation's commits and
K1-S3 from `https://github.com/synqing/K1-S3.git` at
`181cb92a4e660eaeae281ad3c081cf1b420f81f3`. The latter includes the checked,
immutable bench dependency and PRISM-Core v0.3.0 export, so it does not need the
legacy donor checkout. Use Python 3.11+, Node/npm and a C++ compiler. On macOS,
Command Line Tools provide the compiler and `lsof` is preinstalled.

From the AEL root:

```sh
python3.11 -m venv _scratch/emotiscope-venv
source _scratch/emotiscope-venv/bin/activate
python -m pip install -r requirements-emotiscope.txt
export EMO_SOURCE=/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-S3
python "$EMO_SOURCE/scripts/bench.py" verify
python -m unittest tests.test_emotiscope tests.test_evidence_contract tests.test_runner_retry_policy tests.test_observe_uart_download_mode_wrapper tests.test_control_reset_serial
```

The actual run used `/Users/spectrasynq/.platformio/penv/bin/python` and its `pio`
on PATH. PlatformIO fetches the firmware's pinned pioarduino 54.03.20 platform,
Arduino 3.2.0, ESP-IDF library bundle 5.4.0+sha.2f7dcd862a, Xtensa compiler
14.2.0+20241119, FastLED 3.10.3, FixedPoints 1.1.2 and M5ROTATE8 0.4.1.
These are firmware dependencies already selected by K1-S3, not imported from AEL.

## Build, flash, monitor and exercise

Each output directory must be new. The CLI refuses to overwrite previous runs.
Close other serial controllers before accessing the bench.

```sh
export EMO_REV=$(git -C "$EMO_SOURCE" rev-parse HEAD)
python -m ael.emotiscope --source "$EMO_SOURCE" --action build --out _scratch/emo-build-001
python -m ael.emotiscope --source "$EMO_SOURCE" --action flash --out _scratch/emo-flash-001
python -m ael.emotiscope --source "$EMO_SOURCE" --expect-git "$EMO_REV" --action observe --seconds 60 --out _scratch/emo-observe-001
python -m ael.emotiscope --source "$EMO_SOURCE" --expect-git "$EMO_REV" --action test --seconds 60 --resets 3 --real-music-confirmed --out _scratch/emo-test-001
```

After flashing another source revision, set `--expect-git` to the committed
revision printed by that successful guarded flash. Without this argument,
monitor/test uses the lane's deployment record. A build is not deployment;
a documentation-only source change does not itself update the running identity.
The expected revision must exist and its runtime/build inputs must match HEAD.
Do not change expected identity merely to make a mismatch disappear.

`--real-music-confirmed` records an operator-confirmed physical input condition;
it does not start playback. Use actual audible music at the Emotiscope. The test
refuses this mode without that condition. No calibration or generated audio is
used. No 90-minute endurance qualification is performed.

The test records a passive Live timing window, exercises three native modes,
palettes, desaturation, brightness and forbidden-control paths, performs explicit
resets, verifies saved-program return, then collects another passive window.
It always attempts to restore the starting controls and mode and verifies the
readback. Frame snapshots temporarily pause rendering; they are excluded from
the passive cadence windows. Observe mode also temporarily selects Live for the
standardised window and restores the initial mode/controls.

For the normal human control surface, keep using K1-S3's existing PRISM Surface:
`python "$EMO_SOURCE/scripts/serve.py"` and its documented local URL. AEL does
not replace it or add another dashboard. Release the AEL serial connection first.

## Evidence and failure meaning

`result.json` is the AEL runner result; `artifacts/emotiscope-*.json` is the
adapter evidence; `logs/` contains raw serial/build/flash outputs. Facts contain
source identity, decoder hash, commands and replies, saved image, heap readings,
frame pixels/CRC and timing summaries. Exit 1 means failure. Missing samples,
incomplete frame CRCs, wrong firmware, faults or failed state restoration cannot
pass. Incomplete read-only native status replies get at most three attempts;
nonzero invalid-input counters fail immediately. Builds/flashes do not retry.

The OS lock coordinates AEL processes across tty/cu aliases; `lsof` additionally
refuses an existing external port owner. It cannot compel unrelated programs to
honour the lock. Identity is checked on every operation; concurrent reflashing
is a real boundary, not a reason to accept mixed-source evidence.

Existing PSRAM startup diagnostics remain visible as an upstream UART evaluation
FAIL. The bench acceptance separately requires exactly one boot, saved-program
readiness, no crash and only the two characterised absent-PSRAM probe errors.
Any other error fails. No errors are deleted or changed to a diagnostic PASS.
See the report for why removing BOARD_HAS_PSRAM would not fix this SDK path.

## Scope, provenance and recovery

New integration code is `ael/adapters/emotiscope.py`, `ael/emotiscope.py`, the
pack and its tests. Existing AEL runner/evidence/observer modules are reused in
place at upstream `a95dd2639019c6366c92d2bdb78561a9f89855eb`; no AEL firmware is
copied into K1-S3. No root licence file was present at that upstream pin; no new
licence grant is inferred. Existing upstream notices remain untouched. The
K1-S3 capsule retains its GPL-lineage LICENSE/NOTICE and separate bench-only
classification; PRISM-Core retains its own pinned provenance.

Detailed component decisions and measurements:
[implementation report](../reports/emotiscope-integration-2026-10-03/README.md).
Original 8 MB recovery image and restoration instructions:
[preserved checkpoint](../reports/emotiscope-baseline-2026-10-03/README.md).
That private image is deliberately excluded from Git and remains required for
byte-for-byte restoration of the original configuration. Ordinary current-lane
firmware upload preserves the saved program and does not require full erase.
