# Current execution authority

Captain’s latest handover removes the separate report blocker and authorises derivation, implementation, build, flash, reset and physical testing. It explicitly permits characterisation of the stale source-lane gate.

AEL starts at d4c3282 on feat/emotiscope-ael-integration. Upstream pin a95dd2639019c6366c92d2bdb78561a9f89855eb. Firmware is the existing /Users/spectrasynq/SpectraSynq_K1_Firmware, wip/emotiscope-perf, b05cbd2c; its firmware/configuration is unchanged from deployed 45470057. docs/handover/2026-10-03-emotiscope-controls.md is current device-specific authority. The spec-index active_branch still names lane/chromatic-score; its bootstrap FAIL is stale lane metadata, not a build test or a hardware verdict. It remains recorded, not relabelled PASS. This scoped assignment does not supersede the historical Chromatic Score plan.

Only USB 303A:1001, serial DC:54:75:EA:36:14, folded chip 1436EA00, environment k1_emotiscope_live is in scope. No Titan operations. Preserve saved image CRC 62851093 and 3351 bytes; all transient controls restored after tests. Existing firmware source dirtiness is confined to unrelated documentation/skills and must remain untouched.

Recovery remains ../emotiscope-baseline-2026-10-03/README.md and its private 8 MB image. Never change efuses/security state.

Execution dependency order: AEL-01/02 runner/evidence foundation → AEL-04 fresh build and guarded deployment → AEL-05 identity/ownership/reset → AEL-03 observation → AEL-06 physical controls, resources, stability and regressions. Each selected item retains the inspect → minimal design → implement → host test → compile → flash → boot → physical exercise → measurement → regression → diagnosis/repair loop. Ordinary failures are evidence and require repair, not completion. Wrong target, unavailable required physical input or unrecoverable hardware loss stops only dependent operations. Missing readings, skipped checks and generated outputs never count as acceptance.

Closeout requires source/commits, exact reproduction commands, actual before/after measurements, all matrix dispositions, regression results, limitations, recovery and reusable test-pack skill. No external report dependency remains.

## Fresh build and PSRAM diagnosis

The fresh build at b05cbd2c compiled every translation unit in a new build directory and reported static RAM 159252 bytes, application flash 1024974 bytes. The verified-flash script then passed its host gate, flashed the identified target and read back git=b05cbd2c, env=k1_emotiscope_live, epoch=1790997451. The first attempt stopped before any flash because the PlatformIO Python lacked pytest; installing pytest 8.3.5 repaired that dependency. Both attempts are retained.

Actual Arduino 3.2.0 core is framework-arduinoespressif32@src-6738aaddd9fb901216d5f60e093380b6. Its esp32-hal-misc.c lines 259–263 call psramInit at ESP_SYSTEM_INIT unconditionally under CONFIG_SPIRAM; lines 269–272 subsequently call psramAddToHeap. The selected precompiled qio_qspi SDK defines CONFIG_SPIRAM=1 and QUAD, IO30/26, rather than the earlier octal pins 33–37. There is no PSRAM on this target. Removing BOARD_HAS_PSRAM alone cannot disable this core path. This is a reproducible startup probe failure with no PSRAM allocated; it is not assumed fixed. Keep the exact errors in raw evidence and distinguish startup diagnostics from steady-state crashes. Rebuilding the SDK solely to remove a harmless absent-device probe is not required for the host-only AEL integration; additional boot or runtime errors remain failures.

Governance binding was attempted with the native session and actual registry. Server refused: Project outside configured workspace roots. Direct execution/evidence continues; no governance acceptance is claimed and global workspace trust is not changed.

## Live ownership handover discovered during execution

After the fresh legacy flash, another authorised workstream completed the ownership migration. Old repo commit 719af686 explicitly retires Emotiscope development there and directs builds/flash/controls to /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/K1-S3. Live USB reported 67442215 while the AEL test expected the legacy source; live-01 refused before any controls. No test result from mismatched firmware was accepted.

Read current K1-S3 AGENTS.md, README, bench/README, docs/provenance, deployment registry and scripts/bench.py/flash.py. Current source 181cb92a has only documentary changes from deployed 67442215. Its immutable GPL-lineage bench capsule contains selected b05cbd2c inputs, active overlay is lane-owned, and PRISM-Core is pinned v0.3.0. AEL now calls the lane's authoritative scripts, not the retired legacy entry point. No donor source is copied to product code.

The new lane build passed 85 inherited tests and generated firmware.bin (1025376 bytes). The AEL flash adapter ran the lane's host/build/identity/upload/readback sequence successfully: deployed git=181cb92a, epoch=1790997874, env=k1_emotiscope_live, same exact USB target. See lane-build and lane-flash. New source docs prohibit the 90-minute endurance run; this task uses bounded minute-scale functional/regression windows and does not run it.

Live-02 caught a torn read-only native status line under real music and restored all original controls/mode. The adapter now retries only incomplete read-only snapshots at most three times; a complete nonzero invalid count immediately fails. Host fault tests cover both paths. This is host robustness to existing serial truncation, not a firmware transport fix.

The lane remains separate from the AEL checkout. Firmware source inputs were not changed by this integration. The only firmware deployment differences are lane ownership/build identity; the AEL capabilities execute on the host.

## Optional show-state diagnostic and Arduino severity audit

The preserved baseline and live-03 both contain `[E][vfs_api.cpp:99] open(): /littlefs/SHOW_STATE_V1.BIN does not exist, no permits for creation`. In the lane's materialised source, control/k1_show_state.cpp:395–399 returns false on that missing optional read. persistence/bridge_fs.h:644–646 explicitly calls it a soft restore and missing/corrupt data a no-op; primary CONFIG remains authoritative. Saved Live code is separately loaded and its CRC is verified. This pre-existing absent overlay is characterised, not silently created or erased.

The generic AEL UART evaluator does not recognise every Arduino [E] line. The Emotiscope adapter now explicitly records those lines during boot, accepts only exact known diagnostic shapes and rejects other [E] lines during steady state. Original logs and old evaluation outputs remain immutable. Host tests plant an unrelated Arduino DMA error to prove rejection.
