---
name: emotiscope-guarded-bench
description: Use when running AEL validation against the Emotiscope USB bench, especially after source-owner changes, serial truncation or reset.
---

# Emotiscope guarded bench

Use the [bench instructions](../emotiscope-bench.md) and current K1-S3 deployment
record before touching the port. Historical source paths and USB port numbers
are clues; exact USB identity and a matching committed deployment are required.
The prior baseline and recovery evidence must survive every new run.

A complete pack closeout includes raw evidence, reproduction commands,
measurements, component dispositions and a skill capture. A passing build or
flash is not a physical function result.

## Reusable failure lessons

- Source ownership can change during a long task. AEL live-01 caught a different
  firmware identity and refused before controls. Read the new explicit owner
  handover and deployment record; never relax the identity check or reflash the
  retired checkout to recover an outdated expectation.
- Under real audio/rendering load, a native status line can be truncated. AEL
  live-02 failed rather than interpreting missing counters as zero. Retry only
  the read-only query, at most three times, retaining every reply. Complete
  invalid-input counters greater than zero fail immediately. Never retry an
  ambiguous flash or state-changing command merely because an ACK is absent. Reconcile a missing control ACK using the matching read-only query and require the exact intended state.
- Three intentional resets are not a reboot loop. Evaluate each reset window
  separately using one ROM marker, and reject unexpected boots in steady state.
- This no-PSRAM board uses a prebuilt SDK that probes absent quad PSRAM. Keep
  the original UART diagnostic FAIL. Only explicitly characterised probe errors
  and the missing optional show-state overlay may coexist with a separate functional boot pass; unknown errors still fail. Check both ESP-IDF and Arduino [E] severity formats.
- Output-buffer CRC/readback proves firmware output bytes, not light or wire
  timing. Frame capture pauses the renderer. Measure cadence in passive windows
  and do not claim 120 FPS or optical qualification from valid CRCs.
- Always restore controls and renderer in a finally block and verify readback,
  including after failed tests. Never overwrite the saved Live program to make
  the test easier. Use operator-confirmed real music, no automatic calibration.

## Tested failure boundaries

`tests.test_emotiscope` plants wrong identity, wrong firmware, changed saved CRC,
missing status, serial faults, port ownership, cross-process contention, torn
status, nonzero invalid counters, unexpected boot and unknown boot errors.
Tests must turn these cases red while known valid cases pass. The physical
reports record the actual failure/repair sequence; this skill does not imply a
separate subagent compliance experiment or global policy installation.
