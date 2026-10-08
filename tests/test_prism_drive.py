import pytest
from ael.prism_drive import MediaClock, due_hops


def test_speaker_sample_extrapolates_from_render_report_and_subtracts_latency():
    c = MediaClock(48000)
    assert c.speaker_sample(10**9) is None
    c.update({'event': 'clock', 'render_uptime_ns': 2_000_000_000, 'render_sample': 96000, 'latency_s': 0.1})
    assert c.speaker_sample(2_000_000_000) == pytest.approx(96000 - 4800)
    assert c.speaker_sample(2_500_000_000) == pytest.approx(96000 + 24000 - 4800)
    c.extra_s = 0.01
    assert c.speaker_sample(2_000_000_000) == pytest.approx(96000 - 4800 - 480)


def test_negative_prerolls_and_start_reports_are_ignored():
    c = MediaClock(48000)
    c.update({'event': 'clock', 'render_uptime_ns': 1, 'render_sample': -1116, 'latency_s': 0.1})
    c.update({'event': 'start', 'render_uptime_ns': 1, 'render_sample': 5, 'latency_s': 0.1})
    assert c.speaker_sample(10) is None


def test_due_hops_only_releases_hops_whose_window_has_fully_played():
    # 48000 Hz file: one 64-sample hop at 12800 Hz is 240 file samples
    assert list(due_hops(None, 48000, 0, 10)) == []
    assert list(due_hops(239, 48000, 0, 10)) == []
    assert list(due_hops(240, 48000, 0, 10)) == [0]
    assert list(due_hops(240 * 5 + 1, 48000, 2, 10)) == [2, 3, 4]
    assert list(due_hops(240 * 50, 48000, 7, 10)) == [7, 8, 9]
    assert list(due_hops(240 * 3, 48000, 5, 10)) == []  # clock never rewinds sent hops
