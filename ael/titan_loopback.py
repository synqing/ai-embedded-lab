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


def parse_status(raw, boot, epoch):
    require(len(raw) == 256, "Loopback status must contain exactly64 words")
    words = struct.unpack("<64I", raw)
    require(words[0] == 1 and words[1:3] == (boot, epoch), "Stale loopback version/boot/epoch")
    require(words[63] == 0, "Unknown loopback status extension")
    status = dict(zip(STATUS_FIELDS, words))
    require(status["state"] <= 8, "Unknown loopback state")
    require(status["capacity"] == CAPACITY, "Unexpected capture capacity")
    require(status["sof_rows"] <= 256, "Oversized SOF capture")
    require(all(status[k] <= CAPACITY for k in ("words_a", "words_b", "remaining_a", "remaining_b")),
            "Oversized edge capture")
    return status


def parse_chunk(raw, boot, epoch, stream, offset, count):
    require(type(count) is int and 1 <= count <= 256, "Invalid requested chunk length")
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
    require(a.get("schema") == "prism.titan.loopback-acquisition.v1" and a.get("backend") == BACKEND,
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
    results=[]; prior_host=start
    for index,row in enumerate(epochs):
        begin,finish=row["host_unix"]
        require(prior_host <= begin < finish <= end,"Segmented acquisition epoch ordering")
        prior_host=finish
        streams=[bound(x) for x in row["streams"]]
        require(len(streams)==3,"Missing segmented raw stream")
        results.append(verify_epoch(bound(row["status"]),streams[:2],streams[2],boot=info["boot_id"],
                                    epoch=index+1,pattern=index))
        status=parse_status(bound(row["status"]),info["boot_id"],index+1)
        minimum_seconds=(status["capture_end_tick"]-status["epoch_begin"])/results[-1]["calibration"]["frequency_hz"][1]
        require(finish-begin+0.01 >= minimum_seconds,"Host epoch time cannot cover raw acquisition")
    return {"raw_capture_consistent":True,"frames_each":len(results),"epochs":results,
            "measured_waveform_pass":False,"physical_qualification":False,
            "timing_qualification":"UNQUALIFIED_PIN_TO_CAPTURE_ERROR"}


def acquire(exchange, manifest, spec, out, info, *, verify_one=verify_epoch,
            clock=time.monotonic, sleep=time.sleep, absolute_deadline=None):
    """Run bounded commands using the caller's sole owner and durable wire log.

    Admission of physical exclusion and the bootstrap happens in the gateway.
    Every raw response is persisted before parsing. Failure cancels once, never
    retries a stimulus, and leaves programming recovery to the gateway.
    """
    require(info.get("uid") == UID and info.get("build_source_sha256") == manifest["source_binding_hash"],
            "Loopback runtime identity mismatch")
    require(info.get("capabilities",{}).get("isolated_raw_capture") == BACKEND,
            "Resident image does not implement raw detector")
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
    try:
        ready_raw=exchange(STATUS,struct.pack("<2I",boot,0))
        save("initial-detector-status.bin",ready_raw)
        ready=parse_status(ready_raw,boot,0)
        require(ready["state"] == ready["fault"] == ready["first_fsp_error"] == 0 and
                ready["nominal_gpt_hz"] == 300000000 and ready["nominal_pclkd_hz"] == 250000000 and
                ready["gptckcr"] == 6 and ready["gptckdivcr"] == 1 and ready["gtclkcr"] == 0,
                "Post-program detector resource readiness failed before stimulus")
        # Retain the existing transmitter's first-fault snapshot. Autonomous
        # startup can already have failed before the recorder is armed; a later
        # recorder deadline alone cannot identify that failure. This is a read,
        # not another stimulus, and stays inside the same absolute deadline.
        if info.get("capabilities",{}).get("transmitter_status_opcode") == 0x50524c02:
            require(clock() < deadline,"Transaction expired before transmitter observation")
            transmitter_raw=exchange(0x50524c02,struct.pack("<I",boot))
            save("initial-transmitter-status.json",transmitter_raw)
            transmitter=json.loads(transmitter_raw)
            require(transmitter.get("schema") == "prism.titan.transmitter.v2",
                    "Unexpected transmitter diagnostic schema")
        for pattern in range(count):
            current = pattern + 1
            require(clock() < deadline, "Bounded acquisition deadline")
            epoch_started=time.time()
            exchange(ARM, struct.pack("<4I", boot, current, pattern, 1))
            polls = 0
            while True:
                require(clock() < deadline and polls < 1000, "Bounded epoch deadline")
                raw = exchange(STATUS, struct.pack("<2I", boot, current))
                save(f"{current:03d}-status-{polls:04d}.bin", raw)
                s = parse_status(raw, boot, current); polls += 1
                if s["state"] in (6,7,8): break
                require(s["fault"] == 0, "Native detector reports a nonterminal fault")
                sleep(.002)
            status_row = save(f"{current:03d}-status.bin", raw)
            streams = []
            for stream, total in enumerate((s["words_a"], s["words_b"], s["sof_rows"]*4)):
                words = []
                while len(words) < total:
                    require(clock() < deadline, "Bounded drain deadline")
                    offset = len(words); n = min(256, total-offset)
                    chunk = exchange(DRAIN, struct.pack("<5I", boot,current,stream,offset,n))
                    save(f"{current:03d}-stream{stream}-{offset:05d}.bin", chunk)
                    words.extend(parse_chunk(chunk,boot,current,stream,offset,n))
                streams.append(save(f"{current:03d}-stream{stream}.u32", struct.pack("<"+"I"*total,*words)))
            row={"status":status_row,"streams":streams,"host_unix":[epoch_started,time.time()]}
            epochs.append(row)
            save(f"{current:03d}-raw-index.json",(json.dumps(row,indent=2)+"\n").encode())
            final_raw = exchange(STATUS, struct.pack("<2I",boot,current))
            save(f"{current:03d}-drained-status.bin",final_raw)
            final = parse_status(final_raw,boot,current)
            require(all(final[k] == s[k] for k in s if not k.startswith("cursor_")),
                    "Capture changed while draining")
            require([final[k] for k in ("cursor_a","cursor_b","cursor_sof")] ==
                    [s["words_a"],s["words_b"],s["sof_rows"]*4], "Incomplete raw drain")
            try:
                require(s["state"] == 6 and s["fault"] == 0,"Native detector fault/cancel; raw retained")
                result = verify_one(raw, [Path(r["path"]).read_bytes() for r in streams[:2]],
                                    Path(streams[2]["path"]).read_bytes(), boot=boot,epoch=current,
                                    pattern=pattern,endpoint_allowance_ns=INPUT_ENDPOINT_ALLOWANCE_NS)
                require(clock() < deadline,"Transaction deadline during raw verification")
                row["result"]=result
            except BaseException as exc:
                row["result"]={"raw_capture_consistent":False,"physical_qualification":False,"error":str(exc)}
                raise
            finally:
                save(f"{current:03d}-outcome.json",(json.dumps(row,indent=2)+"\n").encode())
        last = json.loads(exchange(1))
        require(all(last.get(k) == info.get(k) for k in ("uid","boot_id","schema_sha256","build_source_sha256")),
                "Runtime changed during capture")
    except BaseException as exc:
        save("failure.json",(json.dumps({"error":str(exc),"epochs":epochs,"physical_qualification":False},indent=2)+"\n").encode())
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
    result = {"schema":"prism.titan.loopback-acquisition.v1", "backend":BACKEND,
              "identity":info, "acquisition_unix":[started,time.time()], "epochs":epochs,
              "frames_each":count, "physical_qualification":False,
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
