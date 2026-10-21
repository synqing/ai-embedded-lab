"""Replacement-only collector. Firmware v4 support is required, never presumed.

Uses the existing sole-owner framed exchange and isolated transaction. No port,
probe or programming ownership is created here. Digital consistency is not
electrical qualification.
"""
from __future__ import annotations
import json
import math
import struct
import sys
import time
from pathlib import Path

from ael import titan_loopback as legacy
from ael.titan_waveform import UID, bound, digest, require

BACKEND = "titan-replacement-direct-loopback-v4"
PAIRED_BACKEND = "titan-replacement-buffered-loopback-v5"
IDENTITY, CONTROL_STATUS, HEALTH = 0x50524200, 0x50524201, 0x50524205
CAPACITY = 7712
BITS = 7680  # v4-v6 wire frame per lane; kept for those contracts only.
# Bits (= edges per polarity stream) per lane, keyed by the status version word.
# v7 (Phase 1, 21 Oct 2026) drives 80 GRB48 pixels per lane: 3,840 bits, 480 bytes.
# Never infer one version's geometry from another's.
BITS_BY_VERSION = {4: 7680, 5: 7680, 6: 7680, 7: 3840}
WORDS_PER_RECORD = 2
RISE_RECORD_WORDS = 2
FALL_RECORD_WORDS = 3
V6_GTBER = 0x00090000
HISTORY_FAULT = 12
GUARD = 0xD1A6C0DE
V5_STATUS_WORDS = 192
V5_EXTENSION = (
    "dmamd_a_rise", "dmamd_a_fall", "dmamd_b_rise", "dmamd_b_fall",
    "dmofr_a_rise", "dmofr_a_fall", "dmofr_b_rise", "dmofr_b_fall",
    "dmcra_a_rise", "dmcra_a_fall", "dmcra_b_rise", "dmcra_b_fall",
    "dmcrb_a_rise", "dmcrb_a_fall", "dmcrb_b_rise", "dmcrb_b_fall",
    "seed_live_a_rise", "seed_live_a_fall", "seed_live_b_rise", "seed_live_b_fall",
    "seed_history_a_rise", "seed_history_a_fall", "seed_history_b_rise", "seed_history_b_fall",
    "guard_a_rise", "guard_a_fall", "guard_b_rise", "guard_b_fall",
    "prearm_counter_a", "prearm_counter_b", "words_per_record", "reserved_v5",
)
CORE = "0b6d1fb7f9a22a951818c1508b3de9ca289f4bdf"
EXTENSION = ("dma_begin", "dma_end", "dma_rbar", "dma_rlar", "dma_mair0",
             "dma_a_rise", "dma_a_fall", "dma_b_rise", "dma_b_fall",
             "microphone_begin", "microphone_end", "led_begin", "led_end",
             "observer_timeout_us", "drain_max_words")
SCHEMA = "prism.titan.replacement-acquisition.v1"
LEAVE_SCHEMA = "prism.titan.replacement-leave-proof.v1"


def validate_profile(manifest, record):
    require(manifest.get("target") == "titan-replacement", "Wrong replacement profile")
    require(manifest.get("identity") == UID and record.get("schema") == "prism-product-build.v1"
            and type(record.get("exit_code")) is int and record["exit_code"] == 0
            and record.get("hardware_access") is False and record.get("product_admitted") is False,
            "Wrong candidate receipt scope")
    argv = record.get("argv", [])
    require(argv.count("--profile") == 1 and argv.index("--profile") + 1 < len(argv)
            and argv[argv.index("--profile") + 1] == "titan-replacement",
            "Build did not select replacement profile")
    require(record.get("core_commit") == CORE and record.get("core_tag") == "v0.12.0-rc.2",
            "Wrong replacement Core identity")
    profile = json.loads(bound({"path": str(Path(manifest["build_receipt"]["path"]).parent / "source-profile.json"),
                               "sha256": manifest["source_binding_hash"]}))
    require(profile.get("application_profile") == "titan-replacement", "Wrong source profile")


def selected_backend(info):
    """Explicit capability selects the wire contract. A missing v5 name stays on v4."""
    capability = info.get("capabilities", {}).get("isolated_raw_capture")
    if capability == PAIRED_BACKEND:
        return PAIRED_BACKEND
    if capability == BACKEND:
        return BACKEND
    raise RuntimeError("BLOCKED_CAPTURE_CAPABILITY: replacement firmware fixture is absent")


def identity(info, manifest):
    require(manifest.get("target") == "titan-replacement" and info.get("uid") == UID
            and info.get("contract") == "titan-replacement-v1"
            and info.get("build_profile") == "titan-replacement"
            and info.get("source_id") == manifest["source_binding_hash"]
            and info.get("core_commit") == CORE and info.get("core_tag") == "v0.12.0-rc.2"
            and info.get("scene_pixels") == [160, 160] and info.get("logical_hz") == 120,
            "Replacement identity/source/profile/geometry mismatch")
    backend = selected_backend(info)
    manifest_backend = manifest.get("isolated_qualification", {}).get("backend", BACKEND)
    require(manifest_backend == backend, "Manifest observer/backend does not match firmware capability")
    require(info["capabilities"].get("fixture_drain_max_words") == 1000,
            "Replacement requires bounded 1000-word drain capability")
    return backend


def control_status(raw):
    require(len(raw) == 112, "Replacement status must remain 112 bytes")
    version, boot, _, target = struct.unpack_from("<4I", raw)
    require(version == 1 and boot > 0 and target == 1 and raw[16:48] == UID.encode(),
            "Replacement status version/boot/target mismatch")
    return boot


def frame_bits(s):
    """Wire bits per lane for this status version. An unknown version is refused."""
    version = s.get("version")
    require(version in BITS_BY_VERSION, "No frame geometry for replacement status version")
    return BITS_BY_VERSION[version]


def require_scope_geometry(s, manifest):
    """The decoded status version's lane bits must equal the scope's bits_each (absent: 7680)."""
    scoped = manifest.get("isolated_qualification", {}).get("bits_each", BITS)
    bits = frame_bits(s)
    require(bits == scoped, f"Status geometry disagrees with scope: v{s['version']} status has "
            f"{bits} bits per lane, scope declares {scoped}")


