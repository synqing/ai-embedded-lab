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
