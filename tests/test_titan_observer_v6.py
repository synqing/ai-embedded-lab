"""Synthetic v6 epochs. Generated edges are not device observations.

Record bytes follow replacement_fixture_test.cpp::model(): each edge shifts the
live/history registers, and a skipped edge stays in the registers until the next
DMA block. Edge times are the pattern-set-v1 390-tick rises and 78/198 highs,
so the unchanged pulse oracle can accept a rebuilt stream. The C++ unit model
alternates those highs by sample index and does not consult the payload oracle.
"""
import struct
from pathlib import Path

import pytest

from ael import titan_loopback as loop
from ael import titan_replacement_observer as observer
from test_titan_paired_capture import fixture as v5_fixture
from test_titan_paired_capture import verify as verify_v5
from test_titan_replacement_observer import raw_streams

ADMISSION = Path("/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts/deploy_admission.py")
ROW = 0x17000


def model_records(edges, width, skipped):
    reg = [0xffffffff, 0xffffffff, 0xffffffff]
    records = []
    for index, edge in enumerate(edges):
        reg = [edge & 0xffffffff, reg[0], reg[1]]
        if index in skipped:
            continue
        records.append(reg[:width])
    return records


def packed(s):
    words = ([s[k] for k in loop.STATUS_FIELDS] + [0] + [s[k] for k in loop.DIRECT_FIELDS]
             + [s[k] for k in observer.EXTENSION] + [0] + [s[k] for k in observer.V5_EXTENSION])
    assert len(words) == 192
    return struct.pack("<192I", *words)


def build(skipped=None, corrupt=None):
    skipped = skipped or (set(), set(), set(), set())
    status, _pairs, sof, streams = v5_fixture(13)
    status.update(version=6, split_capability=4, gtber=observer.V6_GTBER, gpt12_gtber=observer.V6_GTBER,
                  words_per_record=observer.RISE_RECORD_WORDS, reserved_v5=observer.FALL_RECORD_WORDS,
                  reserved_137=0xffffffff, reserved_138=0xffffffff, reserved_143=0)
    records = []
    recovered = []
    for index, edges in enumerate(streams):
        width = observer.record_words(index)
        row = model_records(edges, width, skipped[index])
        _ticks, count = observer.recover_history(row, width)
        records.append(row)
        recovered.append(count)
        address = 0x22000000 + index * ROW
        status.update({"words_" + loop.SPLIT_NAMES[index]: len(row),
                       "remaining_" + loop.SPLIT_NAMES[index]: observer.CAPACITY - len(row),
                       "dmcrb_" + loop.SPLIT_NAMES[index]: observer.CAPACITY - len(row),
                       "dmcra_" + loop.SPLIT_NAMES[index]: observer.record_dmcra(index),
                       "dmofr_" + loop.SPLIT_NAMES[index]: 8,
                       "buffer_" + loop.SPLIT_NAMES[index]: address,
                       "destination_" + loop.SPLIT_NAMES[index]: address + 4 * width * len(row),
                       "reserved_%d" % (139 + index): count})
    status["words_a"] = status["words_a_rise"] + status["words_a_fall"]
    status["words_b"] = status["words_b_rise"] + status["words_b_fall"]
    status["remaining_a"] = status["remaining_a_rise"] + status["remaining_a_fall"]
    status["remaining_b"] = status["remaining_b_rise"] + status["remaining_b_fall"]
    status["edges_a"] = status["edges_b"] = 15360
    if corrupt:
        corrupt(records)
    return status, records, sof, streams, recovered


def verify(status, records, sof):
    parsed = observer.status(packed(status), status["boot"], status["epoch"], layout=6)
    flat = [[word for record in stream for word in record] for stream in records]
    return observer.verify_epoch(parsed, raw_streams(flat, sof), status["pattern"])


def test_cpp_recover_history_vectors():
    one = [(10, 0, 0), (20, 10, 0), (30, 25, 20)]
    ticks, count = observer.recover_history(one, 3)
    assert count == 1 and ticks == [10, 20, 25, 30]
    two = [(10, 0, 0), (20, 10, 0), (40, 35, 30)]
    ticks, count = observer.recover_history(two, 3)
    assert count == 2 and ticks == [10, 20, 30, 35, 40]
    with pytest.raises(RuntimeError, match="Inconsistent history chain"):
        observer.recover_history([(10, 0), (20, 25)], 2)


