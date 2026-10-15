# Replacement isolated observer — host increment, 16 October 2026

Titan must always visualise music. No device was accessed for this increment.
Normal autonomous output must survive fixture cancellation. Product HOLD remains.

## What runs

`ael.prism` now admits the explicit `titan-replacement` target using the existing
candidate source/object/toolchain receipt validator, isolated authority records,
single-owner transport and bounded recovery transaction. `prism_native` selects
replacement identity/status/bind, then the new collector. No old identity opcode,
old binding, old80-pixel profile or legacy completion operation is substituted.
The collector issues ARM, polls STATUS, drains four complete polarity streams
plus SOF records, retains raw replies before parsing, checks the post-drain
snapshot and cancels only fixture work. Failure never retries ARM.

**Firmware dependency remains open.** The inspected replacement advertises
`firmware_fixture:false`; health opcode0x50524205 is insufficient. The following
wire contract is a proposed interface for the Titan owner, implemented on the
AEL side only. Do not advertise it until the firmware actually implements it.

## Required v4 firmware interface

Identity opcode0x50524200 retains replacement-v1/source_id/Core/scene_pixels.
Add `capabilities.isolated_raw_capture = titan-replacement-direct-loopback-v4`
and `fixture_drain_max_words = 1000` only when implemented. Original control
version1, identity and112-byte status remain unchanged. AEL binds with
0x50524202 before fixture access. Health0x50524205 responses are retained as raw
JSON; this increment makes no invented health verdict from their contents.

Reuse ARM/STATUS/DRAIN/CANCEL0x50524601..04 request/reply layout documented by
`ael/titan_loopback.py`. ARM `<4I`: boot, epoch, pattern,1. STATUS `<2I`: boot,
epoch (0 readiness). DRAIN `<5I`: boot,epoch,stream,offset,count; reply repeats
that header then count uint32 timestamps. Streams0..3 are A-rise,A-fall,B-rise,
B-fall; stream4 is four-word SOF rows. One outstanding response; K1S1/K1R1 CRC.

STATUS is160 little-endian uint32 words. Words0..143 preserve v3 field positions
(`STATUS_FIELDS`, padding word63, `DIRECT_FIELDS`), except version4, capacity7712
and actual D-cache/MPU state. Words144..158, in order:

- DMA region begin/end (exclusive), observed MPU RBAR/RLAR/MAIR0;
- observer DMA channel numbers for A-rise,A-fall,B-rise,B-fall (4,5,6,7);
- microphone buffer envelope begin/end, LED buffer envelope begin/end;
- observer timeout_us (20000..500000), drain_max_words1000.

Word159 and existing reserved words must be zero. CCR D-cache bit16 and MPU
CTRL bit0 must be set. MPU region must exactly cover the declared aligned DMA
region with Normal noncacheable attribute0x44. All four7712-word buffers must be
32-byte aligned, nonoverlapping, inside that region and disjoint from microphone
and LED storage. Actual peripheral source/event/destination/count witnesses and
quiescent DMA checks remain the existing direct GPT7/GPT12 contract. Microphone
DMA1/2 and output DMA0/3 remain protected. Firmware must size/link its real
buffers and report actual registers; declarations are insufficient.

Each lane captures7680 rises and7680 falls (960 payload bytes), independent
leading/trailing LOW spans of at least105000 nominal300MHz ticks, and original
counter/frame boundaries. The pattern generator extends the existing frozen
algorithm to960 bytes, including last-byte boundary bits. Four buffers occupy
123392 bytes before SOF/status storage. Provide linker/MPU evidence and actual
resource readiness before stimulus. CANCEL must stop fixture activity without
stopping autonomous music. Readiness is checked after boot and before ARM.

## Commands

Use the existing working interpreter (system Python3.14 has an Expat load fault):

```sh
cd /Users/spectrasynq/ai-embedded-lab
/Users/spectrasynq/.platformio/penv/bin/python -m pytest tests/test_titan_replacement_observer.py tests/test_titan_isolated.py tests/test_prism_bench_trial.py -q
```

Offline candidate inspection, with a parent-prepared deployment manifest whose
bound receipt and image name the NEW candidate, not relabelled rc2-02:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m ael.titan_replacement_observer --manifest "$MANIFEST"
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan --target titan-replacement --action bench-trial-plan --deployment-manifest "$MANIFEST" --out "$FRESH_PLAN_DIR"
```

Manifest uses existing `prism.bench-trial.v1` fields. Set target=titan-replacement,
isolated_qualification backend=titan-replacement-direct-loopback-v4,
operation=titan-isolated-waveform-v2, frames100..120 and maximum_interruption_seconds120.
Optional pattern0..119 requests one full pair; it cannot qualify a full campaign.
Bind genuine physical_confirmation/bootstrap_authority/recovery records. The scope
now includes target,backend,capture_schema4,bits7680,bytes960 and cache mode, so old
80-pixel authority cannot admit this route. No physical setup is presumed confirmed.

After separately authorised physical preparation and firmware implementation ONLY:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -m ael.prism --lane titan --source /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan --target titan-replacement --action bench-trial-qualify-isolated --deployment-manifest "$MANIFEST" --out "$FRESH_RUN_DIR"
```

The existing K1_RFP_SWD_EXECUTE_OK gate is still required; this document does not
activate it. Expected same_dut_instance R7KA8P1KFLCAC, UID545433931bd25436593630352d068363,
E2Lite5AS079228B, target-power OFF are expectations, not observations. Both DIN
paths must be physically excluded before programming an autonomous candidate.

The Titan-owned client now exposes supported read commands (NOT executed here):

```sh
python3 /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/scripts/replacement_client.py --receipt "$CANDIDATE_RECEIPT" --port "$ADMITTED_PORT" identity
python3 /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/scripts/replacement_client.py --receipt "$CANDIDATE_RECEIPT" --port "$ADMITTED_PORT" status
python3 /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/scripts/replacement_client.py --receipt "$CANDIDATE_RECEIPT" --port "$ADMITTED_PORT" health
```

These commands identify a compatible resident; they do not identify an old donor.
Recovery read/signature commands remain the parent's native recovery procedure.
No new probe sequence was invented: actual AEL Golden Reference lookup for
R7KA8P1KFLCAC/e2lite returned no reference. Existing recovery whitelist was
preserved; neither old nor derived donor is claimed to be the observed incumbent.

## Limits and parent review

Logical120Hz is separate from the minimum10334us pair (max96.77Hz before overhead).
Candidate deadline80s, transaction120s and recovery programmer reserve35s are
unchanged. Capture budget is capped60s inside the candidate deadline. Full100-frame
drain throughput is unmeasured; there is no automatic window extension.

Mock tests establish parser/control behaviour only. The output-proof consumer
re-reads full raw evidence and still rejects UNQUALIFIED_INPUT_CAPTURE_TIMING.
Neither this route nor health JSON releases electrical/product HOLD. A parent
must implement and production-test firmware v4, build/bind the new receipt,
consolidate physical identity/isolation/ownership/recovery, then perform any
separately authorised acquisition. No screenshots apply to this host-only change;
source diff, CLI output and retained test logs are the inspection surfaces.
