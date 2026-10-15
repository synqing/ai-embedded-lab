# Replacement isolated observer — host increment, 16 October 2026

Titan must always visualise music. No device was accessed for this increment.
Normal autonomous output must survive fixture cancellation. Product HOLD remains.

## What runs

`ael.prism` now admits the explicit `titan-replacement` target using the existing
candidate source/object/toolchain receipt validator, isolated authority records,
single-owner transport and bounded recovery transaction. `prism_native` selects
replacement identity/status/bind, then the new collector. No old identity opcode,
old binding, old 80-pixel profile or legacy completion operation is substituted.
The collector issues ARM, polls STATUS, drains four complete polarity streams
plus SOF records, retains raw replies before parsing, checks the post-drain
snapshot and cancels only fixture work. Failure never retries ARM.

**Current source status (16 October review): host and firmware v4 are implemented;
runtime is unobserved.** Read-only inspection of canonical Titan
`platform/titan/native_replacement.cpp` and `replacement_fixture_capture.h` found
the advertised backend, actual status/drain dispatch, four 7712-word buffers,
explicit NOLOAD initialisation and MPU/DMA 4..7 witnesses. Final build 04 and its
candidate binding are parent-owned and pending at this review. No live readiness
or physical acquisition is claimed. Health opcode 0x50524205 remains separate.

## Current v4 firmware interface

Identity opcode 0x50524200 retains replacement-v1/source_id/Core/scene_pixels.
Current source advertises
`capabilities.isolated_raw_capture = titan-replacement-direct-loopback-v4`
and `fixture_drain_max_words = 1000`. Original control
version 1, identity and 112-byte status remain unchanged. AEL binds with
0x50524202 before fixture access. Health 0x50524205 responses are retained as raw
JSON; this increment makes no invented health verdict from their contents.

Reuse ARM/STATUS/DRAIN/CANCEL 0x50524601..04 request/reply layout documented by
`ael/titan_loopback.py`. ARM `<4I`: boot, epoch, pattern,1. STATUS `<2I`: boot,
epoch (0 readiness). DRAIN `<5I`: boot,epoch,stream,offset,count; reply repeats
that header then count uint32 timestamps. Streams0..3 are A-rise,A-fall,B-rise,
B-fall; stream4 is four-word SOF rows. One outstanding response; K1S1/K1R1 CRC.

STATUS is 160 little-endian uint32 words. Words0..143 preserve v3 field positions
(`STATUS_FIELDS`, padding word63, `DIRECT_FIELDS`), except version 4, capacity 7712
and actual D-cache/MPU state. Words144..158, in order:

- DMA region begin/end (exclusive), observed MPU RBAR/RLAR/MAIR0;
- observer DMA channel numbers for A-rise,A-fall,B-rise,B-fall (4,5,6,7);
- microphone buffer envelope begin/end, LED buffer envelope begin/end;
- observer timeout_us (20000..500000), drain_max_words 1000.

Word159 and existing reserved words must be zero. CCR D-cache bit16 and MPU
CTRL bit0 must be set. MPU region must exactly cover the declared aligned DMA
region with Normal noncacheable attribute 0x44. All four 7712-word buffers must be
32-byte aligned, nonoverlapping, inside that region and disjoint from microphone
and LED storage. Actual peripheral source/event/destination/count witnesses and
quiescent DMA checks remain the existing direct GPT7/GPT12 contract. Microphone
DMA1/2 and output DMA0/3 remain protected. Firmware must size/link its real
buffers and report actual registers; declarations are insufficient.

Each lane captures 7680 rises and 7680 falls (960 payload bytes), independent
leading/trailing LOW spans of at least 105000 nominal 300 MHz ticks, and original
counter/frame boundaries. The pattern generator extends the existing frozen
algorithm to 960 bytes, including last-byte boundary bits. Four buffers occupy
123392 bytes before SOF/status storage. Provide linker/MPU evidence and actual
resource readiness before stimulus. CANCEL must stop fixture activity without
stopping autonomous music. Readiness is checked after boot and before ARM.

## Commands

Use the existing working interpreter (system Python 3.14 has an Expat load fault):

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
operation=titan-isolated-waveform-v2, frames 100..120 and maximum_interruption_seconds 120.
Optional pattern 0..119 requests one full pair; it cannot qualify a full campaign.
Bind genuine physical_confirmation/bootstrap_authority/recovery records. The scope
now includes target,backend,capture_schema 4,bits 7680,bytes 960 and cache mode, so old
80-pixel authority cannot admit this route. No physical setup is presumed confirmed.

After final candidate binding, clean source admission and separately authorised physical preparation ONLY:

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

Logical 120 Hz is separate from the minimum 10334 us pair (max 96.77 Hz before overhead).
Candidate deadline 80s, transaction 120s and recovery programmer reserve 35s are
unchanged. Capture budget is capped 60s inside the candidate deadline. Full 100-frame
drain throughput is unmeasured; there is no automatic window extension.

Mock tests establish parser/control behaviour only. The output-proof consumer
re-reads full raw evidence and still rejects UNQUALIFIED_INPUT_CAPTURE_TIMING.
Neither this route nor health JSON releases electrical/product HOLD. A parent
must finish production validation of firmware v4 and build/bind the new receipt,
consolidate physical identity/isolation/ownership/recovery, then perform any
separately authorised acquisition. No screenshots apply to this host-only change;
source diff, CLI output and retained test logs are the inspection surfaces.

## Source admission is still blocked by the actual dirty checkout

`prism_bench_trial.validate_manifest` first compares the selected source HEAD to
`source_commit`, then requires `git status --porcelain --untracked-files=no` to
be empty. This is a whole tracked-tree gate, including unrelated W4 scratch and
migration-index edits. Committing only current replacement files cannot clear
it while those inherited paths remain dirty. `bench-trial-plan` also runs this
validator, so even that plan command currently refuses `Dirty candidate source`
before admission. The offline observer profile check remains runnable, but it
is explicitly not source/deployment admission. Immutable candidate receipts
remain evidence of their identified build; checkout dirt does not erase them.

Legitimate resumption under the current gate requires the respective owners to
reconcile all retained tracked edits into an approved clean checkpoint in the
existing Titan repository, without discarding or disguising them. Then build or
validate the final candidate against that checkpoint and bind its actual HEAD,
source-profile, receipt and image in the manifest. Do not stash/reset someone
else's work, create a clean sibling, switch to a different source, or remove
paths from this check. If owner reconciliation is unavailable, this AEL execution
route remains blocked; a policy change would be a separate authorised workflow
change, not part of this adapter repair.

The collector now supplies its 60-second capture/drain cutoff to every framed
exchange; cancellation alone receives the outer candidate deadline (at most 80s).
The 120s transaction and 35s recovery programmer reserve remain unchanged.

Verified bound recovery fields and original paths are written to
`_scratch/packet_c_replacement_20261016/recovery-manifest-fields.json`. Re-run the
existing read-only validator with:

```sh
/Users/spectrasynq/.platformio/penv/bin/python -c 'import json; from ael.adapters.prism_bench_trial import require_titan_recovery; print(json.dumps(require_titan_recovery(json.load(open("_scratch/packet_c_replacement_20261016/recovery-manifest-fields.json"))), indent=2))'
```

These recovery bytes and historical range verification are not a current
resident observation or evidence that the derived image has been programmed.