def verify_memory(s):
    require(s["ccr"] & (1 << 16) and s["mpu"] & 1, "Replacement D-cache/MPU disabled")
    begin, end = s["dma_begin"], s["dma_end"]
    rbar, rlar, mair = s["dma_rbar"], s["dma_rlar"], s["dma_mair0"]
    attr = (rlar >> 1) & 7
    require(begin > 0 and end > begin and begin % 32 == end % 32 == 0
            and rlar & 1 and attr <= 3 and (mair >> (attr * 8)) & 255 == 0x44
            and rbar & 0xffffffe0 == begin and (rlar & 0xffffffe0) + 32 == end,
            "Replacement noncache MPU span mismatch")
    channels = [s["dma_" + name] for name in legacy.SPLIT_NAMES]
    require(channels == [4, 5, 6, 7], "Observer aliases microphone/LED DMA or wrong stream ownership")
    require(s["observer_timeout_us"] >= 20000 and s["observer_timeout_us"] <= 500000
            and s["drain_max_words"] == 1000, "Inadequate replacement capture/drain configuration")
    protected = [(s[name+"_begin"], s[name+"_end"]) for name in ("microphone", "led")]
    require(all(begin <= lo < hi <= end for lo,hi in protected), "Missing protected DMA spans")
    if s["version"] in (6, 7):
        row_words = CAPACITY * FALL_RECORD_WORDS + 8
    elif s["version"] == 5:
        row_words = CAPACITY * WORDS_PER_RECORD + 8
    else:
        row_words = CAPACITY
    row_bytes = row_words * 4
    addresses = [s["buffer_" + name] for name in legacy.SPLIT_NAMES]
    require(all(abs(a-b) >= row_bytes for index,a in enumerate(addresses) for b in addresses[index+1:]),
            "Observer DMA rows overlap")
    for name in legacy.SPLIT_NAMES:
        address = s["buffer_" + name]
        require(address % 32 == 0 and begin <= address < address + row_bytes <= end,
                "Observer DMA buffer outside observed noncache span")
        require(all(address + row_bytes <= lo or hi <= address for lo,hi in protected),
                "Observer buffer aliases microphone/LED storage")


def status(raw, boot, epoch, *, layout=None):
    """Decode one replacement status. layout None accepts the length that matches the version word.

    v4 remains exactly 640 bytes. v5, v6 and v7 are exactly 768 bytes and are told apart by
    the version word. v7 is the v6 field map with 3,840-bit lanes (BITS_BY_VERSION). Passing
    the other length is a refusal, never a conversion of one contract into the other.
    """
    if layout is None:
        require(len(raw) in (640, 768), "Replacement status requires 160 or 192 words")
        layout = 5 if len(raw) == 768 else 4
        if layout == 5 and struct.unpack_from("<I", raw)[0] in (6, 7):
            layout = struct.unpack_from("<I", raw)[0]
    if layout == 4:
        require(len(raw) == 640, "Replacement v4 status requires 160 words")
        words = struct.unpack("<160I", raw)
        require(words[:3] == (4, boot, epoch), "Stale replacement version/boot/epoch")
        require(words[63] == 0 and words[159] == 0, "Unknown replacement status extension")
        s = dict(zip(legacy.STATUS_FIELDS, words[:63]))
        s.update(zip(legacy.DIRECT_FIELDS, words[64:144]))
        s.update(zip(EXTENSION, words[144:159]))
    elif layout == 5:
        require(len(raw) == 768, "Replacement v5 status requires 192 words")
        words = struct.unpack("<192I", raw)
        require(words[:3] == (5, boot, epoch), "Stale replacement version/boot/epoch")
        require(words[63] == 0 and words[107] == 3 and words[159] == 0, "Unknown replacement v5 layout")
        require(words[191] == 0, "Unknown replacement v5 reserved word")
        s = dict(zip(legacy.STATUS_FIELDS, words[:63]))
        s.update(zip(legacy.DIRECT_FIELDS, words[64:144]))
        s.update(zip(EXTENSION, words[144:159]))
        s.update(zip(V5_EXTENSION, words[160:192]))
        require(s["words_per_record"] == WORDS_PER_RECORD, "Paired record width mismatch")
    elif layout == 6 or layout == 7:
        # v7 keeps every v6 word; only the frame geometry differs (frame_bits).
        require(len(raw) == 768, f"Replacement v{layout} status requires 192 words")
        words = struct.unpack("<192I", raw)
        require(words[:3] == (layout, boot, epoch), "Stale replacement version/boot/epoch")
        require(words[63] == 0 and words[107] == 4 and words[159] == 0, f"Unknown replacement v{layout} layout")
        require(words[190] == RISE_RECORD_WORDS and words[191] == FALL_RECORD_WORDS,
                f"Replacement v{layout} record widths mismatch")
        require(words[143] == 0, f"Unknown replacement v{layout} reserved word")
        s = dict(zip(legacy.STATUS_FIELDS, words[:63]))
        s.update(zip(legacy.DIRECT_FIELDS, words[64:144]))
        s.update(zip(EXTENSION, words[144:159]))
        s.update(zip(V5_EXTENSION, words[160:192]))
        s["seed_second_a_fall"] = words[137]
        s["seed_second_b_fall"] = words[138]
        for index, name in enumerate(legacy.SPLIT_NAMES):
            s["history_unresolved_" + name] = bool(words[139 + index] >> 31)
            s["recovered_" + name] = words[139 + index] & 0xffff
            s["duplicates_" + name] = (words[139 + index] >> 16) & 0x7fff
        s["rise_record_words"] = words[190]
        s["fall_record_words"] = words[191]
    else:
        raise RuntimeError("Unknown replacement status layout")
    require(s["capacity"] == CAPACITY and s["state"] <= 8 and s["sof_rows"] <= 256,
            "Wrong replacement capacity/state")
    require(all(s[field + "_" + name] <= CAPACITY for field in ("words", "remaining")
                for name in legacy.SPLIT_NAMES), "Oversized replacement capture")
    return s


def _mod_distance(later, earlier):
    return (later - earlier) & 0xffffffff


def _inside_window(tick, begin, end):
    """Strict interior of the independently witnessed counter interval."""
    span = _mod_distance(end, begin)
    require(0 < span < 0x80000000, "Capture window width is not a single modular half-range")
    return 0 < _mod_distance(tick, begin) < span


def canonical_pairs(raw_words, records, live_seed, history_seed, begin, end):
    """Accept every raw pair. Outside words survive only when they equal the observed pre-arm seed.

    A pair may straddle two captures: both values stay real. No expected payload is consulted.
    Two or more overwrites of the same physical edge leave a hole and fail the unique count.
    """
    require(len(raw_words) == records * WORDS_PER_RECORD, "Paired raw length is not two words per record")
    require(not _inside_window(live_seed, begin, end), "Pre-arm live seed lies inside the capture window")
    require(not _inside_window(history_seed, begin, end), "Pre-arm history seed lies inside the capture window")
    accepted = []
    for index in range(records):
        pair = raw_words[index * 2:index * 2 + 2]
        for word in pair:
            if _inside_window(word, begin, end):
                accepted.append(word)
            elif word in (live_seed, history_seed):
                continue
            else:
                raise RuntimeError(f"Outside timestamp {word:#x} is not the observed pre-arm seed")
    require(any(_inside_window(word, begin, end) for word in raw_words[1::2]),
            "Paired history never captured an edge")
    unique = []
    seen = set()
    for word in accepted:
        if word not in seen:
            seen.add(word)
            unique.append(word)
    require(len(unique) == records, "Paired unique timestamp count is not one per DMA record")
    # Chronology is modular distance from the independent window start, never a numeric sort
    # that would mis-order a counter wrap.
    unique.sort(key=lambda tick: _mod_distance(tick, begin))
    for earlier, later in zip(unique, unique[1:]):
        require(_mod_distance(later, earlier) != 0, "Duplicate canonical timestamp")
    return unique


