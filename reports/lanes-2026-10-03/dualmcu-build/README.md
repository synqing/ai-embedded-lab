# DualMCU donor build evidence — 3 October 2026

Fresh donor target builds and four native bridge tests completed successfully. The donor working source stayed unchanged. These are donor results, not implemented PRISM DualMCU firmware.

## Source identity

- Donor: `21de29be3fff18244a4da7a81b21e13f35bb2694`
- Dirty source: `21de29be3fff18244a4da7a81b21e13f35bb2694-dirty-cb8c7e5a862e436a`
- Diff SHA-256: `f306bc6c0ec01e5bc058f252b89d8f542da752601b0afd96d0a426db48880f19`
- Unchanged before/after: `true` (Git status, commit, source identifier and binary diff hash).
- Modified donor files were preserved: `firmware/rt1062/ws2812_dma_driver.cpp` and `docs/evidence/ws2812-128-bringup-2026-09-21/RECOVERY_AND_DMA.md`.

## Executed checks

| Check | Exit | Seconds | Evidence |
|---|---:|---:|---|
| native_bridge_tests | 0 | 4.193 | [native_bridge_tests.json](native_bridge_tests.json), [log](native_bridge_tests.log) |
| rt1062_production | 0 | 28.7 | [rt1062_production.json](rt1062_production.json), [log](rt1062_production.log) |
| s3_radio_bridge_ble | 0 | 34.122 | [s3_radio_bridge_ble.json](s3_radio_bridge_ble.json), [log](s3_radio_bridge_ble.log) |

Native environments: `native_bridge_protocol`, `native_bridge_transport`, `native_s3_radio_core`, `native_ble_dualmcu_host`. The donor G++ runner compiled and executed them; this is not a PlatformIO host run. A second execution with `--keep` retained their binaries for hashing ([receipt](native-retained.json), [log](native-retained.log)). Host compiler: Apple clang 17.0.0, arm64-apple-darwin25.1.0.

All PlatformIO build, workspace, library dependency and cache directories were fresh external scratch paths. Exact commands, environment variables, logs and hashes are in [summary.json](summary.json).

## Target binaries

| Target | File | SHA-256 |
|---|---|---|
| rt1062_production | `firmware.elf` | `5f21a4d59b0f944eb13d25be1605bbd70698f0e4757c1da514e8f9194b82664b` |
| rt1062_production | `firmware.hex` | `d345e6182f44a2d3c612991f7f99ab9365ccdf9fd0029598486f15cd15387f0f` |
| s3_radio_bridge_ble | `firmware.bin` | `1dbcfee73f67facb2ad998770f18c4de68867a945f7a596aca10d5fb8cf9e906` |
| s3_radio_bridge_ble | `firmware.elf` | `bb828c0e7476d1c6dddda4ac7ca68116ac106bf1cba1e5c73657f7e5d19e714a` |
| s3_radio_bridge_ble | `firmware.map` | `80cb9fabbdba7dcd4fa4663576a94a1d51eef2cb875e685fc500f2d503fb8d1d` |

## Applicability and remaining path

The RT1062 environment builds for Teensy 4.1, whereas the existing donor bench environment is `rt1062_k1_migration_t40_ws2812_128` (Teensy 4.0). The S3 BLE build contains SPI bridging, MIDI decoding, replicated state and diagnostic display/touch support. Neither build proves current device behaviour.

PRISM K1-DualMCU remains a greenfield lane with the pinned shared pattern engine and no chip-specific firmware/build composition. Donor source remains a reference; copying it requires the lane provenance review.

1. AEL may expose these donor recipes as externally referenced build/host checks, with explicit donor identity.
2. PRISM target implementation and target-specific build environments must exist before claiming PRISM firmware build support.
3. Any later device validation must independently establish target identity and firmware applicability before execution.

Governance `workflow_verify` and its installed CLI equivalent both rejected the AEL project as outside their configured workspace. These commands were therefore executed directly under the existing assignment authority; no governance admission is claimed.

No hardware was opened, enumerated, flashed or measured. No donor source was edited.