def test_torn_reads_lose_nothing_and_match_the_firmware_rule():
    # Fall block (x,w,v): next capture after the first read gives (x,x,w), after the second (x,w,w).
    after_b = [(10, 0, 0), (20, 10, 0), (30, 30, 20), (40, 30, 20)]
    assert observer.recover_history(after_b, 3) == ([10, 20, 30, 40], 0)
    after_e = [(10, 0, 0), (20, 10, 0), (30, 20, 20), (40, 30, 20)]
    assert observer.recover_history(after_e, 3) == ([10, 20, 30, 40], 0)
    rise = [(10, 0), (20, 10), (30, 30), (40, 30)]
    assert observer.recover_history(rise, 2) == ([10, 20, 30, 40], 0)
    # One coalesced fall (25) plus a torn read: (30,25,20) read as (30,30,25).
    coalesced = [(10, 0, 0), (20, 10, 0), (30, 30, 25), (40, 30, 25)]
    assert observer.recover_history(coalesced, 3) == ([10, 20, 25, 30, 40], 1)


def test_torn_read_does_not_hide_a_genuine_chain_break():
    with pytest.raises(RuntimeError, match="Inconsistent history chain"):
        observer.recover_history([(10, 0, 0), (20, 10, 0), (30, 30, 5)], 3)
    with pytest.raises(RuntimeError, match="Inconsistent history chain"):
        observer.recover_history([(10, 0, 0), (20, 10, 0), (30, 20, 20), (40, 30, 7)], 3)


def test_clean_v6_epoch_rebuilds_every_edge():
    status, records, sof, streams, recovered = build()
    assert recovered == [0, 0, 0, 0]
    for index, edges in enumerate(streams):
        ticks, count = observer.recover_history(records[index], observer.record_words(index))
        assert ticks == edges and count == 0
    result = verify(status, records, sof)
    assert result["recovered_edges"] == [0, 0, 0, 0]
    assert result["bits_each"] == 7680 and result["physical_qualification"] is False


def test_one_coalesced_fall_is_recovered_and_accepted():
    skipped = (set(), {3770}, set(), set())
    status, records, sof, streams, recovered = build(skipped)
    assert recovered == [0, 1, 0, 0]
    ticks, count = observer.recover_history(records[1], 3)
    assert count == 1 and ticks == streams[1]
    result = verify(status, records, sof)
    assert result["recovered_edges"] == [0, 1, 0, 0]
    assert result["bits_each"] == 7680


def test_two_consecutive_coalesced_falls_are_recovered_and_accepted():
    skipped = (set(), {5173, 5174}, set(), set())
    status, records, sof, streams, recovered = build(skipped)
    assert recovered == [0, 2, 0, 0]
    ticks, count = observer.recover_history(records[1], 3)
    assert count == 2 and ticks == streams[1]
    result = verify(status, records, sof)
    assert result["recovered_edges"] == [0, 2, 0, 0]


def test_three_consecutive_coalesced_falls_are_rejected():
    skipped = (set(), {100, 101, 102}, set(), set())
    status, records, sof, _streams, recovered = build(skipped)
    assert recovered[1] == 2
    ticks, count = observer.recover_history(records[1], 3)
    assert count == 2 and len(ticks) == 7679
    with pytest.raises(RuntimeError, match="not 7680"):
        verify(status, records, sof)


def test_host_firmware_recovered_count_mismatch_is_rejected():
    skipped = (set(), {3770}, set(), set())
    status, records, sof, _streams, recovered = build(skipped)
    assert recovered[1] == 1
    status["reserved_140"] = 0
    with pytest.raises(RuntimeError, match="recovered-count mismatch"):
        verify(status, records, sof)


def test_broken_second_history_chain_is_rejected():
    def corrupt(records):
        records[3][3000][2] ^= 4
    status, records, sof, _streams, _recovered = build(corrupt=corrupt)
    with pytest.raises(RuntimeError, match="Inconsistent history chain"):
        verify(status, records, sof)


def test_history_older_than_previous_live_is_rejected():
    def corrupt(records):
        records[1][3000][1] = (records[1][3000][1] - 1000) & 0xffffffff
    status, records, sof, _streams, _recovered = build(corrupt=corrupt)
    with pytest.raises(RuntimeError, match="Inconsistent history chain"):
        verify(status, records, sof)


@pytest.mark.parametrize("field,value", [
    ("gtber", 0x50000),
    ("gpt12_gtber", 0),
    ("dmcra_a_rise", 0x00030003),
    ("dmcra_a_fall", 0x00020002),
])
def test_wrong_gtber_or_dmcra_is_rejected(field, value):
    status, records, sof, _streams, _recovered = build()
    status[field] = value
    with pytest.raises(RuntimeError):
        verify(status, records, sof)