def record_words(stream):
    """Rise streams are (live, history). Fall streams add the second history word."""
    return FALL_RECORD_WORDS if stream % 2 else RISE_RECORD_WORDS


def record_dmcra(stream):
    """DMCRA block and repeat counts: two words on a rise, three on a fall."""
    return 0x00030003 if stream % 2 else 0x00020002


def paired_layout(raw_status):
    """Return 5, 6 or 7 from the raw paired version word. Any other version is refused."""
    require(isinstance(raw_status, (bytes, bytearray)) and len(raw_status) >= 4,
            "Paired status has no version word")
    version = struct.unpack_from("<I", raw_status)[0]
    require(version in (5, 6, 7), "Paired status version is not 5, 6 or 7")
    return version


def recover_history(records, width, *, with_duplicates=False):
    """Rebuild one edge stream using the same rule as recover_history in the fixture header.

    Record 0 contributes its live word only. Each later record must continue the capture
    shift chain from the previous live word. A rise carries at most one coalesced edge
    and a fall at most two. Returns (ticks, recovered_count).
    """
    require(width in (RISE_RECORD_WORDS, FALL_RECORD_WORDS), "Unsupported history record width")
    require(records, "History rebuild has no DMA record")
    # A block identical to the previous one re-read unchanged registers: no edge
    # (an extra transfer raised while a slow one was still reading; v6c frame 6).
    kept, duplicates = [records[0]], 0
    for record in records[1:]:
        if tuple(record) == tuple(kept[-1]):
            duplicates += 1
        else:
            kept.append(record)
    normal = [_history_record(r, width) for r in kept]
    ticks = [normal[0][0]]
    recovered = 0
    for (prev, prev_first, _), (live, first, second) in zip(normal, normal[1:]):
        span = _mod_distance(live, prev)
        if span == 0 or span >= 0x80000000:
            raise RuntimeError("Inconsistent history chain")
        if first is None:
            ticks.append(live)
            continue
        if first == prev:
            if second is not None and prev_first is not None and second != prev_first:
                raise RuntimeError("Inconsistent history chain")
            ticks.append(live)
            continue
        newer = _mod_distance(first, prev)
        if newer == 0 or newer >= span:
            raise RuntimeError("Inconsistent history chain")
        if second is None or second == prev:
            ticks.extend((first, live))
            recovered += 1
            continue
        older = _mod_distance(second, prev)
        if older == 0 or older >= newer:
            raise RuntimeError("Inconsistent history chain")
        ticks.extend((second, first, live))
        recovered += 2
    return (ticks, recovered, duplicates) if with_duplicates else (ticks, recovered)


def _history_record(record, width):
    """Mirror history_record in the fixture header: a capture landing between a block's
    reads shifts the registers, so (x,w,v) reads as (x,x,w) or (x,w,w) and (x,w) as
    (x,x). Equal adjacent words name the torn read; the shifted-out word is unknown."""
    live = record[0]
    if record[1] == live:
        return (live, record[2], None) if width == FALL_RECORD_WORDS else (live, None, None)
    if width == FALL_RECORD_WORDS and record[2] == record[1]:
        return (live, record[1], None)
    return (live, record[1], record[2] if width == FALL_RECORD_WORDS else None)


def verify_v6_configuration(s, *, complete=False, readiness=False):
    """v6/v7 block capture. Fall DMA blocks are three words. Completed blocks may be under
    the frame's bits (7680 for v6, 3840 for v7)."""
    require(s["version"] in (6, 7), "v6 configuration requires status version 6 or 7")
    bits = frame_bits(s)
    require(s["split_capability"] == 4 and s["reserved"] == 0 and s["reserved_143"] == 0,
            "Unknown v6 capture capability")
    require(s["rise_record_words"] == RISE_RECORD_WORDS and s["fall_record_words"] == FALL_RECORD_WORDS,
            "v6 record widths are not 2 and 3")
    verify_memory(s)
    expected_period = 0xfffffffe if readiness else 0xffffffff
    require(s["gpt7_gtpr"] == s["gpt12_gtpr"] == expected_period, "Direct counter modulus mismatch")
    if not readiness:
        # GTBER is written when capture opens, not in the idle bootstrap snapshot.
        require(s["gtber"] == s["gpt12_gtber"] == V6_GTBER, "v6 GTBER is not single-A/double-B history")
        require((s["gticasr"], s["gticbsr"], s["gpt12_gticasr"], s["gpt12_gticbsr"]) ==
                (0x300, 0xc00, 0x3000, 0xc000), "Direct polarity selector mismatch")
        require((s["elc_e"], s["elc_f"], s["elc_g"], s["elc_h"]) == (0x1c0, 0x1c1, 0x1ed, 0x1ee) and
                s["gpt2_gtupsr"] == 0x300000 and s["gpt3_gtupsr"] == 0xc00000,
                "Direct edge counter/event mapping mismatch")
        require(s["gpt12_gtcr"] == s["gpt7_gtcr"] == s["gpt2_gtcr"] == s["gpt3_gtcr"] == 1 and
                s["gpt12_gtior"] == s["gtior"] == 0,
                "Direct timer mode/filter mismatch")
        require(s["p603_pfs"] & ~2 == s["p714_pfs"] & ~2 == 0x03010000,
                "Direct physical pin configuration mismatch")
        require(s["gpt12_initial"] == s["gpt7_initial"] == 0 and s["start_mask"] == 0x1080,
                "Direct timer initialisation/start mismatch")
        for lane, prefix in (("a", ""), ("b", "b_")):
            require(_mod_distance(s[prefix + "leading_begin"], s["prearm_counter_" + lane]) < 0x80000000,
                    "Pre-arm counter follows the independently witnessed leading boundary")
    sources = (0x4032274c, 0x40322750, 0x40322c4c, 0x40322c50)
    events = (0x1c0, 0x1c1, 0x1ed, 0x1ee)
    names = legacy.SPLIT_NAMES
    buffers = [s["buffer_" + name] for name in names]
    row_bytes = (CAPACITY * FALL_RECORD_WORDS + 8) * 4
    require(all(abs(a - b) >= row_bytes for index, a in enumerate(buffers) for b in buffers[index + 1:]),
            "Overlapping v6 DMA buffers")
    for index, name in enumerate(names):
        width = record_words(index)
        require(s["dmtmd_" + name] == 0x9201, "Paired DMTMD is not normal BLOCK mode: " + name)
        require(s["dmamd_" + name] == 0x4080, "Paired DMAMD source-offset/dest-increment mismatch: " + name)
        require(s["dmint_" + name] == 0, "Paired DMA repeat-block interrupt must stay clear: " + name)
        require(s["dmofr_" + name] == 8, "Paired source offset mismatch: " + name)
        require(s["dmcra_" + name] == record_dmcra(index), "v6 DMCRA block geometry mismatch: " + name)
        require(s["guard_" + name] == 1, "Paired row guard was overwritten: " + name)
        require(s["event_" + name] == events[index], "Split DMA ownership mismatch: " + name)
        require(s["source_" + name] == s["expected_source_" + name] == sources[index]
                and s["buffer_" + name] != 0, "Split DMA address mismatch: " + name)
        require(s["words_" + name] <= CAPACITY and s["remaining_" + name] + s["words_" + name] == CAPACITY,
                "Paired block remaining/count mismatch: " + name)
        require(s["destination_" + name] == s["buffer_" + name] + 4 * width * s["words_" + name],
                "Split DMA destination/count mismatch: " + name)
        require(s["cursor_" + name] <= width * s["words_" + name],
                "Raw-word cursor exceeds captured records: " + name)
        if complete:
            require(s.get("history_unresolved_" + name)
                    or s["words_" + name] + s["recovered_" + name] - s.get("duplicates_" + name, 0) == bits,
                    f"v{s['version']} DMA blocks plus recovered history are not {bits}: " + name)
            require(s["dmcrb_" + name] == s["remaining_" + name],
                    "Frozen DMCRB is not the remaining block count: " + name)
            require(s["dmsts_" + name] == 0, "Paired DMA not quiescent: " + name)
        elif readiness:
            require(s["dmcrb_" + name] == CAPACITY, "Ready DMCRB is not 7712 blocks: " + name)
    if complete:
        require(s["edges_a"] == s["edges_b"] == 2 * bits,
                f"Combined v{s['version']} hardware edge count is not {2 * bits} per lane")


