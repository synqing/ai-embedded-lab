"""Bounded Titan external-loopback acquisition over the existing CDC owner.

Raw GPT capture timestamps and independent edge counts are the observations.
Pattern bytes are only an independent comparison oracle. Separate epochs never
acquire invented timestamps between them. No function in this module opens a
port, programs a target, or asserts that a fixture is physically isolated.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys
import time

from ael.titan_waveform import REQUIREMENTS, UID, bound, diagnostic_payload, digest, require

BACKEND = "titan-gpt7-external-loopback-v1"
SPLIT_BACKEND = "titan-split-edge-loopback-v2"
DIRECT_BACKEND = "titan-direct-gpt7-gpt12-loopback-v3"
ARM, STATUS, DRAIN, CANCEL = range(0x50524601, 0x50524605)
CAPACITY, EDGE_COUNT, MIN_SOF_ROWS = 7744, 7680, 128
USB_SOURCE = {
    "url": "https://www.usb.org/sites/default/files/usb_20_20250603.zip",
    "member": "usb_20.pdf",
    "sha256": "d39698a33486c399124af92bd02e4f978fd9a836b5cf4e52e6e4633eb1d89f61",
    "section": "7.1.12", "printed_page": 159,
    "full_speed_frame_ns": [999500, 1000500],
}
STATUS_FIELDS = (
    "version", "boot", "epoch", "state", "fault", "pattern", "capacity", "sof_rows",
    "words_a", "words_b", "edges_a", "edges_b", "remaining_a", "remaining_b",
    "dmsts_a", "dmsts_b", "gpt7_gtst", "gpt2_gtst", "gpt3_gtst",
    "capture_arm_tick", "stimulus_tick", "capture_end_tick", "leading_begin",
    "leading_end", "trailing_begin", "trailing_end", "initial_low", "final_low",
    "nominal_gpt_hz", "gptckcr", "gptckdivcr", "gpt7_gtcr", "gticasr", "gticbsr",
    "gtior", "gtber", "gpt2_gtupsr", "gpt3_gtupsr", "elc_e", "elc_f",
    "dmtmd_a", "dmtmd_b", "event_a", "event_b", "first_frmnum", "last_frmnum",
    "usb_valid", "first_fsp_error", "cursor_a", "cursor_b", "cursor_sof",
    "required_sof_rows", "calibration_timeout_us", "fixture_timeout_us", "epoch_begin",
    "nominal_pclkd_hz", "gtclkcr",
    "configuration_low", "dmint_a", "dmint_b", "gpt2_gtcr", "gpt3_gtcr", "recording",
)


SPLIT_CAPACITY = 3872
SPLIT_NAMES = ("a_rise", "a_fall", "b_rise", "b_fall")
SPLIT_FIELDS = tuple(f"{field}_{name}" for field in
    ("words", "remaining", "dmsts", "dmtmd", "event", "dmint") for name in SPLIT_NAMES) + (
    "cursor_a_rise", "cursor_a_fall", "cursor_b_rise", "cursor_b_fall", "cursor_split_sof",
    "gpt4_gtcr", "gpt4_gticasr", "gpt4_gticbsr", "gpt4_gtior", "gpt4_gtber", "gpt4_gtst",
    "elc_g", "elc_h", "irq27_cr", "irq28_cr", "p603_pfs", "p602_pfs", "ccr", "mpu", "split_capability",
) + tuple(f"{field}_{name}" for field in ("source", "destination", "buffer", "expected_source")
          for name in SPLIT_NAMES) + ("gpt4_initial", "gpt7_initial", "start_mask", "reserved")

DIRECT_FIELDS = tuple(name.replace("gpt4_", "gpt12_").replace("irq27_cr", "gpt7_gtpr")
    .replace("irq28_cr", "gpt12_gtpr").replace("p602_pfs", "p714_pfs") for name in SPLIT_FIELDS) + (
    "b_capture_arm_tick", "b_stimulus_tick", "b_capture_end_tick", "b_leading_begin", "b_leading_end",
    "b_trailing_begin", "b_trailing_end", "b_initial_low", "b_final_low",
) + tuple(f"reserved_{index}" for index in range(137,144))


def verify_direct_configuration(s, *, complete=False, readiness=False):
    require(s["split_capability"] == 2 and s["reserved"] == 0 and
            all(s[f"reserved_{i}"] == 0 for i in range(137,144)), "Unknown direct capture capability")
    if s["version"] == 4:
        from ael.titan_replacement_observer import verify_memory
        verify_memory(s)
    else:
        require(s["ccr"] & (1 << 16) == 0 and s["mpu"] == 0,"Direct cache/MPU configuration mismatch")
    expected_period=0xfffffffe if readiness else 0xffffffff
    require(s["gpt7_gtpr"] == s["gpt12_gtpr"] == expected_period,"Direct counter modulus mismatch")
    if not readiness:
        require((s["gticasr"],s["gticbsr"],s["gpt12_gticasr"],s["gpt12_gticbsr"]) ==
                (0x300,0xc00,0x3000,0xc000), "Direct polarity selector mismatch")
        require((s["elc_e"],s["elc_f"],s["elc_g"],s["elc_h"]) == (0x1c0,0x1c1,0x1ed,0x1ee) and
                s["gpt2_gtupsr"] == 0x300000 and s["gpt3_gtupsr"] == 0xc00000,
                "Direct edge counter/event mapping mismatch")
        require(s["gpt12_gtcr"] == s["gpt7_gtcr"] == s["gpt2_gtcr"] == s["gpt3_gtcr"] == 1 and
                s["gpt12_gtior"] == s["gpt12_gtber"] == s["gtior"] == s["gtber"] == 0,
                "Direct timer mode/filter mismatch")
        require(s["p603_pfs"] & ~2 == s["p714_pfs"] & ~2 == 0x03010000,
                "Direct physical pin configuration mismatch")
        require(s["gpt12_initial"] == s["gpt7_initial"] == 0 and s["start_mask"] == 0x1080,
                "Direct timer initialisation/start mismatch")
    verify_dma_configuration(s,(0x1c0,0x1c1,0x1ed,0x1ee),
                             (0x4032274c,0x40322750,0x40322c4c,0x40322c50),complete=complete, capacity=s["capacity"])


def stream_counts(s):
    return ([s["words_"+n] for n in SPLIT_NAMES] if s["version"] in (2,3,4) else
            [s["words_a"], s["words_b"]]) + [s["sof_rows"]*4]


def verify_split_configuration(s, *, complete=False, readiness=False):
    if s["version"] in (3,4):
        return verify_direct_configuration(s,complete=complete,readiness=readiness)
    require(s["split_capability"] == 1 and s["reserved"] == 0, "Unknown split capture capability")
    require(s["ccr"] & (1 << 16) == 0 and s["mpu"] == 0,"Split cache/MPU configuration mismatch")
    if not readiness:
        require(s["gticasr"] == 0xc00 and s["gticbsr"] == 0xc000 and
                s["gpt4_gticasr"] == 1 << 20 and s["gpt4_gticbsr"] == 1 << 21,
                "Split polarity capture selector mismatch")
        require((s["elc_e"],s["elc_f"],s["elc_g"],s["elc_h"]) == (0x1c,0x1d,0x1c0,0x1c1) and
                s["gpt2_gtupsr"] == (1 << 20 | 1 << 22) and
                s["gpt3_gtupsr"] == (1 << 21 | 1 << 23), "Split counter/event mapping mismatch")
        require(s["gpt4_gtcr"] == s["gpt7_gtcr"] == s["gpt2_gtcr"] == s["gpt3_gtcr"] == 1 and
                s["gpt4_gtior"] == s["gpt4_gtber"] == s["gtior"] == s["gtber"] == 0,
                "Split timer configuration mismatch")
        require(s["p603_pfs"] & ~2 == s["p602_pfs"] & ~2 == 0x03014000,
                "Split physical pin configuration mismatch")
        require(s["irq27_cr"] == s["irq28_cr"] == 1, "Split IRQ configuration mismatch")
        require(s["gpt4_initial"] == s["gpt7_initial"] == 0 and s["start_mask"] == 0x90,
                "Split timers were not synchronised")
    verify_dma_configuration(s,(0x1a5,0x1c0,0x1a6,0x1c1),
                             (0x4032244c,0x4032274c,0x40322450,0x40322750),complete=complete)


def verify_dma_configuration(s, events, sources, *, complete, capacity=SPLIT_CAPACITY):
    buffers=[s["buffer_"+n] for n in SPLIT_NAMES]
    require(all(abs(a-b) >= 4*capacity for i,a in enumerate(buffers) for b in buffers[i+1:]),
            "Overlapping split DMA buffers")
    for name,event,source in zip(SPLIT_NAMES,events,sources):
        require(s["dmtmd_"+name] == 0x2201 and s["dmint_"+name] == 0 and
                s["event_"+name] == event, "Split DMA ownership mismatch: "+name)
        require(s["source_"+name] == s["expected_source_"+name] == source and
                s["source_"+name] != 0 and s["buffer_"+name] != 0,
                "Split DMA address mismatch: "+name)
        require(s["destination_"+name] == s["buffer_"+name] + 4*s["words_"+name],
                "Split DMA destination/count mismatch: "+name)
        require(s["remaining_"+name] + s["words_"+name] == capacity,
                "Split DMA remaining/count mismatch: "+name)
        if complete:
            require(s["dmsts_"+name] == 0, "Split DMA not quiescent: "+name)


def verify_split_epoch(s, lane_raw, sof_raw, *, pattern, pulses=3840, diagnostic_profile=2):
    """Ordered digital consistency only; IRQ-to-ELC offset is not physical metrology."""
    require(s["state"] == 6 and s["fault"] == s["first_fsp_error"] == 0,
            "Split loopback did not complete cleanly")
    require(s["pattern"] == pattern, "Wrong diagnostic frame index")
    verify_split_configuration(s, complete=True)
    require(s["gtclkcr"] == 0 and s["nominal_gpt_hz"] == 300000000 and
            s["nominal_pclkd_hz"] == 250000000 and s["gptckcr"] == 6 and s["gptckdivcr"] == 1,
            "Unreviewed split capture clock configuration")
    require(len(lane_raw) == 4, "Missing split polarity stream")
    require(s["configuration_low"] == s["initial_low"] == s["final_low"] == 3 and
            s["recording"] == 1, "Split capture LOW/recording evidence missing")
    direct=s["version"] in (3,4)
    require(s["gpt12_gtst" if direct else "gpt4_gtst"] == s["gpt7_gtst"] == 0x8003 and
            s["gpt2_gtst"] == s["gpt3_gtst"] == 0x8000, "Split capture overflow/flags")
    require(s["edges_a"] == s["edges_b"] == s["words_a"] == s["words_b"] == 2*pulses,
            "Missing/extra independent edge count")
    streams=[]
    for stream,(name,raw) in enumerate(zip(SPLIT_NAMES,lane_raw)):
        require(s["words_"+name] == pulses, "Missing/extra polarity edges: "+name)
        origin=s["b_leading_begin" if direct and stream>=2 else "leading_begin"]
        ticks=[(tick-origin) & 0xffffffff for tick in parse_words(raw,pulses)]
        for index,(a,b) in enumerate(zip(ticks,ticks[1:])):
            require(b>a, f"{name} first nonmonotonic/duplicate/wrap at pulse {index+1}: {a}, {b}")
        streams.append(ticks)
    period=3000 if pulses==128 and diagnostic_profile==1 else 390
    hashes=[]; widths=[]
    for lane in (0,1):
        rises,falls=streams[2*lane:2*lane+2]
        prefix="b_" if direct and lane==1 else ""
        if direct:
            bounds=[(s[prefix+k]-s[prefix+"leading_begin"]) & 0xffffffff for k in
                    ("leading_end","stimulus_tick","trailing_begin","trailing_end","capture_end_tick")]
            require(((s[prefix+"leading_begin"]-s[prefix+"capture_arm_tick"]) & 0xffffffff) < 0x80000000 and
                    all(a <= b for a,b in zip(bounds,bounds[1:])) and bounds[-1] < 0x80000000,
                    f"Lane {lane} invalid independent frame boundaries")
            require(s[prefix+"initial_low"] == s[prefix+"final_low"] == 3,
                    f"Lane {lane} missing LOW boundaries")
            require(rises[0] >= ((s[prefix+"stimulus_tick"]-s[prefix+"leading_begin"]) & 0xffffffff),
                    f"Lane {lane} first edge precedes its stimulus")
        require(((s[prefix+"leading_end"]-s[prefix+"leading_begin"]) & 0xffffffff) <= rises[0] and
                falls[-1] <= ((s[prefix+"trailing_begin"]-s[prefix+"leading_begin"]) & 0xffffffff) < 0x80000000,
                f"Lane {lane} first/last edge outside frame")
        expected=diagnostic_payload(pattern,lane,bytes_per_lane=pulses//8) if pulses in (3840,7680) else bytes(pulses//8)
        payload=bytearray(pulses//8); lane_widths=[]
        for bit,(rise,fall) in enumerate(zip(rises,falls)):
            require(rise < fall and (bit==pulses-1 or fall < rises[bit+1]),
                    f"Lane {lane} first rise/fall/next-rise mismatch at bit {bit}: {rise}, {fall}")
            high=fall-rise; lane_widths.append(high)
            if pulses==128 and diagnostic_profile==1:
                require(high==1500,f"Lane {lane} first slow pulse width mismatch at bit {bit}: {high}")
                value=0
            else:
                if direct:
                    require(high in (78,198),f"Lane {lane} first direct HIGH mismatch at bit {bit}: {high}")
                value=int(high>138) # Frozen midpoint of 78/198; no fitted offset/tolerance.
            if expected is not None:
                wanted=(expected[bit//8] >> (7-bit%8)) & 1
                require(value==wanted, f"Lane {lane} first payload mismatch at bit {bit}: high_ticks={high}, expected={wanted}")
            payload[bit//8] |= value << (7-bit%8)
            if bit+1<pulses:
                require(rises[bit+1]-rise == period, f"Lane {lane} first rising period mismatch at bit {bit}")
                if expected is not None:
                    next_value=(expected[(bit+1)//8] >> (7-(bit+1)%8)) & 1
                    expected_delta=period+120*(next_value-value)
                    require(falls[bit+1]-fall == expected_delta,
                            f"Lane {lane} first falling period mismatch at bit {bit}: observed={falls[bit+1]-fall}, expected={expected_delta}")
        hashes.append(digest(payload)); widths.append({"minimum":min(lane_widths),"maximum":max(lane_widths),
            "first":lane_widths[0],"last":lane_widths[-1]})
    timing={"status":"UNQUALIFIED_PIN_TO_CAPTURE_ERROR"}
    try:
        words=parse_words(sof_raw,s["sof_rows"]*4)
        timing["calibration"]=calibrate([words[i:i+4] for i in range(0,len(words),4)])
    except RuntimeError as exc:
        timing["calibration_error"]=str(exc)
    return {"epoch":s["epoch"],"pattern":pattern,"bits_each":pulses,"payload_sha256":hashes,
            "raw_capture_consistent":True,"physical_qualification":False,"measured_waveform_pass":False,
            "timing_qualification":"UNQUALIFIED_PIN_TO_CAPTURE_ERROR","timing":timing,
            "observed_high_ticks":widths,"rise_to_fall_offset":"SAME_LANE_DIRECT_CAPTURE_PHYSICAL_ERROR_UNQUALIFIED" if direct else "UNBOUNDED_IRQ_ELC_VS_DIRECT_CAPTURE",
            "digital_decision_threshold_ticks":138}


def parse_status(raw, boot, epoch):
    require(len(raw) in (256,512,576), "Loopback status must contain exactly 64, 128 or 144 words")
    words = struct.unpack("<"+"I"*(len(raw)//4), raw)
    require(words[0] in (1,2,3) and words[1:3] == (boot,epoch), "Stale loopback version/boot/epoch")
    require(len(words) == {1:64,2:128,3:144}[words[0]], "Status version/length mismatch")
    require(words[63] == 0, "Unknown loopback status extension")
    status = dict(zip(STATUS_FIELDS,words[:63]))
    if words[0] in (2,3):
        status.update(zip(SPLIT_FIELDS if words[0]==2 else DIRECT_FIELDS,words[64:]))
    require(status["state"] <= 8, "Unknown loopback state")
    capacity=CAPACITY if words[0] == 1 else SPLIT_CAPACITY
    require(status["capacity"] == capacity, "Unexpected capture capacity")
    require(status["sof_rows"] <= 256, "Oversized SOF capture")
    keys=("words_a","words_b","remaining_a","remaining_b") if words[0]==1 else tuple(
        field+"_"+name for field in ("words","remaining") for name in SPLIT_NAMES)
    require(all(status[k] <= capacity for k in keys), "Oversized edge capture")
    return status


def parse_chunk(raw, boot, epoch, stream, offset, count, *, max_words=256):
    require(type(max_words) is int and max_words in (256,1000), "Unknown drain chunk capability")
    require(type(count) is int and 1 <= count <= max_words, "Invalid requested chunk length")
    require(len(raw) == 20 + 4 * count, "Truncated/oversized raw chunk")
    header = struct.unpack_from("<5I", raw)
    require(header == (boot, epoch, stream, offset, count), "Wrong raw chunk identity/order")
    return list(struct.unpack_from("<" + "I" * count, raw, 20))


def parse_words(raw, count):
    require(type(count) is int and 0 <= count <= CAPACITY, "Invalid raw word count")
    require(len(raw) == count * 4, "Truncated raw timestamp file")
    return list(struct.unpack("<" + "I" * count, raw))


def calibrate(rows):
    """Conservative frequency interval from independently received USB SOF.

    Each row brackets the actual hardware FRMNUM change in GPT ticks. The
    elapsed reference interval is bounded using every full-speed frame's USB
    specification tolerance, not the transmitter's nominal GPT frequency.
    """
    require(MIN_SOF_ROWS <= len(rows) <= 256, "Insufficient/oversized independent SOF calibration")
    for i, row in enumerate(rows):
        require(len(row) == 4 and all(type(x) is int and 0 <= x <= 0xffffffff for x in row),
                "Malformed SOF row")
        frame, lo, hi, register = row
        require(frame < 2048 and register == frame, "USB frame error flags or wrong frame number")
        require(lo < hi and hi - lo <= 30000, "Unbounded USB observation bracket")
        if i:
            require(frame == (rows[i-1][0] + 1) % 2048, "Missed/repeated USB frame")
            require(lo > rows[i-1][2], "Nonmonotonic/wrapped USB calibration ticks")
    elapsed_min = rows[-1][1] - rows[0][2]
    elapsed_max = rows[-1][2] - rows[0][1]
    frames = len(rows) - 1
    low = math.nextafter(elapsed_min * 1e9 / (frames * 1000500), -math.inf)
    high = math.nextafter(elapsed_max * 1e9 / (frames * 999500), math.inf)
    require(1e6 < low < high < 1e9, "Invalid measured GPT frequency")
    # Check each independent bracket against the resulting frequency envelope.
    for a, b in zip(rows, rows[1:]):
        require((b[1] - a[2]) * 1e9 / high <= 1000500 and
                (b[2] - a[1]) * 1e9 / low >= 999500,
                "Inconsistent USB calibration interval")
    return {"frequency_hz": [low, high], "reference": USB_SOURCE,
            "rows": len(rows), "first_tick": rows[0][1], "last_tick": rows[-1][2],
            "max_bracket_ticks": max(r[2]-r[1] for r in rows)}


def interval_ns(ticks, calibration, endpoint_allowance_ns):
    require(type(ticks) is int and ticks >= 0, "Negative/wrapped interval")
    require(math.isfinite(endpoint_allowance_ns) and endpoint_allowance_ns >= 0,
            "Invalid endpoint uncertainty")
    lo, hi = calibration["frequency_hz"]
    return (math.nextafter(ticks * 1e9 / hi - endpoint_allowance_ns, -math.inf),
            math.nextafter(ticks * 1e9 / lo + endpoint_allowance_ns, math.inf))


def _within(interval, limits):
    return limits[0] <= interval[0] and interval[1] <= limits[1]


def verify_epoch(status_raw, lane_raw, sof_raw, *, boot, epoch, pattern,
                 endpoint_allowance_ns=None):
    """Check raw integrity and a provisional timing model for one window.

    The unspecified pin-to-capture error prevents positive physical timing
    qualification. None applies only known counter quantisation to a provisional
    model. Synthetic tests may exercise other allowances, without qualifying
    them or reading a purported bound from an acquisition manifest.
    """
    s = parse_status(status_raw, boot, epoch)
    if s["version"] in (2,3,4):
        return verify_split_epoch(s,lane_raw,sof_raw,pattern=pattern)
    require(s["state"] == 6 and s["fault"] == s["first_fsp_error"] == 0,
            "Loopback did not complete cleanly")
    require(s["pattern"] == pattern and 0 <= pattern < 120, "Wrong diagnostic frame index")
    require(s["required_sof_rows"] == MIN_SOF_ROWS and s["usb_valid"] == 1,
            "USB clock reference not valid")
    require(s["initial_low"] == s["final_low"] == 3, "Unobserved initial/terminal LOW")
    require(s["gticasr"] == 0xf00 and s["gticbsr"] == 0xf000,
            "Capture source is not both physical input edges")
    require(s["gpt2_gtupsr"] == 1 << 20 and s["gpt3_gtupsr"] == 1 << 21 and
            s["elc_e"] == s["event_a"] == 0x1c0 and s["elc_f"] == s["event_b"] == 0x1c1,
            "Independent edge counter/event mapping mismatch")
    require(s["gtior"] == s["gtber"] == 0, "Input capture output/filter/buffer configuration mismatch")
    require(s["gpt7_gtcr"] == s["gpt2_gtcr"] == s["gpt3_gtcr"] == 1 and
            s["gtclkcr"] == 0 and s["nominal_gpt_hz"] == 300000000 and
            s["nominal_pclkd_hz"] == 250000000 and s["gptckcr"] == 6 and
            s["gptckdivcr"] == 1, "Unreviewed capture clock configuration")
    require(s["dmtmd_a"] == s["dmtmd_b"] == 0x2201 and
            s["dmint_a"] == s["dmint_b"] == 0, "DMA mode/interrupt ownership mismatch")
    require(s["configuration_low"] == 3 and s["recording"] == 1,
            "Capture was not armed from actual LOW")
    require(s["gpt7_gtst"] == 0x8003, "Capture flags/overflow mismatch")
    require(s["gpt2_gtst"] == s["gpt3_gtst"] == 0x8000, "Independent counter overflow")
    # An active transfer or completion at full capacity is a failed acquisition.
    require(s["dmsts_a"] == s["dmsts_b"] == 0, "DMA status not quiescent/error-free")
    sof_words = parse_words(sof_raw, s["sof_rows"] * 4)
    rows = [sof_words[i:i+4] for i in range(0, len(sof_words), 4)]
    cal = calibrate(rows)
    if endpoint_allowance_ns is None:
        endpoint_allowance_ns = 2e9 / cal["frequency_hz"][0]
    require(s["first_frmnum"] < 2048 and (s["first_frmnum"]+1)%2048 == rows[0][3] and
            s["last_frmnum"] == rows[-1][3],
            "SOF endpoint binding mismatch")
    require(rows[MIN_SOF_ROWS-1][2] <= s["capture_arm_tick"],
            "Capture began before independent clock calibration")
    require(s["epoch_begin"] <= cal["first_tick"] < s["capture_arm_tick"] <=
            s["leading_begin"] < s["leading_end"] <= s["stimulus_tick"] <
            s["trailing_begin"] < s["trailing_end"] <= s["capture_end_tick"] <= cal["last_tick"],
            "Incomplete raw clock coverage/quiet boundaries")
    for start, end in ((s["leading_begin"], s["leading_end"]),
                       (s["trailing_begin"], s["trailing_end"])):
        require(interval_ns(end-start, cal, endpoint_allowance_ns)[0] > 280000,
                "Insufficient observed reset LOW")
    payloads = []
    for lane, name in enumerate(("a", "b")):
        require(s["words_"+name] == s["edges_"+name] == EDGE_COUNT and
                s["remaining_"+name] == CAPACITY-EDGE_COUNT,
                "Missing/extra edges or DMA overwrite/loss")
        ticks = parse_words(lane_raw[lane], EDGE_COUNT)
        require(all(b > a for a,b in zip(ticks, ticks[1:])), "Nonmonotonic/duplicate capture ticks")
        require(s["leading_end"] <= ticks[0] and ticks[-1] <= s["trailing_begin"],
                "Capture edge outside observed frame window")
        require(interval_ns(ticks[0]-s["leading_begin"], cal, endpoint_allowance_ns)[0] > 280000 and
                interval_ns(s["trailing_end"]-ticks[-1], cal, endpoint_allowance_ns)[0] > 280000,
                "First/last edge reset incomplete")
        payload = bytearray(480)
        for bit in range(3840):
            rise, fall = ticks[2*bit:2*bit+2]
            high = interval_ns(fall-rise, cal, endpoint_allowance_ns)
            values = [v for v in (0,1) if _within(high, REQUIREMENTS[f"t{v}h_ns"])]
            require(len(values) == 1, "HIGH duration outside independent timing bounds")
            value = values[0]
            payload[bit//8] |= value << (7-bit%8)
            if bit < 3839:
                next_rise = ticks[2*bit+2]
                require(_within(interval_ns(next_rise-fall, cal, endpoint_allowance_ns),
                                REQUIREMENTS[f"t{value}l_ns"]), "LOW duration outside independent timing bounds")
                require(interval_ns(next_rise-rise, cal, endpoint_allowance_ns)[0] >= 1250,
                        "Bit period too short/uncertain")
        require(bytes(payload) == diagnostic_payload(pattern, lane), "Wrong raw payload/bit/lane order")
        payloads.append(digest(payload))
    return {"epoch": epoch, "pattern": pattern, "calibration": cal,
            "payload_sha256": payloads, "bits_each": 3840,
            "physical_qualification": False, "measured_waveform_pass": False,
            "raw_capture_consistent": True,
            "timing_qualification": "UNQUALIFIED_PIN_TO_CAPTURE_ERROR",
            "provisional_endpoint_allowance_ns": endpoint_allowance_ns,
            "missing_metrology": "Independent bound for physical input pad/synchroniser to GPT captured-tick differential error"}


def verify_acquisition(acquisition, candidate):
    """Re-read original segmented raw files; never trust saved verdict fields."""
    a=acquisition
    require(a.get("schema") == "prism.titan.loopback-acquisition.v1" and a.get("backend") in (BACKEND,SPLIT_BACKEND,DIRECT_BACKEND),
            "Unknown segmented acquisition schema/backend")
    for field,value in (("image_sha256",candidate["image"]["sha256"]),
                        ("source_commit",candidate["source_commit"]),
                        ("source_binding_hash",candidate["source_binding_hash"]),
                        ("build_receipt_sha256",candidate["build_receipt"]["sha256"])):
        require(a.get(field) == value,"Segmented acquisition/candidate mismatch: "+field)
    info=a["identity"]
    require(info.get("uid") == UID and info.get("build_source_sha256") == a["source_binding_hash"],
            "Segmented acquisition identity mismatch")
    require(a.get("requirements") == REQUIREMENTS and a.get("usb_reference") == USB_SOURCE,
            "Changed independent physical requirements")
    epochs=a["epochs"]
    require(type(a.get("frames_each")) is int and 100 <= a["frames_each"] <= 120 and
            len(epochs) == a["frames_each"], "Incomplete segmented frame count")
    start,end=a["acquisition_unix"]
    require(all(type(t) in (int,float) and math.isfinite(t) for t in (start,end)) and
            start < end <= start+90 and 0 <= time.time()-end <= 86400,
            "Stale/future/unbounded segmented acquisition")
    event=json.loads(bound(a["programming_event"]))
    require(event.get("identity") == UID and event.get("image_sha256") == a["image_sha256"] and
            event.get("readback_sha256") == a["image_sha256"] and event.get("readback_verified") is True and
            event.get("source_binding_hash") == a["source_binding_hash"] and event["completed_unix"] <= start,
            "Segmented acquisition lacks current image program/verify event")
    from ael.titan_isolated import verify_program_log
    from ael.adapters.prism_bench_trial import bound_file, hex_spans
    require(event.get("image_file") == candidate["image"],"Program event image file mismatch")
    image=bound_file(candidate["image"])
    verify_program_log(bound(event["programmer_log"]),returncode=event["returncode"],argv=event["argv"],
                       image=image,spans=hex_spans(image))
    if a["backend"] in (SPLIT_BACKEND,DIRECT_BACKEND):
        require(a.get("scope") == "frozen-campaign","Diagnostic is not the frozen campaign")
        audio=a["audio_observations"]
        observations=[json.loads(bound(audio[name])) for name in
            ("initial-info.json","final-info.json","initial-transmitter-status.json","final-transmitter-status.json")]
        require(all(observations[i].get(k) == info.get(k) for i in (0,1) for k in
                    ("uid","boot_id","schema_sha256","build_source_sha256")), "Audio observation identity changed")
        verify_audio_progress(*observations)
    results=[]; prior_host=start
    for index,row in enumerate(epochs):
        begin,finish=row["host_unix"]
        require(prior_host <= begin < finish <= end,"Segmented acquisition epoch ordering")
        prior_host=finish
        streams=[bound(x) for x in row["streams"]]
        require(len(streams) in (3,5),"Missing segmented raw stream")
        results.append(verify_epoch(bound(row["status"]),streams[:-1],streams[-1],boot=info["boot_id"],
                                    epoch=index+1,pattern=index))
        status=parse_status(bound(row["status"]),info["boot_id"],index+1)
        require(status["version"] == {BACKEND:1,SPLIT_BACKEND:2,DIRECT_BACKEND:3}[a["backend"]],
                "Acquisition backend/status version mismatch")
        calibration=results[-1].get("calibration",results[-1].get("timing",{}).get("calibration"))
        if calibration is not None:
            minimum_seconds=(status["capture_end_tick"]-status["epoch_begin"])/calibration["frequency_hz"][1]
            require(finish-begin+0.01 >= minimum_seconds,"Host epoch time cannot cover raw acquisition")
    return {"raw_capture_consistent":True,"frames_each":len(results),"epochs":results,
            "measured_waveform_pass":False,"physical_qualification":False,
            "timing_qualification":"UNQUALIFIED_PIN_TO_CAPTURE_ERROR"}


def verify_audio_progress(before,after,transmitter_before,transmitter_after):
    # Growing microphone callbacks cannot cover a stopped transmitter. Direct
    # fixture frames do not use pattern_completed; require the sampled hardware
    # reset completion counter instead. A wrap/reset is not healthy progress.
    a=transmitter_before.get('wire_reset_completions')
    b=transmitter_after.get('wire_reset_completions')
    require(type(a) is int and type(b) is int and 0 <= a < b,
            'Transmitter reset completion progress missing or counter reset')
    for field in ("capture_errors","capture_restart_attempts","capture_restart_failures"):
        require(field in before and field in after and before[field] == after[field],
                "Microphone error/restart changed or missing: "+field)
    require(after.get("capture_stale") is False, "Microphone stale after capture")
    for lane in (0,1):
        require(transmitter_before["microphone_dma"][lane].get("threshold_register") ==
                transmitter_after["microphone_dma"][lane].get("threshold_register") == 1,
                "Microphone threshold changed or missing")
        a=transmitter_before["microphone_dma"][lane]["callbacks"]
        b=transmitter_after["microphone_dma"][lane]["callbacks"]
        require(type(a) is int and type(b) is int and b>a,
                f"Microphone DMA{lane+1} callback progress missing")



TIMING_WITNESS = 0x50524606
TIMING_STAGES = ("output", "audio", "render", "usb", "fixture")


def parse_timing_witness(raw, boot, epoch):
    """Decode the optional v1 diagnostic; it never establishes acceptance."""
    require(len(raw) == 64*4, "Timing witness size mismatch")
    w = struct.unpack("<64I", raw)
    require(w[0] == 1 and w[2:4] == (boot, epoch), "Stale/unknown timing witness")
    require(all(x == 0 for x in w[48:]), "Unknown timing witness extension")
    return {"schema":"prism.titan.fixture-timing-witness.v1", "words":list(w),
            "version":w[0], "terminal_valid":w[1], "boot":w[2], "epoch":w[3],
            "cycle_clock_hz":w[4], "terminal_state":w[5], "fault":w[6],
            "precheck_state":w[7], "window_us":w[8] | w[9]<<32,
            "terminal_now_us":w[10] | w[11]<<32,
            "initial_freeze_gpt7_tick":w[12], "initial_freeze_valid":w[13],
            "terminal_gpt7_tick":w[14], "finishing":w[15],
            "last_poll_cycle":w[16], "max_poll_gap_cycles":w[17],
            "max_gap_preceding_stage":w[18], "last_stage":w[19],
            "stages":{name:{"max_cycles":w[20+i], "latest_begin_cycle":w[25+i],
                            "latest_end_cycle":w[30+i]} for i,name in enumerate(TIMING_STAGES)},
            "queue":dict(zip(("produced","consumed","dropped","overflow",
                              "last_producer_gpt_before","last_producer_gpt_after",
                              "frame","valid","snapshot_consistent",
                              "snapshot_cycle_begin","snapshot_cycle_end"),w[35:46])),
            "wire_completion_observed_cycle":w[46], "wire_completion_observed_valid":w[47],
            "physical_qualification":False}


def acquire(exchange, manifest, spec, out, info, *, verify_one=verify_epoch,
            clock=time.monotonic, sleep=time.sleep, absolute_deadline=None):
    """Run bounded commands using the caller's sole owner and durable wire log.

    Admission of physical exclusion and the bootstrap happens in the gateway.
    Every raw response is persisted before parsing. Failure cancels once, never
    retries a stimulus, and leaves programming recovery to the gateway.
    """
    require(info.get("uid") == UID and info.get("build_source_sha256") == manifest["source_binding_hash"],
            "Loopback runtime identity mismatch")
    require(info.get("capabilities",{}).get("isolated_raw_capture") in (BACKEND,SPLIT_BACKEND,DIRECT_BACKEND),
            "Resident image does not implement raw detector")
    backend=info["capabilities"]["isolated_raw_capture"]
    split=backend in (SPLIT_BACKEND,DIRECT_BACKEND)
    drain_max_words=info.get("capabilities",{}).get("fixture_drain_max_words",256)
    require(type(drain_max_words) is int and drain_max_words in (256,1000),
            "Unknown drain chunk capability")
    single_pattern=spec.get("pattern")
    require(single_pattern is None or type(single_pattern) is int and 0 <= single_pattern < 120,
            "Invalid scoped pattern")
    count = spec.get("frames", 100)
    require(type(count) is int and 100 <= count <= 120, "Need100..120 physical frame pairs")
    boot = info["boot_id"]
    require(type(boot) is int and boot > 0, "Invalid boot identity")
    output = Path(out) / "loopback"
    output.mkdir(exist_ok=False)
    budget = spec.get("budget_seconds",60)
    require(type(budget) in (int,float) and math.isfinite(budget) and 1 <= budget <= 80,
            "Invalid bounded capture budget")
    started = time.time(); deadline = clock() + budget
    if absolute_deadline is not None:
        require(type(absolute_deadline) in (int,float) and math.isfinite(absolute_deadline),
                "Invalid absolute transaction deadline")
        deadline=min(deadline,absolute_deadline)
    require(clock() < deadline,"Transaction expired before detector readiness")
    epochs = []
    current = 0
    def save(name, data):
        path = output / name
        with path.open("xb") as f: f.write(data)
        return {"path": str(path.resolve()), "sha256": digest(data)}
    audio_observations={}
    def transmitter_snapshot(name):
        require(clock() < deadline,"Transaction expired before transmitter observation")
        transmitter_raw=exchange(0x50524c02,struct.pack("<I",boot))
        audio_observations[name]=save(name,transmitter_raw)
        transmitter=json.loads(transmitter_raw)
        require(transmitter.get("schema") == "prism.titan.transmitter.v2",
                "Unexpected transmitter diagnostic schema")
        return transmitter
    has_transmitter_status=info.get("capabilities",{}).get("transmitter_status_opcode") == 0x50524c02
    timing_observations = {}
    timing_attempted = set()
    has_timing_witness = info.get("capabilities",{}).get("fixture_timing_witness_opcode") == TIMING_WITNESS
    def timing_snapshot():
        # Explicit capability preserves old schema-v3 images. One read per epoch,
        # no retry or stimulus, and no extension of the transaction deadline.
        if not has_timing_witness or not current or current in timing_attempted:
            return
        timing_attempted.add(current)
        name = f"{current:03d}-timing-witness"
        try:
            require(clock() < deadline, "Transaction expired before timing witness")
            witness_raw = exchange(TIMING_WITNESS, struct.pack("<I",boot))
            entry = {"raw":save(name+".bin",witness_raw)}
            timing_observations[str(current)] = entry
            parsed = parse_timing_witness(witness_raw,boot,current)
            entry["parsed"] = save(name+".json",(json.dumps(parsed,indent=2)+"\n").encode())
        except Exception as witness_error:
            # Diagnostic failure must not replace acquisition failure or prevent
            # cancellation and the caller's sealed-donor recovery.
            timing_observations.setdefault(str(current),{})["error"] = str(witness_error)
            save(name+"-error.json",json.dumps({"error":str(witness_error)}).encode())
    try:
        if split:
            audio_observations["initial-info.json"]=save("initial-info.json",json.dumps(info).encode())
        ready_raw=exchange(STATUS,struct.pack("<2I",boot,0))
        save("initial-detector-status.bin",ready_raw)
        ready=parse_status(ready_raw,boot,0)
        require(ready["state"] == ready["fault"] == ready["first_fsp_error"] == 0 and
                ready["nominal_gpt_hz"] == 300000000 and ready["nominal_pclkd_hz"] == 250000000 and
                ready["gptckcr"] == 6 and ready["gptckdivcr"] == 1 and ready["gtclkcr"] == 0,
                "Post-program detector resource readiness failed before stimulus")
        require(ready["version"] == {BACKEND:1,SPLIT_BACKEND:2,DIRECT_BACKEND:3}[backend],
                "Backend/status schema mismatch")
        if split:
            verify_split_configuration(ready,readiness=True)
        initial_transmitter=None
        # Retain the existing transmitter's first-fault snapshot. Autonomous
        # startup can already have failed before the recorder is armed; a later
        # recorder deadline alone cannot identify that failure. This is a read,
        # not another stimulus, and stays inside the same absolute deadline.
        require(not split or has_transmitter_status,"Missing microphone status capability before stimulus")
        if has_transmitter_status:
            initial_transmitter=transmitter_snapshot("initial-transmitter-status.json")
        diagnostic=spec.get("constant_timer_diagnostic")
        require(diagnostic is None or type(diagnostic) is int and diagnostic in (1,2), "Unknown constant timer diagnostic")
        require(single_pattern is None or diagnostic is None,"Cannot combine scoped pattern and constant diagnostic")
        if diagnostic is not None:
            save("constant-diagnostic.json",json.dumps({"profile":diagnostic,"pulses_each":128,"expected_edges_each":256,"purpose":"acquisition isolation only; not the frozen pattern campaign","physical_qualification":False}).encode())
        patterns=[single_pattern] if single_pattern is not None else range(1 if diagnostic is not None else count)
        for index,pattern in enumerate(patterns):
            current = index + 1
            require(clock() < deadline, "Bounded acquisition deadline")
            epoch_started=time.time()
            exchange(0x50524605 if diagnostic is not None else ARM, struct.pack("<4I", boot, current, diagnostic if diagnostic is not None else pattern, 1))
            polls = 0
            while True:
                require(clock() < deadline and polls < 1000, "Bounded epoch deadline")
                raw = exchange(STATUS, struct.pack("<2I", boot, current))
                save(f"{current:03d}-status-{polls:04d}.bin", raw)
                s = parse_status(raw, boot, current); polls += 1
                if s["state"] in (6,7,8): break
                require(s["fault"] == 0, "Native detector reports a nonterminal fault")
                sleep(.002)
            timing_snapshot()
            status_row = save(f"{current:03d}-status.bin", raw)
            streams = []
            for stream, total in enumerate(stream_counts(s)):
                words = []
                while len(words) < total:
                    require(clock() < deadline, "Bounded drain deadline")
                    offset = len(words); n = min(drain_max_words, total-offset)
                    chunk = exchange(DRAIN, struct.pack("<5I", boot,current,stream,offset,n))
                    save(f"{current:03d}-stream{stream}-{offset:05d}.bin", chunk)
                    words.extend(parse_chunk(chunk,boot,current,stream,offset,n,max_words=drain_max_words))
                streams.append(save(f"{current:03d}-stream{stream}.u32", struct.pack("<"+"I"*total,*words)))
            row={"status":status_row,"streams":streams,"host_unix":[epoch_started,time.time()]}
            if str(current) in timing_observations:
                row["timing_witness"] = timing_observations[str(current)]
            epochs.append(row)
            save(f"{current:03d}-raw-index.json",(json.dumps(row,indent=2)+"\n").encode())
            final_raw = exchange(STATUS, struct.pack("<2I",boot,current))
            save(f"{current:03d}-drained-status.bin",final_raw)
            final = parse_status(final_raw,boot,current)
            require(all(final[k] == s[k] for k in s if not k.startswith("cursor_")),
                    "Capture changed while draining")
            cursor_keys=tuple("cursor_"+n for n in SPLIT_NAMES)+( "cursor_split_sof",) if split else ("cursor_a","cursor_b","cursor_sof")
            require([final[k] for k in cursor_keys] == stream_counts(s), "Incomplete raw drain")
            if s["state"] != 6 and has_transmitter_status:
                # Raw detector data is already durable. Observe the output
                # owner at failure without replaying ARM or extending recovery.
                try:
                    transmitter_snapshot(f"{current:03d}-failed-transmitter-status.json")
                    require(clock() < deadline,"Transaction expired before failed runtime observation")
                    save(f"{current:03d}-failed-info.json",exchange(1))
                except Exception as diagnostic_error:
                    save(f"{current:03d}-failed-diagnostic-error.json",
                         (json.dumps({"error":str(diagnostic_error)})+"\n").encode())
            if split:
                # Preserve terminal microphone evidence even if raw verification fails.
                terminal_tx=transmitter_snapshot(f"{current:03d}-terminal-transmitter-status.json")
                require(clock() < deadline,"Transaction expired before terminal audio observation")
                terminal_raw=exchange(1)
                terminal_info=json.loads(terminal_raw)
                terminal_row=save(f"{current:03d}-terminal-info.json",terminal_raw)
                row["audio_observations"]={"info":terminal_row,
                    "transmitter":audio_observations[f"{current:03d}-terminal-transmitter-status.json"]}
                save(f"{current:03d}-audio-index.json",json.dumps(row["audio_observations"]).encode())
            try:
                if split:
                    verify_audio_progress(info,terminal_info,initial_transmitter,terminal_tx)
                require(diagnostic is None or split,"Constant timer diagnostic retained; not a pattern qualification run")
                require(s["state"] == 6 and s["fault"] == 0,"Native detector fault/cancel; raw retained")
                lane_raw=[Path(r["path"]).read_bytes() for r in streams[:-1]]
                sof_raw=Path(streams[-1]["path"]).read_bytes()
                if diagnostic is not None and split:
                    result=verify_split_epoch(s,lane_raw,sof_raw,pattern=s["pattern"],pulses=128,diagnostic_profile=diagnostic)
                else:
                    result = verify_one(raw,lane_raw,sof_raw,boot=boot,epoch=current,
                                        pattern=pattern,endpoint_allowance_ns=INPUT_ENDPOINT_ALLOWANCE_NS)
                require(clock() < deadline,"Transaction deadline during raw verification")
                row["result"]=result
            except BaseException as exc:
                row["result"]={"raw_capture_consistent":False,"physical_qualification":False,"error":str(exc)}
                raise
            finally:
                save(f"{current:03d}-outcome.json",(json.dumps(row,indent=2)+"\n").encode())
        last_raw=exchange(1)
        audio_observations["final-info.json"]=save("final-info.json",last_raw)
        last = json.loads(last_raw)
        if split:
            require(initial_transmitter is not None,"Missing initial microphone DMA status")
            final_transmitter=transmitter_snapshot("final-transmitter-status.json")
            verify_audio_progress(info,last,initial_transmitter,final_transmitter)
        require(all(last.get(k) == info.get(k) for k in ("uid","boot_id","schema_sha256","build_source_sha256")),
                "Runtime changed during capture")
    except BaseException as exc:
        timing_snapshot()
        save("failure.json",(json.dumps({"error":str(exc),"epochs":epochs,"timing_witnesses":timing_observations,"physical_qualification":False},indent=2)+"\n").encode())
        raise
    finally:
        if current:
            # Cancellation must not disable normal autonomous music.
            primary_error=sys.exc_info()[1]
            try:
                save("cancel-response.bin",exchange(CANCEL, struct.pack("<2I",boot,current)))
            except BaseException as exc:
                save("cancel-failure.json",json.dumps({"error":str(exc),"primary_error":str(primary_error)}).encode())
                if primary_error is None: raise
    result = {"schema":"prism.titan.loopback-acquisition.v1", "backend":backend,
              "identity":info, "audio_observations":audio_observations, "acquisition_unix":[started,time.time()], "epochs":epochs,
              "frames_each":len(epochs), "physical_qualification":False,
              "scope":"constant-diagnostic" if diagnostic is not None else "single-pattern" if single_pattern is not None else "frozen-campaign",
              "timing_qualification":"UNQUALIFIED_PIN_TO_CAPTURE_ERROR",
              "image_sha256":manifest["image"]["sha256"],"source_commit":manifest["source_commit"],
              "source_binding_hash":manifest["source_binding_hash"],
              "build_receipt_sha256":manifest["build_receipt"]["sha256"],
              "programming_event":manifest["isolated_programming_event"],
              "requirements":REQUIREMENTS,"usb_reference":USB_SOURCE,
              "fixture_id":manifest["isolated_fixture_id"],
              "physical_confirmation":manifest["isolated_qualification"]["physical_confirmation"],
              "bootstrap_authority":manifest["isolated_qualification"]["bootstrap_authority"]}
    save("acquisition.json", (json.dumps(result,indent=2)+"\n").encode())
    return result


# No primary maximum pin/synchroniser error was established. None permits raw
# acquisition and provisional quantisation-only consistency checking, but every
# positive result remains explicitly unqualified for physical timing admission.
INPUT_ENDPOINT_ALLOWANCE_NS = None
