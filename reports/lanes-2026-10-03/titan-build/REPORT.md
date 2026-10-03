# Titan existing donor fresh build — 3 October 2026

THE TITAN MUST ALWAYS BE VISUALISING MUSIC. This work performed no hardware, serial, probe, broker, playback or flash operation.

The existing Emotiscope-based Titan implementation builds successfully without source changes. This is the buildable donor for AEL integration, not the separate PRISM Kx-Titan scaffold and not evidence of a PRISM VM deployment.

## Reproduction and provenance

- Source: `/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001`.
- HEAD: `119ba2c498054fb0206e453cf38f6968222431c9`; tracked tree clean before and after. Unrelated untracked donor evidence was preserved.
- Existing candidate: `docs/emotiscope-port-001/evidence/arm-palette-003/receipt.json`, recorded 2026-10-01. All 194 fresh source hashes match that record and the current files.
- Original Emotiscope donor pin: `7f86939bd7c16c4a6dd5789813e9d551246ed134`; Titan BSP pin `6dd0a705d00ffbd6397c9a8c0199cbaa8eec41b7`.
- Fresh build ID: `becb0186f0a66fbb04b0e0f4a79c0480b8b963db0fe3f518a91af9bb2dd2b5c7`, identical to the existing candidate. Parent reported the same broker identity; this worker did not read live hardware or certify current residency.
- Compiler: Arm GNU Toolchain 13.3.Rel1, GCC 13.3.1. Scalar Armv8.1-M hard float, `-O2`, vectorisation disabled and data cache disabled, matching the recorded flags.

Exact command, from the source directory (output must not already exist):

```sh
python3 -B scripts/build_scalar.py --output /Users/spectrasynq/ai-embedded-lab/_scratch/lanes-titan-build/arm-palette-003-rebuild --optimisation o2 --dcache disabled --pdm-target --palette-runtime --palette-autostart --palette-morph --palette-ws2816-gpt-pair --dmac-priority fixed --dmac-lane-map led-first --emotiscope-port --tempo-field --live-runtime --live-emit --live-defaults docs/contracts/titan-emotiscope-spectrum-defaults-v1.json
```

Machine-consumable invocation: `build-command.json`. The builder writes only the supplied fresh output/stage directory. `python3 -B` avoids donor Python bytecode writes.

## Output and checks

Build directory: `/Users/spectrasynq/ai-embedded-lab/_scratch/lanes-titan-build/arm-palette-003-rebuild`.

| Artefact | SHA-256 |
| --- | --- |
| rtthread.elf | 7f4f3cff2e8d6bf92786139a7fb088073373b8100ab43d883804f7d56bb7cf4e |
| rtthread.hex | 72a6d73cc85aca1e4ed0563adf06f9be12d00e87ba1850c90d72d4019b760b7c |
| rtthread.map | 4d36c21d033298e64c157358df3999b53720b372d85f70d6539c602aa5600a2a |

Size: text 209,652 bytes; data 123,768 bytes; BSS 347,892 bytes. The build emits ELF and HEX, not a `.bin` file. Retained outputs include build.log, disassembly, symbols, ELF attributes, compiler macros, source-bound receipt and donor allocator-symbol check.

`python3 -B reports/lanes-2026-10-03/titan-build/verify_build.py` passed. It independently reads every source hash and every receipt-listed artefact hash, checks tracked cleanliness and HEAD, compares the old/fresh build ID and source dictionary, and isolates the binary difference. The first verification attempt exposed the receipt's `external/live_defaults.json` alias; the verifier now resolves that alias through the receipt's explicit defaults path.

The ELF differs from the recorded candidate by exactly six bytes, all in the compiler date/time strings (`17:08:33 Oct 1 2026` → `15:30:49 Oct 3 2026`). The link map is byte-identical. RT-Thread embeds these macros in `stage/rt-thread/src/kservice.c:256`. The HEX differs in the corresponding two records. Build ID equality therefore means matching identified source/configuration, not binary byte identity. `build-summary.json` records exact offsets and all output hashes.

## Implemented architecture