def verify_paired_configuration(s, *, complete=False, readiness=False):
    """v5 block-mode DMA. Record counts live in words_*; raw cursors are cursor_raw_*."""
    if s.get("version") in (6, 7):
        return verify_v6_configuration(s, complete=complete, readiness=readiness)
    legacy.verify_direct_configuration(s, complete=complete, readiness=readiness)
    require(s["version"] == 5, "Paired configuration requires status version 5")
    for name in legacy.SPLIT_NAMES:
        require(s["dmtmd_" + name] == 0x9201, "Paired DMTMD is not normal BLOCK mode: " + name)
        require(s["dmamd_" + name] == 0x4080, "Paired DMAMD source-offset/dest-increment mismatch: " + name)
        require(s["dmint_" + name] == 0, "Paired DMA repeat-block interrupt must stay clear: " + name)
        require(s["words_" + name] <= CAPACITY and s["remaining_" + name] + s["words_" + name] == CAPACITY,
                "Paired block remaining/count mismatch: " + name)
        if complete:
            require(s["words_" + name] == BITS and s["remaining_" + name] == 32, "Incomplete paired DMA blocks: " + name)
            require(s["dmcrb_" + name] == 32, "Frozen DMCRB is not the full-frame remainder: " + name)
            require(s["dmsts_" + name] == 0, "Paired DMA not quiescent: " + name)
        elif readiness:
            require(s["dmcrb_" + name] == CAPACITY, "Ready DMCRB is not 7712 blocks: " + name)
        offset = 8  # A->C and B->E both advance 8 bytes; register order A,B,C,E,D,F.
        require(s["dmofr_" + name] == offset, "Paired source offset mismatch: " + name)
        require(s["dmcra_" + name] == 0x00020002, "Paired DMCRA block geometry mismatch: " + name)
        require(s["guard_" + name] == 1, "Paired row guard was overwritten: " + name)
        require(s["cursor_" + name] <= WORDS_PER_RECORD * s["words_" + name],
                "Raw-word cursor exceeds captured records: " + name)
    if not readiness:
        for lane, prefix in (("a", ""), ("b", "b_")):
            require(_mod_distance(s[prefix + "leading_begin"], s["prearm_counter_" + lane]) < 0x80000000,
                    "Pre-arm counter follows the independently witnessed leading boundary")


def verify_paired_epoch(s, streams, pattern):
    """Same pulse/payload/period/quiet gates as v4, applied to canonical words recovered from raw pairs."""
    require(len(streams) == 5, "Missing paired raw stream")
    require(s["state"] == 6 and s["fault"] == s["first_fsp_error"] == 0, "Paired loopback did not complete cleanly")
    require(s["pattern"] == pattern, "Wrong diagnostic frame index")
    verify_paired_configuration(s, complete=True)
    for prefix in ("", "b_"):
        for first, last in (("leading_begin", "leading_end"), ("trailing_begin", "trailing_end")):
            span = _mod_distance(s[prefix + last], s[prefix + first])
            require(105000 <= span < 0x80000000, "Missing replacement 350us reset coverage")
    canonical = []
    provenance = []
    for index, name in enumerate(legacy.SPLIT_NAMES):
        prefix = "b_" if index >= 2 else ""
        require(len(streams[index]) == WORDS_PER_RECORD * BITS * 4,
                "Paired raw length is not two words per full-frame record")
        words = struct.unpack("<" + "I" * (WORDS_PER_RECORD * BITS), streams[index])
        ticks = canonical_pairs(words, BITS, s["seed_live_" + name], s["seed_history_" + name],
                                s[prefix + "leading_end"], s[prefix + "trailing_begin"])
        canonical.append(ticks)
        first_index = {}
        for word_index, tick in enumerate(words):
            first_index.setdefault(tick, word_index)
        provenance.append([first_index[tick] for tick in ticks])
        require(len(ticks) == BITS, "Incomplete paired polarity: " + name)
    # Combined hardware edges are the four canonical streams, not a fifth counter.
    require(s["edges_a"] == s["edges_b"] == 15360,
            "Combined paired hardware edge count is not 15360 per lane")
    # Hand the canonical single-word streams to the existing pulse oracle. The raw files stay
    # the provenance; this view is derived and is never written back as a v4 capture.
    single = [struct.pack("<" + "I" * BITS, *ticks) for ticks in canonical]
    result = legacy.verify_split_epoch(s, single, streams[4], pattern=pattern, pulses=BITS)
    result["canonical_raw_word_indices"] = provenance
    result["raw_physical_qualification"] = False
    result["physical_qualification"] = False
    result["paired_records_each"] = BITS
    result["raw_words_each"] = WORDS_PER_RECORD * BITS
    return result


