"""Synthetic v7 epochs. Generated edges are not device observations.

Status protocol v7 (21 Oct 2026, Phase 1) is the v6 field map with 80-pixel lanes:
3,840 bits (480 bytes) per lane, 7,680 hardware edges per lane, the same 7,712-block
capacity and the same 2/3-word rise/fall history records. Geometry comes from the
version word; v5 and v6 keep 7,680 bits.
"""
import copy
import json
import struct
import time

import pytest

from ael import titan_loopback as loop
from ael import titan_replacement_observer as observer
from ael.titan_waveform import UID, diagnostic_payload, digest
from test_titan_observer_v6 import ROW, model_records, packed
from test_titan_paired_capture import fixture as v5_fixture
from test_titan_replacement_observer import info, manifest, raw_streams

PATTERN = 13
MASK = 0xffffffff


def xorshift_frame(frame, lane, size):
    """Second, independent pattern-set-v1 writer (Kx replacement_fixture_capture.h pattern()),
    truncated at `size` bytes with the boundary marker on byte 0 bit 7 and the LAST byte bit 0."""
    x = 0x9e3779b9 ^ ((frame * 0x85ebca6b) & MASK) ^ ((lane * 0xc2b2ae35) & MASK)
    out = bytearray(size)
    for i in range(size):
        x ^= (x << 13) & MASK
        x ^= x >> 17
        x ^= (x << 5) & MASK
        out[i] = 0 if frame == 0 else 255 if frame == 1 else (0x55 if lane else 0xaa) if frame == 2 else x & 255
    if frame >= 3:
        edge = (frame - 3) % 4
        out[0] = (out[0] & 0x7f) | ((edge >> 1) << 7)
        out[size - 1] = (out[size - 1] & 0xfe) | (edge & 1)
    return bytes(out)