| Area | Current compiled implementation and source |
| --- | --- |
| Cortex-M85 | Owns audio and visual processing in the RT-Thread/FSP scalar shell. `platform/ra8p1/hal_entry.c:1`, `scripts/build_scalar.py:27`. |
| M33 | Not started by this image. `platform/ra8p1/hal_entry.c:256` explicitly excludes SecondaryCoreStart. |
| Ethos-U55 | Build receipt has `npu=false`; no NPU model supplied and no runtime initialisation on this configuration. BSP Ethos interrupt symbols remain linked; their presence does not establish inference use. `hal_entry.c:233` and `hal_entry.c:256`. |
| Audio capture | Onboard LMD2718 PDM adapter, data P502/clock P812, programme U14 rising edge DMA1 and measurement U13 falling edge DMA2. Nominal 40 kHz capture is measured-rate adapted to 12,800 Hz, 64-sample/5 ms hops. Exact settings are in the fresh receipt's `pdm_target_configuration`; acoustic and physical capture admission remain marked unproven/not run by this build. |
| Audio analysis | `LiveAudioRuntime::consume` calls `k1_emotiscope_push_pcm64`, using normalised PCM, not legacy K1 features (`platform/ra8p1/k1_live_runtime.cpp:183`). Emotiscope wrapper retains Goertzel, VU, tempo, novelty and visual state; `platform/ra8p1/emotiscope_port.cpp:178`, `:403`, `:426`. Contract `sr12800.hop64.bins64.emotiscope`, 64 spectrum bins and 96 tempo bins. |
| Visual output | `platform/ra8p1/palette_runtime.cpp:304` calls donor render; `:314` selects RGB8-expanded or RGB16 candidate output through the explicit nearest mapping (`emotiscope_output.h`). Native 128 pixels map to one continuous 160-pixel surface, split 80+80. Final packing applies hardware brightness once (`palette_runtime.cpp:529`). |
| LED transport | Paired WS2816 GRB48: P601/GPT6/DMA0 and P604/GPT8/DMA3, 80 pixels each. Receipt `pair_allocation` and `dmac_resolved` bind these resources. |
| Communications | Existing USB CDC identity/control/telemetry retained through `platform/ra8p1/hal_entry.c:181`, `:332`, `:350` and `fixture_app.cpp`. Donor Wi-Fi, web dashboard and continuous HIL export are excluded by the port assignment. |
| Autonomous start | Defaults emission on, brightness100, Spectrum mode1. USB enumeration has a bounded 500 ms startup interval; absent host cannot gate ongoing normal output (`hal_entry.c:267`). This is source/build evidence, not fresh optical proof. |
| PRISM VM | No PRISM VM/bytecode implementation found in compiled owner/source inspection or targeted `prism::`, `prism_vm`, `PrismVM`, `execute_bytecode` searches across platform/src/build script. Existing `prism_count` fields are a legacy visual effect parameter, not PRISM runtime evidence. |

## Capability reuse opportunities

The useful existing capability is USB CDC identity, schema, telemetry and accepted/rendered/emitted control receipts. An AEL profile can consume those through the established owner, avoiding a second transport or new firmware; the next decisive proof is a fresh owner-mediated read whose build/schema identity matches the profile, with no direct competing serial client.

The existing source-bound builder, map, disassembly and allocator check provide reusable host qualification machinery. Activation is the exact command above plus this file readback; cost is a fresh isolated output directory and the installed toolchain. The timestamp difference must remain explicit when comparing binaries.

M33/U55 are documented platform capabilities but parked in this donor. Using them would add partitioning, driver and timing validation work. This assignment does not establish an incremental product benefit or activation authority for either, and does not enable them.

## Constraints and remaining integration

Brightness instructions conflict across scopes: current global/skill text says24/255, while donor AGENTS begins with the newer 2026-09-29 explicit100/255 default override. Parent directed exact current-config reproduction and no hardware. The build therefore preserves recorded100/255 and emission-on; no policy or donor files were changed.

Governance `workflow_suggest` returned provider_disabled with spectrasynq-workflow mandatory; that procedure and canonical Titan platform memory were loaded. `workflow_verify` refused `Verification project outside configured workspace` for AEL. It was not bypassed or represented as accepted. Direct deterministic verification passed. No registry exists for this worker; `workflow_gate` returned no bound ledger and explicitly not a completion certificate. The parent owns registry/admission and AEL integration. AEL's referenced `docs/agent/AGENT_EXECUTION_STANDARD.md` was absent; supplied instructions and `docs/AI_USAGE_RULES.md` were read.

1. Bind the AEL profile to this donor build command, exact schema/contract and output paths; preserve the existing single serial owner.
2. Resolve AEL governance workspace admission through its supported configuration process if formal workflow acceptance is required.
3. When the parent is authorised to perform runtime verification, require fresh identity/telemetry evidence. No waveform, optical continuity, current hardware health, PRISM VM or deployment claim follows from this host build.