def verify_v6_epoch(s, streams, pattern):
    """Rebuild each v6/v7 stream from its history records, then use the existing pulse oracle.

    The expected edge count per stream is the version's frame bits: 7680 (v6) or 3840 (v7).
    """
    require(len(streams) == 5, "Missing v6 raw stream")
    bits = frame_bits(s)
    require(s["fault"] != HISTORY_FAULT, "Inconsistent history chain")
    require(s["state"] == 6 and s["fault"] == s["first_fsp_error"] == 0, "v6 loopback did not complete cleanly")
    require(s["pattern"] == pattern, "Wrong diagnostic frame index")
    verify_v6_configuration(s, complete=False)
    for prefix in ("", "b_"):
        for first, last in (("leading_begin", "leading_end"), ("trailing_begin", "trailing_end")):
            span = _mod_distance(s[prefix + last], s[prefix + first])
            require(105000 <= span < 0x80000000, "Missing replacement 350us reset coverage")
    rebuilt = []
    recovered = []
    for index, name in enumerate(legacy.SPLIT_NAMES):
        width = record_words(index)
        blocks = s["words_" + name]
        require(len(streams[index]) == width * blocks * 4,
                "v6 raw length is not the record width times completed DMA blocks")
        raw = struct.unpack("<" + "I" * (width * blocks), streams[index])
        records = [raw[pos:pos + width] for pos in range(0, len(raw), width)]
        ticks, count, dups = recover_history(records, width, with_duplicates=True)
        # Device-flagged streams are decoded by the host alone; recover_history still
        # raises on any chain it cannot explain, and the total must be exact.
        require(s.get("history_unresolved_" + name)
                or (count == s["recovered_" + name] and dups == s["duplicates_" + name]),
                "Host/firmware recovered-count mismatch: " + name)
        require(blocks + count - dups == bits and len(ticks) == bits,
                f"Rebuilt edge stream is not {bits} ticks: " + name)
        rebuilt.append(ticks)
        recovered.append(count)
    require(s["edges_a"] == s["edges_b"] == 2 * bits,
            f"Combined v{s['version']} hardware edge count is not {2 * bits} per lane")
    single = [struct.pack("<" + "I" * bits, *ticks) for ticks in rebuilt]
    result = legacy.verify_split_epoch(s, single, streams[4], pattern=pattern, pulses=bits)
    result["recovered_edges"] = recovered
    result["physical_qualification"] = False
    return result


def verify_epoch(s, streams, pattern):
    if s.get("version") in (6, 7):
        return verify_v6_epoch(s, streams, pattern)
    if s.get("version") == 5:
        return verify_paired_epoch(s, streams, pattern)
    require(s.get("version") == 4, "Replacement epoch is neither v4 nor v5")
    require(len(streams) == 5, "Missing replacement raw stream")
    result = legacy.verify_split_epoch(s, streams[:4], streams[4], pattern=pattern, pulses=BITS)
    for prefix in ("", "b_"):
        # 300 MHz nominal ticks: diagnostic consistency only, not calibrated time.
        for first, last in (("leading_begin", "leading_end"), ("trailing_begin", "trailing_end")):
            span = (s[prefix + last] - s[prefix + first]) & 0xffffffff
            require(105000 <= span < 0x80000000, "Missing replacement 350us reset coverage")
    return result


def verify_replacement_program(event, image, spans):
    """Re-read the sealed writer receipt. Gateway argv is not an RFP program log.

    A historical raw `rfp-cli -pv` argv still goes through the strict log parser.
    Flags inside the event are not a substitute for either check.
    """
    from ael.titan_isolated import verify_program_log, verify_sealed_program
    argv = event.get("argv")
    receipt = event.get("sealed_writer_receipt")
    programme = event.get("programme_directory")
    if isinstance(receipt, dict) and programme:
        sealed = json.loads(bound(receipt))
        programme_dir = Path(programme)
        receipt_path = Path(receipt["path"]).resolve()
        require(receipt_path.parent == programme_dir.resolve(), "Sealed receipt is not in its programme directory")
        require(receipt_path.is_file(), "Sealed writer receipt file missing")
        verify_sealed_program(sealed, image=image, programme_dir=programme_dir, spans=spans)
        return
    if isinstance(argv, list) and len(argv) >= 2 and argv[-2] == "-pv" and Path(argv[-1]) == Path(image):
        verify_program_log(bound(event["programmer_log"]), returncode=event["returncode"], argv=argv,
                           image=image, spans=spans)
        return
    raise RuntimeError("Programming event has no bound sealed writer receipt and is not a raw RFP program/verify log")


def revalidate_leave_proof(row):
    """Re-read identity, control, terminal status and cancel bytes. JSON boot is not authority."""
    if isinstance(row, (str, Path)):
        raw = Path(row).read_bytes()
        proof = json.loads(raw)
        proof_sha = digest(raw)
    else:
        raw = bound(row)
        proof = json.loads(raw)
        proof_sha = row["sha256"]
    require(proof.get("schema") == LEAVE_SCHEMA, "Wrong leave-proof schema")
    # cancelled_after_stop: a run stopped before completion and cancelled cleanly (20 Oct 2026).
    # It qualifies only the board's idle leave state; it is never a capture result.
    require(proof.get("classification") in ("complete", "capture_verification_failed", "cancelled_after_stop"),
            "Leave proof is not a completion, a post-drain verification failure or a cancelled stop")
    identity_raw = bound(proof["identity_raw"])
    control_raw = bound(proof["control_raw"])
    status_raw = bound(proof["terminal_status_raw"])
    cancel_raw = bound(proof["cancel_raw"])
    ident = json.loads(identity_raw)
    boot = control_status(control_raw)
    epoch = proof.get("terminal_epoch")
    require(type(epoch) is int and epoch >= 1, "Leave proof has no terminal epoch")
    require(proof.get("boot") == boot, "Leave proof boot does not match the control reply")
    layout = paired_layout(status_raw) if selected_backend(ident) == PAIRED_BACKEND else 4
    require(len(cancel_raw) == len(status_raw), "Cancel status contract does not match the terminal status")
    parsed = status(status_raw, boot, epoch, layout=layout)
    require(parsed["epoch"] == epoch, "Leave proof epoch does not match the status reply")
    require(ident.get("uid") == UID, "Leave proof identity is not the admitted target")
    require(isinstance(cancel_raw, (bytes, bytearray)), "Cancel reply missing")
    cancelled = status(cancel_raw, boot, epoch, layout=layout)
    require(cancelled["epoch"] == epoch, "Cancel epoch does not match the leave proof")
    require(cancelled["state"] not in (1, 2, 3, 4, 5), "Cancel leaves capture active")
    for word in range(72, 76):
        # RA8P1 Rev.1.30 17.2.16: DMSTS.ACT is bit 7; bit 0 is ESIF. Same word positions in v5.
        require(word * 4 < len(cancel_raw) and (cancel_raw[word * 4] & 0x80) == 0, "Capture DMA ACT still set")
    return {"boot": boot, "terminal_epoch": epoch, "classification": proof["classification"],
            "identity": ident, "proof_sha256": proof_sha, "cancel_sha256": proof["cancel_raw"]["sha256"]}