def test_v5_path_is_unchanged():
    status, pairs, sof, streams = v5_fixture()
    result = verify_v5(status, pairs, sof)
    assert result["bits_each"] == 7680 and result["physical_qualification"] is False
    assert "recovered_edges" not in result
    for index in range(4):
        assert [pairs[index][word] for word in result["canonical_raw_word_indices"][index]] == streams[index]
    parsed = observer.status(packed(status), status["boot"], status["epoch"])
    assert parsed["version"] == 5 and parsed["split_capability"] == 3


def test_paired_layout_reads_the_version_word_and_rejects_anything_else():
    v6_status, _records, _sof, _streams, _recovered = build()
    v5_status, _pairs, _sof, _streams = v5_fixture()
    assert observer.paired_layout(packed(v6_status)) == 6
    assert observer.paired_layout(packed(v5_status)) == 5
    v6 = observer.status(packed(v6_status), v6_status["boot"], v6_status["epoch"])
    assert v6["version"] == 6 and v6["recovered_a_fall"] == 0
    assert v6["rise_record_words"] == 2 and v6["fall_record_words"] == 3
    with pytest.raises(RuntimeError, match="not 5, 6 or 7"):
        observer.paired_layout(struct.pack("<I", 4))
    # 7 is accepted since the 21 Oct 2026 v7 contract (test_titan_observer_v7.py); 8 is not.
    with pytest.raises(RuntimeError, match="not 5, 6 or 7"):
        observer.paired_layout(struct.pack("<I", 8))


def test_idle_v6_bootstrap_checks_dma_geometry_without_requiring_open_gtber():
    status, _records, _sof, _streams, _recovered = build()
    status.update(epoch=0, state=0, fault=0, words_a=0, words_b=0, edges_a=0, edges_b=0,
                  gtber=0, gpt12_gtber=0, gpt7_gtpr=0xfffffffe, gpt12_gtpr=0xfffffffe)
    for index, name in enumerate(loop.SPLIT_NAMES):
        status.update({"words_" + name: 0, "remaining_" + name: observer.CAPACITY,
                       "dmcrb_" + name: observer.CAPACITY,
                       "destination_" + name: status["buffer_" + name],
                       "reserved_%d" % (139 + index): 0})
    parsed = observer.status(packed(status), status["boot"], 0, layout=6)
    observer.verify_paired_configuration(parsed, readiness=True)
    parsed["dmcra_a_fall"] = 0x00020002
    with pytest.raises(RuntimeError, match="DMCRA"):
        observer.verify_paired_configuration(parsed, readiness=True)


def test_admission_selects_layout_from_the_version_word():
    text = ADMISSION.read_text()
    assert "layout=observer.paired_layout(raw_status) if paired else 4" in text
    assert "layout=5 if paired else 4" not in text


def test_duplicate_block_carries_no_edge():
    # (30,25) recovers 25; the identical next block re-read the same registers.
    records = [(10, 0), (20, 10), (30, 25), (30, 25), (40, 30)]
    assert observer.recover_history(records, 2, with_duplicates=True) == ([10, 20, 25, 30, 40], 1, 1)
    assert observer.recover_history(records, 2) == ([10, 20, 25, 30, 40], 1)


def test_real_v6c_frame6_lane_b_rises_rebuild_completely():
    import pathlib
    base = pathlib.Path("/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/"
                        "_scratch/led-timing-resolution-20261020/v6c-capture-211641/replacement-loopback")
    if not base.exists():
        pytest.skip("retained v6c capture not present on this machine")
    for stream, width, rec, dup in ((2, 2, 1, 1), (3, 3, 5, 0)):
        raw = struct.unpack("<%dI" % (len((base / f"6-stream{stream}.u32").read_bytes()) // 4),
                            (base / f"6-stream{stream}.u32").read_bytes())
        records = [raw[i:i + width] for i in range(0, len(raw), width)]
        ticks, count, dups = observer.recover_history(records, width, with_duplicates=True)
        assert (len(ticks), count, dups) == (7680, rec, dup)
        assert ticks == sorted(ticks)


def test_device_flagged_stream_is_decoded_by_the_host_and_still_strict():
    flagged = (1 << 31)
    raw = struct.pack("<192I", *([0] * 139 + [flagged, 0, 0, 0] + [0] * 49))
    words = struct.unpack("<192I", raw)
    assert bool(words[139] >> 31) and (words[139] & 0xffff) == 0
    with pytest.raises(RuntimeError, match="Inconsistent history chain"):
        observer.recover_history([(10, 0), (20, 10), (20, 5)], 2)
