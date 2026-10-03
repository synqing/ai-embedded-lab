# PRISM lane bench: source identity before target claims

Use with [prism-lanes.md](../prism-lanes.md). This is the closeout capture for the [3 October lane run](../../reports/lanes-2026-10-03/README.md).

1. Inspect the named lane's tracked source and build files. A vendored portable VM and a chip name do not make firmware. Record scaffold and donor separately; do not import donor code across provenance boundaries to make a green row.
2. Verify the dependency against its pinned Git commit, then run host checks in a disposable copy. Read-only vendors must not acquire npm or generated files. Serialise old core tests using their shared temporary path.
3. Build into a fresh directory with the lane's native builder. Record the commit, dirty patch and source hashes, including untracked headers. Timeout cleanup must terminate compiler descendants as well as their launcher.
4. Identify actual USB devices. The Emotiscope S3 is not a substitute for an RT1062, RA8P1 or a two-device link. A missing second MCU leaves link validation untested even if both binaries compile.
5. Reuse an existing hardware owner. Check device-topic timestamps, not just a recently written host file or advancing display sequence. In this run, a broker kept publishing three-hour-old counters after `Errno 6` while the USB node had reappeared; restarting its existing launchd service restored communication without a board reset.
6. Before recovery, match the exact owner script, evidence argument, service PID, device UID and image/schema. Refuse suffix lookalikes and the wrong owner. Recovery is an explicit single operation, never an automatic flash retry.
7. Measure each counter against its own device-topic timestamps. Asynchronous cached topics measured against host publication time distorted the first short-window rate. Retain raw observations and distinguish counter progress, electrical output and optical appearance.
8. Regress the standard lane with its existing pack, restore controls and saved programme, and retain the recovery image. Capture both positive and planted-negative tests before committing.

Do not mistake `accepted=false` in an old broker checkpoint scheme for unidentified hardware; independently compare the observed UID/build/schema with source-bound build evidence. Conversely, never convert that independent read-only match into programming/control permission. This run made no firmware admission changes.

For PRISM-owned locked baselines, use the same adapter's `bench-build` and
`regression` actions. Verify that the recorded lane entry point executed, that
its receipt identifies the operation and retains `BENCH_ONLY`, and that emitted
firmware hashes match. Preserve a failed or missing receipt as failure even
when a command exits zero. Keep `build`/`flash` refusal until clean product
source and deployment profiles have separately been admitted. `diagnose` only
reports capabilities and the remaining path; it never opens the serial device.