def verify_acquisition(a, candidate):
    """Re-read bound raw records; saved positive verdicts have no authority."""
    backend = selected_backend(a["identity"])
    require(a.get("schema") == SCHEMA and a.get("backend") == backend, "Wrong replacement acquisition schema")
    identity(a["identity"], candidate)
    for key, value in (("image_sha256", candidate["image"]["sha256"]),
                       ("source_commit", candidate["source_commit"]),
                       ("source_binding_hash", candidate["source_binding_hash"]),
                       ("build_receipt_sha256", candidate["build_receipt"]["sha256"])):
        require(a.get(key) == value, "Replacement capture/candidate mismatch: " + key)
    start, end = a["acquisition_unix"]
    require(all(type(t) in (int,float) and math.isfinite(t) for t in (start,end))
            and start < end <= start + 80, "Stale replacement acquisition")
    monotonic = a.get("acquisition_monotonic")
    if monotonic is not None:
        require(isinstance(monotonic, list) and len(monotonic) == 2
                and all(type(t) in (int,float) and math.isfinite(t) for t in monotonic)
                and a.get("host_time_basis") == "monotonic-elapsed-from-wall-anchor",
                "Invalid replacement monotonic acquisition clock")
        mono_start, mono_end = monotonic
        require(mono_start < mono_end and 0 <= time.monotonic()-mono_end <= 86400
                and abs((end-start)-(mono_end-mono_start)) <= 4*math.ulp(start),
                "Stale/mismatched replacement monotonic acquisition")
    else:
        require(0 <= time.time()-end <= 86400, "Stale replacement acquisition")
    opened, closed = start, end
    event = json.loads(bound(a["programming_event"]))
    require(event.get("identity") == UID and event.get("image_sha256") == a["image_sha256"]
            and event.get("readback_sha256") == a["image_sha256"] and event.get("readback_verified") is True
            and event.get("source_binding_hash") == a["source_binding_hash"]
            and (event["completed_monotonic"] <= mono_start if monotonic is not None and "completed_monotonic" in event
                 else event["completed_unix"] <= opened)
            and event.get("image_file") == candidate["image"], "Wrong replacement programming event")
    from ael.adapters.prism_bench_trial import bound_file, hex_spans
    image = bound_file(candidate["image"])
    verify_replacement_program(event, image, hex_spans(image))
    boot = control_status(bound(a["control_status"]))
    require(boot == a["boot"] == control_status(bound(a["final_control"])), "Replacement boot changed")
    require(json.loads(bound(a["final_identity"])) == a["identity"], "Replacement final identity changed")
    epoch_base = a.get("start_epoch", 0)
    require(type(epoch_base) is int and epoch_base >= 0, "Replacement epoch lineage missing")
    ready_raw = bound(a["ready"])
    ready_layout = paired_layout(ready_raw) if backend == PAIRED_BACKEND else 4
    ready = status(ready_raw, boot, epoch_base, layout=ready_layout)
    require_scope_geometry(ready, candidate)
    if epoch_base == 0:
        require(ready["state"] == ready["fault"] == ready["first_fsp_error"] == 0, "Detector not ready")
        if backend == PAIRED_BACKEND:
            verify_paired_configuration(ready, readiness=True)
        else:
            legacy.verify_direct_configuration(ready, readiness=True)
    else:
        require(ready["state"] not in (1, 2, 3, 4, 5), "Continuation was still active")
        verify_memory(ready)
    for name in ("health_before", "health_after"):
        json.loads(bound(a[name]))  # Original health evidence; no invented health verdict.
    epochs = a["epochs"]
    require(type(a.get("frames_each")) is int and 100 <= len(epochs) == a["frames_each"] <= 120,
            "Incomplete replacement campaign")
    previous = opened
    for index, row in enumerate(epochs):
        begin, finish = row["host_unix"]
        require(previous <= begin < finish <= closed and row["pattern"] == index, "Stale/reordered replacement epoch")
        previous = finish
        expect = epoch_base + index + 1
        require(row.get("epoch") == expect, "Replacement epoch lineage broke")
        status_raw = bound(row["status"])
        drained_raw = bound(row["drained_status"])
        layout = paired_layout(status_raw) if backend == PAIRED_BACKEND else 4
        s = status(status_raw, boot, expect, layout=layout)
        require_scope_geometry(s, candidate)
        final = status(drained_raw, boot, expect, layout=paired_layout(drained_raw) if backend == PAIRED_BACKEND else 4)
        require(all(final[k] == s[k] for k in s if not k.startswith("cursor_")), "Changed drained capture")
        require([final["cursor_"+n] for n in legacy.SPLIT_NAMES] + [final["cursor_split_sof"]]
                == stream_counts(s), "Incomplete replacement drain")
        verify_epoch(s, [bound(r) for r in row["streams"]], index)
    return {"raw_capture_consistent": True, "physical_qualification": False,
            "timing_qualification": "UNQUALIFIED_INPUT_CAPTURE_TIMING", "frames_each": len(epochs)}


def stream_counts(s):
    """v4 raw files are one word per edge. v5 raw files are two words per completed record.

    v6/v7 drain length is the record width times completed DMA blocks. Recovered history
    edges are not extra DMA words.
    """
    if s.get("version") in (6, 7):
        return [record_words(index) * s["words_" + name]
                for index, name in enumerate(legacy.SPLIT_NAMES)] + [s["sof_rows"] * 4]
    if s.get("version") == 5:
        return [WORDS_PER_RECORD * s["words_" + name] for name in legacy.SPLIT_NAMES] + [s["sof_rows"] * 4]
    return legacy.stream_counts(s)