def lane_edges(status, pattern, bits):
    """Rise/fall ticks for both lanes, built from the payload bytes of a `bits`-bit frame."""
    streams = []
    for lane in (0, 1):
        prefix = "b_" if lane else ""
        first = status[prefix + "stimulus_tick"]
        payload = xorshift_frame(pattern, lane, bits // 8)
        levels = "".join(f"{byte:08b}" for byte in payload)
        rises = [(first + i * 390) & MASK for i in range(bits)]
        falls = [(t + (198 if bit == "1" else 78)) & MASK for t, bit in zip(rises, levels)]
        streams.extend([rises, falls])
        status[prefix + "trailing_begin"] = (falls[-1] + 1) & MASK
        status[prefix + "trailing_end"] = (falls[-1] + 120000) & MASK
        status[prefix + "capture_end_tick"] = (falls[-1] + 120001) & MASK
    return streams


def build(version=7, bits=3840, pattern=PATTERN, skipped=None):
    """v6/v7 status plus history records. `bits` is the geometry actually emitted, so a
    status whose version disagrees with its edge count can be planted."""
    skipped = skipped or (set(), set(), set(), set())
    status, _pairs, sof, _streams = v5_fixture(pattern)
    status.update(version=version, split_capability=4, gtber=observer.V6_GTBER, gpt12_gtber=observer.V6_GTBER,
                  words_per_record=observer.RISE_RECORD_WORDS, reserved_v5=observer.FALL_RECORD_WORDS,
                  reserved_137=MASK, reserved_138=MASK, reserved_143=0)
    streams = lane_edges(status, pattern, bits)
    records, recovered = [], []
    for index, edges in enumerate(streams):
        width = observer.record_words(index)
        row = model_records(edges, width, skipped[index])
        _ticks, count = observer.recover_history(row, width)
        records.append(row)
        recovered.append(count)
        name = loop.SPLIT_NAMES[index]
        address = 0x22000000 + index * ROW
        status.update({"words_" + name: len(row), "remaining_" + name: observer.CAPACITY - len(row),
                       "dmcrb_" + name: observer.CAPACITY - len(row),
                       "dmcra_" + name: observer.record_dmcra(index), "dmofr_" + name: 8,
                       "buffer_" + name: address, "destination_" + name: address + 4 * width * len(row),
                       "reserved_%d" % (139 + index): count})
    status["words_a"] = status["words_a_rise"] + status["words_a_fall"]
    status["words_b"] = status["words_b_rise"] + status["words_b_fall"]
    status["remaining_a"] = status["remaining_a_rise"] + status["remaining_a_fall"]
    status["remaining_b"] = status["remaining_b_rise"] + status["remaining_b_fall"]
    status["edges_a"] = status["edges_b"] = 2 * bits
    return status, records, sof, streams, recovered


def verify(status, records, sof, *, layout=None):
    parsed = observer.status(packed(status), status["boot"], status["epoch"], layout=layout)
    flat = [[word for record in stream for word in record] for stream in records]
    return observer.verify_epoch(parsed, raw_streams(flat, sof), status["pattern"])


def idle(status):
    status = copy.deepcopy(status)
    status.update(epoch=0, state=0, fault=0, words_a=0, words_b=0, edges_a=0, edges_b=0,
                  gtber=0, gpt12_gtber=0, gpt7_gtpr=0xfffffffe, gpt12_gtpr=0xfffffffe)
    for index, name in enumerate(loop.SPLIT_NAMES):
        status.update({"words_" + name: 0, "remaining_" + name: observer.CAPACITY,
                       "dmcrb_" + name: observer.CAPACITY, "destination_" + name: status["buffer_" + name],
                       "reserved_%d" % (139 + index): 0})
    return status


def test_geometry_is_keyed_by_the_status_version_word():
    assert observer.BITS_BY_VERSION == {4: 7680, 5: 7680, 6: 7680, 7: 3840}
    assert observer.frame_bits({"version": 7}) == 3840
    assert observer.frame_bits({"version": 6}) == observer.frame_bits({"version": 5}) == 7680
    with pytest.raises(RuntimeError, match="No frame geometry"):
        observer.frame_bits({"version": 8})
    # The loopback's own history geometry must never drift from the observer's.
    assert loop.HISTORY_PULSES == {v: observer.BITS_BY_VERSION[v] for v in (6, 7)}


@pytest.mark.parametrize("frame", [3, 4, 5, 6, 13, 14])
def test_480_byte_pattern_is_bit_exact_and_marks_byte_479(frame):
    short = xorshift_frame(frame, 1, 480)
    assert diagnostic_payload(frame, 1, bytes_per_lane=480) == short
    full = xorshift_frame(frame, 1, 960)
    # Same xorshift stream; only the trailing marker moves from byte 959 to byte 479.
    assert short[:479] == full[:479] and short[479] >> 1 == full[479] >> 1
    assert short[479] & 1 == ((frame - 3) % 4) & 1 and short[0] >> 7 == ((frame - 3) % 4) >> 1


@pytest.mark.parametrize("pattern", [13, 14])
def test_clean_v7_epoch_rebuilds_3840_edges_per_stream(pattern):
    status, records, sof, streams, recovered = build(pattern=pattern)
    assert recovered == [0, 0, 0, 0] and all(len(edges) == 3840 for edges in streams)
    parsed = observer.status(packed(status), status["boot"], status["epoch"])
    assert parsed["version"] == 7 and observer.paired_layout(packed(status)) == 7
    assert observer.stream_counts(parsed) == [2 * 3840, 3 * 3840, 2 * 3840, 3 * 3840, status["sof_rows"] * 4]
    result = verify(status, records, sof)
    assert result["bits_each"] == 3840 and result["physical_qualification"] is False
    assert result["recovered_edges"] == [0, 0, 0, 0]
    assert result["payload_sha256"] == [digest(xorshift_frame(pattern, lane, 480)) for lane in (0, 1)]


def test_v7_coalesced_falls_and_duplicate_fields_are_still_recovered():
    status, records, sof, streams, recovered = build(skipped=(set(), {1770}, set(), {3001, 3002}))
    assert recovered == [0, 1, 0, 2]
    for index in (1, 3):
        ticks, _count = observer.recover_history(records[index], 3)
        assert ticks == streams[index]
    parsed = observer.status(packed(status), status["boot"], status["epoch"], layout=7)
    assert parsed["duplicates_a_fall"] == 0 and parsed["history_unresolved_a_fall"] is False
    assert verify(status, records, sof)["recovered_edges"] == [0, 1, 0, 2]


def test_v7_device_flagged_stream_is_decoded_by_the_host():
    status, records, sof, _streams, _recovered = build(skipped=(set(), {1770}, set(), set()))
    status["reserved_140"] = 1 << 31  # history_unresolved, no device count
    parsed = observer.status(packed(status), status["boot"], status["epoch"], layout=7)
    assert parsed["history_unresolved_a_fall"] is True and parsed["recovered_a_fall"] == 0
    assert verify(status, records, sof)["recovered_edges"] == [0, 1, 0, 0]


def test_v7_status_carrying_7680_bit_lanes_is_refused():
    status, records, sof, _streams, _recovered = build(version=7, bits=7680)
    with pytest.raises(RuntimeError, match="not 3840"):
        verify(status, records, sof)
    parsed = observer.status(packed(status), status["boot"], status["epoch"], layout=7)
    with pytest.raises(RuntimeError, match="not 3840"):
        observer.verify_paired_configuration(parsed, complete=True)


def test_v6_status_carrying_3840_bit_lanes_is_refused():
    status, records, sof, _streams, _recovered = build(version=6, bits=3840)
    with pytest.raises(RuntimeError, match="not 7680"):
        verify(status, records, sof)


def test_v7_edges_alone_at_the_old_geometry_are_refused():
    status, records, sof, _streams, _recovered = build()
    status["edges_a"] = status["edges_b"] = 15360
    with pytest.raises(RuntimeError, match="hardware edge count is not 7680"):
        verify(status, records, sof)


def test_v7_payload_from_the_960_byte_frame_is_refused():
    status, records, sof, _streams, _recovered = build()
    parsed = observer.status(packed(status), status["boot"], status["epoch"], layout=7)
    flat = [[word for record in stream for word in record] for stream in records]
    rebuilt = [observer.recover_history(records[i], observer.record_words(i))[0] for i in range(4)]
    single = [struct.pack("<3840I", *ticks) for ticks in rebuilt]
    with pytest.raises(RuntimeError, match="Pulse count does not match"):
        loop.verify_split_epoch(parsed, single, raw_streams(flat, sof)[4], pattern=PATTERN, pulses=7680)


def test_v7_length_and_layout_word_are_as_strict_as_v6():
    status, _records, _sof, _streams, _recovered = build()
    raw = packed(status)
    with pytest.raises(RuntimeError, match="v7 status requires 192 words"):
        observer.status(raw[:640], status["boot"], status["epoch"], layout=7)
    bad = bytearray(raw)
    struct.pack_into("<I", bad, 107 * 4, 3)
    with pytest.raises(RuntimeError, match="Unknown replacement v7 layout"):
        observer.status(bytes(bad), status["boot"], status["epoch"])
    with pytest.raises(RuntimeError, match="Stale replacement version"):
        observer.status(raw, status["boot"], status["epoch"], layout=6)


def test_idle_v7_bootstrap_checks_dma_geometry():
    # Same call form as deploy_admission.py's restarted-candidate bootstrap check.
    status, _records, _sof, _streams, _recovered = build()
    raw_status = packed(idle(status))
    parsed = observer.status(raw_status, status["boot"], 0, layout=observer.paired_layout(raw_status))
    assert parsed["version"] == 7
    observer.verify_paired_configuration(parsed, readiness=True)
    parsed["dmcrb_b_fall"] = 7680
    with pytest.raises(RuntimeError, match="Ready DMCRB"):
        observer.verify_paired_configuration(parsed, readiness=True)


class V7Detector:
    """Fake fixture over the actual collector route. Generated data, not a device."""

    def __init__(self):
        self.s, self.records, self.sof, _, _ = build()
        self.calls = []
        self.drained = False

    def flat(self):
        return [[w for r in stream for w in r] for stream in self.records] + [sum(self.sof, [])]

    def drained_status(self):
        s = copy.deepcopy(self.s)
        for index, name in enumerate(loop.SPLIT_NAMES):
            s["cursor_" + name] = observer.record_words(index) * s["words_" + name]
        s["cursor_split_sof"] = len(self.sof) * 4
        return s

    def exchange(self, opcode, payload=b"", *, absolute_deadline=None):
        self.calls.append(opcode)
        if opcode == observer.IDENTITY:
            identity = info()
            identity["capabilities"]["isolated_raw_capture"] = observer.PAIRED_BACKEND
            return json.dumps(identity).encode()
        if opcode in (observer.CONTROL_STATUS, 0x50524202):
            return struct.pack("<4I", 1, 7, int(opcode == 0x50524202), 1) + UID.encode() + bytes(64)
        if opcode == observer.HEALTH:
            return b'{"host_mock":true}'
        if opcode == loop.ARM:
            _boot, epoch, pattern, _exclusion = struct.unpack("<4I", payload)
            self.s, self.records, self.sof, _, _ = build(pattern=pattern)
            self.s["epoch"] = epoch
            self.drained = False
            return packed(self.s)
        if opcode == loop.STATUS:
            _boot, epoch = struct.unpack("<2I", payload)
            if epoch == 0:
                return packed(idle(self.s))
            return packed(self.drained_status() if self.drained else self.s)
        if opcode == loop.DRAIN:
            _boot, _epoch, stream, offset, count = struct.unpack("<5I", payload)
            words = self.flat()[stream][offset:offset + count]
            if stream == 4:
                self.drained = True
            return payload + struct.pack("<" + "I" * len(words), *words)
        if opcode == loop.CANCEL:
            return packed(self.drained_status())
        raise AssertionError(hex(opcode))


def paired_route():
    i, m = info(), manifest()
    i["capabilities"]["isolated_raw_capture"] = observer.PAIRED_BACKEND
    m["isolated_qualification"]["backend"] = observer.PAIRED_BACKEND
    m["isolated_qualification"]["bits_each"] = 3840  # titan_isolated scope for a v7 source
    return i, m


def test_actual_collector_drains_v7_and_revalidates_the_leave_proof(tmp_path):
    d = V7Detector()
    i, m = paired_route()
    result = observer.acquire(d.exchange, m, dict(frames=100, pattern=PATTERN, budget_seconds=60),
                              tmp_path, i, absolute_deadline=time.monotonic() + 60)
    assert d.calls.count(loop.ARM) == 1 and d.calls[-1] == loop.CANCEL
    sizes = [__import__("pathlib").Path(r["path"]).stat().st_size for r in result["epochs"][0]["streams"][:4]]
    assert sizes == [4 * 2 * 3840, 4 * 3 * 3840, 4 * 2 * 3840, 4 * 3 * 3840]
    proof = observer.revalidate_leave_proof(result["leave_proof"])
    assert proof["classification"] == "complete" and proof["terminal_epoch"] == 1


def test_v7_cancelled_stop_writes_a_revalidated_leave_proof(tmp_path):
    d = V7Detector()
    i, m = paired_route()
    now = [0.]

    def exchange(op, payload=b"", *, absolute_deadline=None):
        raw = d.exchange(op, payload)
        if op == loop.DRAIN:
            now[0] = 61
        return raw
    with pytest.raises(RuntimeError, match="deadline"):
        observer.acquire(exchange, m, dict(frames=100, pattern=PATTERN, budget_seconds=60), tmp_path, i,
                         absolute_deadline=80, clock=lambda: now[0])
    proof = observer.revalidate_leave_proof(tmp_path / "replacement-loopback" / "leave-proof.json")
    assert proof["classification"] == "cancelled_after_stop" and proof["terminal_epoch"] == 1


@pytest.mark.parametrize("declared", [None, 7680])
def test_v7_status_in_a_7680_bit_scope_is_refused_before_arming(tmp_path, declared):
    d = V7Detector()
    i, m = paired_route()
    if declared is None:
        del m["isolated_qualification"]["bits_each"]
    else:
        m["isolated_qualification"]["bits_each"] = declared
    with pytest.raises(RuntimeError, match="Status geometry disagrees with scope: v7 status has 3840"):
        observer.acquire(d.exchange, m, dict(frames=100, pattern=PATTERN, budget_seconds=60),
                         tmp_path, i, absolute_deadline=time.monotonic() + 60)
    assert loop.ARM not in d.calls


def test_v6_status_in_a_3840_bit_scope_is_refused():
    status, _records, _sof, _streams, _recovered = build(version=6, bits=7680)
    parsed = observer.status(packed(status), status["boot"], status["epoch"])
    with pytest.raises(RuntimeError, match="Status geometry disagrees with scope: v6 status has 7680"):
        observer.require_scope_geometry(parsed, {"isolated_qualification": {"bits_each": 3840}})
    observer.require_scope_geometry(parsed, {"isolated_qualification": {}})