def acquire(exchange, manifest, spec, out, info, *, absolute_deadline, clock=time.monotonic, sleep=time.sleep):
    """Real ARM/poll/drain/cancel route; all replies retained before decoding."""
    backend = identity(info, manifest)
    layout = 4
    count = spec.get("frames")
    require(type(count) is int and 100 <= count <= 120 and not set(spec) - {"frames", "budget_seconds", "pattern", "start_epoch"},
            "Unsupported replacement acquisition request")
    start_epoch = spec.get("start_epoch", 0)
    require(type(start_epoch) is int and 0 <= start_epoch < 100000, "Repair start epoch invalid")
    if "start_epoch" in spec:
        require(manifest.get("isolated_qualification", {}).get("repair_session"),
                "Epoch lineage requires the bound repair session")
    pattern = spec.get("pattern")
    require(pattern is None or type(pattern) is int and 0 <= pattern < 120, "Wrong replacement pattern")
    budget = spec.get("budget_seconds")
    # 70 s: v6 three-word fall records take 0.63 s per frame, so 100 frames need about 63 s
    # (Captain ruling 20 Oct 2026; the broker's 80 s and the 120 s interruption bounds are unchanged).
    require(type(budget) in (int, float) and math.isfinite(budget) and 0 < budget <= 70
            and type(absolute_deadline) in (int, float) and math.isfinite(absolute_deadline), "Unbounded replacement collector")
    deadline = min(absolute_deadline, clock() + budget)
    output = Path(out) / "replacement-loopback"
    output.mkdir(exist_ok=False)
    def save(name, raw):
        p = output / name
        with p.open("xb") as f: f.write(raw)
        return {"path": str(p.resolve()), "sha256": digest(raw)}
    def read(name, opcode, payload=b""):
        require(clock() < deadline, "Replacement capture/drain deadline; recovery reserve retained")
        raw = exchange(opcode, payload, absolute_deadline=deadline)
        row = save(name, raw)
        require(clock() < deadline, "Replacement reply exceeded capture deadline")
        return raw, row
    started = time.time(); started_mono = clock(); epochs = []; current = 0
    def host_stamp():
        # Wall-clock adjustment must not reorder real capture transactions.
        return started + (clock()-started_mono)
    initial, initial_row = read("control-status.bin", CONTROL_STATUS)
    boot = control_status(initial)
    if start_epoch > 0:
        require(type(manifest.get("resident_boot")) is int and boot == manifest["resident_boot"],
                "Fresh control boot does not match the retained repair boot")
    raw, _ = read("bind-status.bin", 0x50524202, struct.pack("<2I", 1, boot) + UID.encode())
    require(control_status(raw) == boot and struct.unpack_from("<I", raw, 8)[0] == 1,
            "Replacement fixture binding failed")
    _, health_before = read("health-before.json", HEALTH)
    ready, ready_row = read("ready.bin", legacy.STATUS, struct.pack("<2I", boot, start_epoch))
    if backend == PAIRED_BACKEND:
        layout = paired_layout(ready)
    s = status(ready, boot, start_epoch, layout=layout)
    # Fixed for the session: every later status is decoded with this same layout.
    require_scope_geometry(s, manifest)
    start_epoch = s["epoch"]
    if start_epoch == 0:
        require(s["state"] == s["fault"] == s["first_fsp_error"] == 0, "Replacement detector not ready")
        if layout in (5, 6, 7):
            verify_paired_configuration(s, readiness=True)
        else:
            legacy.verify_direct_configuration(s, readiness=True)
    else:
        require(s["state"] not in (1, 2, 3, 4, 5), "Replacement capture still active")
        verify_memory(s)
    armed = False
    leave = {}
    try:
        for index, selected in enumerate([pattern] if pattern is not None else range(count)):
            current = start_epoch + index + 1; begin = host_stamp()
            read(f"{current}-arm.bin", legacy.ARM, struct.pack("<4I", boot, current, selected, 1))
            armed = True
            for poll in range(1000):
                raw, status_row = read(f"{current}-status-{poll}.bin", legacy.STATUS, struct.pack("<2I", boot, current))
                s = status(raw, boot, current, layout=layout)
                if s["state"] in (6, 7, 8): break
                require(s["fault"] == 0, "Replacement nonterminal detector fault")
                sleep(min(.005, max(0, deadline-clock())))
            require(s["state"] in (6, 7, 8), "Replacement polling limit")
            streams = []; raw_streams = []
            for stream, total in enumerate(stream_counts(s)):
                words = []
                while len(words) < total:
                    offset = len(words); n = min(1000, total-offset)
                    raw, _ = read(f"{current}-stream{stream}-{offset}.bin", legacy.DRAIN,
                                  struct.pack("<5I", boot, current, stream, offset, n))
                    words.extend(legacy.parse_chunk(raw, boot, current, stream, offset, n, max_words=1000))
                raw = struct.pack("<" + "I" * total, *words)
                raw_streams.append(raw); streams.append(save(f"{current}-stream{stream}.u32", raw))
            raw, final_row = read(f"{current}-drained.bin", legacy.STATUS, struct.pack("<2I", boot, current))
            final = status(raw, boot, current, layout=layout)
            require(all(final[k] == s[k] for k in s if not k.startswith("cursor_")), "Capture changed while draining")
            require([final["cursor_"+n] for n in legacy.SPLIT_NAMES] + [final["cursor_split_sof"]]
                    == stream_counts(s), "Incomplete replacement drain")
            row = {"status": status_row, "drained_status": final_row, "streams": streams,
                   "pattern": selected, "epoch": current, "host_unix": [begin, host_stamp()]}
            epochs.append(row)
            save(f"{current}-index.json", json.dumps(row).encode())
            try:
                verify_epoch(s, raw_streams, selected)
            except RuntimeError as exc:
                # Only a failure after the full raw drain is a capture verification failure.
                exc.capture_verification_failed = True
                exc.fixture_epoch = current
                exc.terminal_status = final_row
                raise
        raw, final_identity = read("identity-after.json", IDENTITY)
        require(json.loads(raw) == info, "Replacement identity changed during acquisition")
        raw, final_control = read("control-after.bin", CONTROL_STATUS)
        require(control_status(raw) == boot, "Replacement reboot during acquisition")
        leave.update(identity=final_identity, control=final_control, boot=boot,
                     epoch=current, status=epochs[-1]["drained_status"], classification="complete")
        _, health_after = read("health-after.json", HEALTH)
    except BaseException as exc:
        text = str(exc)
        if any(part in text for part in (
                "identity mismatch", "identity changed", "identity absent", "Wrong native UID",
                "source identity", "Replacement reboot", "binding failed")):
            exc.identity_lost = True
            exc.capture_verification_failed = False
        elif getattr(exc, "capture_verification_failed", False):
            try:
                raw, ident_row = read("identity-leave.json", IDENTITY)
                require(json.loads(raw) == info, "Replacement identity changed during acquisition")
                raw, control_row = read("control-leave.bin", CONTROL_STATUS)
                leave_boot = control_status(raw)
                require(leave_boot == boot, "Replacement reboot during acquisition")
                leave.update(identity=ident_row, control=control_row, boot=leave_boot,
                             epoch=exc.fixture_epoch, status=exc.terminal_status,
                             classification="capture_verification_failed")
            except BaseException as ident_exc:
                exc.capture_verification_failed = False
                exc.identity_lost = True
                exc.add_note("Leave identity/control was not revalidated: " + str(ident_exc))
        failure = {"error": str(exc), "epochs": epochs, "physical_qualification": False,
                   "fixture_epoch": getattr(exc, "fixture_epoch", current),
                   "capture_verification_failed": getattr(exc, "capture_verification_failed", False)}
        secondary = None
        try:
            now = clock()
            if now >= deadline:
                failure["health_failure"] = {"outcome": "skipped", "reason": "capture/candidate deadline exhausted",
                                             "deadline": deadline, "observed_monotonic": now}
            else:
                health_deadline = min(deadline, now + 1.0)
                raw = exchange(HEALTH, absolute_deadline=health_deadline)
                row = save("health-failure.json", raw)
                failure["health_failure"] = {"outcome": "retained", "raw": row,
                                             "deadline": health_deadline, "observation_only": True}
                require(clock() < health_deadline, "Failure health reply exceeded capture deadline")
        except BaseException as health_error:
            secondary = health_error
            detail = {"error": str(health_error), "exception_type": type(health_error).__name__}
            failure["health_failure_error"] = detail
            exc.add_note("Failure health observation failed: " + str(health_error))
            try:
                save("health-failure-error.json", json.dumps(detail).encode())
            except BaseException as save_error:
                exc.add_note("Failure health error could not be retained: " + str(save_error))
        try:
            save("failure.json", json.dumps(failure).encode())
        except BaseException as save_error:
            exc.add_note("Capture failure record could not be retained: " + str(save_error))
            if secondary is None: secondary = save_error
        if secondary is not None:
            raise exc from secondary
        raise
    finally:
        if current:
            # Stop only fixture activity. Firmware CANCEL must resume normal music.
            primary = sys.exc_info()[1]
            cancel_row = None
            try:
                require(clock() < absolute_deadline, "No candidate budget remains for cancellation")
                cancel_row = save("cancel.bin", exchange(legacy.CANCEL, struct.pack("<2I", boot, current),
                                            absolute_deadline=absolute_deadline))
            except Exception as exc:
                save("cancel-error.json", json.dumps({"error": str(exc)}).encode())
                if primary is None:
                    exc.collector_quiesced = False
                    raise
                primary.collector_quiesced = False
            if (cancel_row is not None and not leave.get("classification") and primary is not None
                    and not getattr(primary, "identity_lost", False)):
                # A stop before completion (e.g. the collector budget, 20 Oct 2026): after a clean
                # CANCEL, re-read identity and control so the next guarded deploy can qualify the
                # board. The cancel reply is the terminal status; the same idle predicates apply.
                try:
                    require(clock() < absolute_deadline, "No candidate budget remains for leave reads")
                    ident_raw = exchange(IDENTITY, absolute_deadline=absolute_deadline)
                    ident_row = save("identity-leave.json", ident_raw)
                    require(json.loads(ident_raw) == info, "Replacement identity changed during acquisition")
                    control_raw = exchange(CONTROL_STATUS, absolute_deadline=absolute_deadline)
                    control_row = save("control-leave.bin", control_raw)
                    require(control_status(control_raw) == boot, "Replacement reboot during acquisition")
                    leave.update(identity=ident_row, control=control_row, boot=boot, epoch=current,
                                 status=cancel_row, classification="cancelled_after_stop")
                except BaseException as leave_error:
                    primary.add_note("Leave identity/control after the stop was not revalidated: " + str(leave_error))
            if cancel_row is not None and leave.get("classification"):
                proof = {"schema": LEAVE_SCHEMA, "classification": leave["classification"],
                         "boot": leave["boot"], "terminal_epoch": leave["epoch"],
                         "identity_raw": leave["identity"], "control_raw": leave["control"],
                         "terminal_status_raw": leave["status"], "cancel_raw": cancel_row}
                try:
                    proof_row = save("leave-proof.json", json.dumps(proof).encode())
                    if primary is None:
                        leave["proof"] = proof_row
                    else:
                        primary.leave_proof = proof_row
                except BaseException as save_error:
                    if primary is None:
                        raise
                    primary.add_note("Leave proof could not be retained: " + str(save_error))
    ended_mono = clock()
    result = {"schema": SCHEMA, "backend": backend, "identity": info, "boot": boot,
              "start_epoch": start_epoch,
              "control_status": initial_row, "ready": ready_row, "epochs": epochs,
              "final_identity": final_identity, "final_control": final_control,
              "health_before": health_before, "health_after": health_after,
              "frames_each": len(epochs), "acquisition_unix": [started, started+(ended_mono-started_mono)],
              "acquisition_monotonic": [started_mono, ended_mono],
              "host_time_basis": "monotonic-elapsed-from-wall-anchor",
              "image_sha256": manifest["image"]["sha256"], "source_commit": manifest["source_commit"],
              "source_binding_hash": manifest["source_binding_hash"], "build_receipt_sha256": manifest["build_receipt"]["sha256"],
              "programming_event": manifest["isolated_programming_event"],
              "leave_proof": leave.get("proof"),
              "physical_qualification": False, "timing_qualification": "UNQUALIFIED_INPUT_CAPTURE_TIMING"}
    save("acquisition.json", json.dumps(result, indent=2).encode())
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        receipt = json.loads(bound(manifest["build_receipt"]))
        validate_profile(manifest, receipt)
        require(receipt.get("source_profile_sha256") == manifest["source_binding_hash"], "Wrong receipt source")
        image = bound(manifest["image"])
        require(receipt.get("artefacts", {}).get("titan-native.hex") == digest(image), "Wrong receipt image")
        result = verify_acquisition(json.loads(args.capture.read_text()), manifest) if args.capture else {
            "profile": "titan-replacement", "backend": BACKEND, "paired_backend": PAIRED_BACKEND,
            "bits_each": BITS, "bytes_each": 960, "bits_by_status_version": BITS_BY_VERSION,
            "firmware_dependency": "Final candidate binding and runtime readiness required; this offline check does not establish fixture capability",
            "hardware_access": False, "physical_qualification": False}
        print(json.dumps(result, indent=2)); return 0
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "hardware_access": False})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
