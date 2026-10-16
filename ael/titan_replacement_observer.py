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
IDENTITY, CONTROL_STATUS, HEALTH = 0x50524200, 0x50524201, 0x50524205
CAPACITY = 7712
BITS = 7680
CORE = "0b6d1fb7f9a22a951818c1508b3de9ca289f4bdf"
EXTENSION = ("dma_begin", "dma_end", "dma_rbar", "dma_rlar", "dma_mair0",
             "dma_a_rise", "dma_a_fall", "dma_b_rise", "dma_b_fall",
             "microphone_begin", "microphone_end", "led_begin", "led_end",
             "observer_timeout_us", "drain_max_words")
SCHEMA = "prism.titan.replacement-acquisition.v1"


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


def identity(info, manifest):
    require(manifest.get("target") == "titan-replacement" and info.get("uid") == UID
            and info.get("contract") == "titan-replacement-v1"
            and info.get("build_profile") == "titan-replacement"
            and info.get("source_id") == manifest["source_binding_hash"]
            and info.get("core_commit") == CORE and info.get("core_tag") == "v0.12.0-rc.2"
            and info.get("scene_pixels") == [160, 160] and info.get("logical_hz") == 120,
            "Replacement identity/source/profile/geometry mismatch")
    require(info.get("capabilities", {}).get("isolated_raw_capture") == BACKEND,
            "BLOCKED_CAPTURE_CAPABILITY: replacement firmware v4 fixture is absent")
    require(info["capabilities"].get("fixture_drain_max_words") == 1000,
            "Replacement requires bounded 1000-word drain capability")


def control_status(raw):
    require(len(raw) == 112, "Replacement status must remain 112 bytes")
    version, boot, _, target = struct.unpack_from("<4I", raw)
    require(version == 1 and boot > 0 and target == 1 and raw[16:48] == UID.encode(),
            "Replacement status version/boot/target mismatch")
    return boot


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
    for name in legacy.SPLIT_NAMES:
        address = s["buffer_" + name]
        require(address % 32 == 0 and begin <= address < address + 4 * CAPACITY <= end,
                "Observer DMA buffer outside observed noncache span")
        require(all(address + 4*CAPACITY <= lo or hi <= address for lo,hi in protected),
                "Observer buffer aliases microphone/LED storage")


def status(raw, boot, epoch):
    require(len(raw) == 640, "Replacement v4 status requires 160 words")
    words = struct.unpack("<160I", raw)
    require(words[:3] == (4, boot, epoch), "Stale replacement version/boot/epoch")
    require(words[63] == 0 and words[159] == 0, "Unknown replacement status extension")
    s = dict(zip(legacy.STATUS_FIELDS, words[:63]))
    s.update(zip(legacy.DIRECT_FIELDS, words[64:144]))
    s.update(zip(EXTENSION, words[144:159]))
    require(s["capacity"] == CAPACITY and s["state"] <= 8 and s["sof_rows"] <= 256,
            "Wrong replacement capacity/state")
    require(all(s[field + "_" + name] <= CAPACITY for field in ("words", "remaining")
                for name in legacy.SPLIT_NAMES), "Oversized replacement capture")
    return s


def verify_epoch(s, streams, pattern):
    require(len(streams) == 5, "Missing replacement raw stream")
    result = legacy.verify_split_epoch(s, streams[:4], streams[4], pattern=pattern, pulses=BITS)
    for prefix in ("", "b_"):
        # 300 MHz nominal ticks: diagnostic consistency only, not calibrated time.
        for first, last in (("leading_begin", "leading_end"), ("trailing_begin", "trailing_end")):
            span = (s[prefix + last] - s[prefix + first]) & 0xffffffff
            require(105000 <= span < 0x80000000, "Missing replacement 350us reset coverage")
    return result


def verify_acquisition(a, candidate):
    """Re-read bound raw records; saved positive verdicts have no authority."""
    require(a.get("schema") == SCHEMA and a.get("backend") == BACKEND, "Wrong replacement acquisition schema")
    identity(a["identity"], candidate)
    for key, value in (("image_sha256", candidate["image"]["sha256"]),
                       ("source_commit", candidate["source_commit"]),
                       ("source_binding_hash", candidate["source_binding_hash"]),
                       ("build_receipt_sha256", candidate["build_receipt"]["sha256"])):
        require(a.get(key) == value, "Replacement capture/candidate mismatch: " + key)
    start, end = a["acquisition_unix"]
    require(all(type(t) in (int,float) and math.isfinite(t) for t in (start,end))
            and start < end <= start + 80 and 0 <= time.time()-end <= 86400, "Stale replacement acquisition")
    event = json.loads(bound(a["programming_event"]))
    require(event.get("identity") == UID and event.get("image_sha256") == a["image_sha256"]
            and event.get("readback_sha256") == a["image_sha256"] and event.get("readback_verified") is True
            and event.get("source_binding_hash") == a["source_binding_hash"] and event["completed_unix"] <= start
            and event.get("image_file") == candidate["image"], "Wrong replacement programming event")
    from ael.titan_isolated import verify_program_log
    from ael.adapters.prism_bench_trial import bound_file, hex_spans
    image = bound_file(candidate["image"])
    verify_program_log(bound(event["programmer_log"]), returncode=event["returncode"], argv=event["argv"],
                       image=image, spans=hex_spans(image))
    boot = control_status(bound(a["control_status"]))
    require(boot == a["boot"] == control_status(bound(a["final_control"])), "Replacement boot changed")
    require(json.loads(bound(a["final_identity"])) == a["identity"], "Replacement final identity changed")
    ready = status(bound(a["ready"]), boot, 0)
    require(ready["state"] == ready["fault"] == ready["first_fsp_error"] == 0, "Detector not ready")
    legacy.verify_direct_configuration(ready, readiness=True)
    for name in ("health_before", "health_after"):
        json.loads(bound(a[name]))  # Original health evidence; no invented health verdict.
    epochs = a["epochs"]
    require(type(a.get("frames_each")) is int and 100 <= len(epochs) == a["frames_each"] <= 120,
            "Incomplete replacement campaign")
    previous = start
    for index, row in enumerate(epochs):
        begin, finish = row["host_unix"]
        require(previous <= begin < finish <= end and row["pattern"] == index, "Stale/reordered replacement epoch")
        previous = finish
        s = status(bound(row["status"]), boot, index+1)
        final = status(bound(row["drained_status"]), boot, index+1)
        require(all(final[k] == s[k] for k in s if not k.startswith("cursor_")), "Changed drained capture")
        require([final["cursor_"+n] for n in legacy.SPLIT_NAMES] + [final["cursor_split_sof"]]
                == legacy.stream_counts(s), "Incomplete replacement drain")
        verify_epoch(s, [bound(r) for r in row["streams"]], index)
    return {"raw_capture_consistent": True, "physical_qualification": False,
            "timing_qualification": "UNQUALIFIED_INPUT_CAPTURE_TIMING", "frames_each": len(epochs)}


def acquire(exchange, manifest, spec, out, info, *, absolute_deadline, clock=time.monotonic, sleep=time.sleep):
    """Real ARM/poll/drain/cancel route; all replies retained before decoding."""
    identity(info, manifest)
    count = spec.get("frames")
    require(type(count) is int and 100 <= count <= 120 and not set(spec) - {"frames", "budget_seconds", "pattern"},
            "Unsupported replacement acquisition request")
    pattern = spec.get("pattern")
    require(pattern is None or type(pattern) is int and 0 <= pattern < 120, "Wrong replacement pattern")
    budget = spec.get("budget_seconds")
    require(type(budget) in (int, float) and math.isfinite(budget) and 0 < budget <= 60
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
    started = time.time(); epochs = []; current = 0
    initial, initial_row = read("control-status.bin", CONTROL_STATUS)
    boot = control_status(initial)
    raw, _ = read("bind-status.bin", 0x50524202, struct.pack("<2I", 1, boot) + UID.encode())
    require(control_status(raw) == boot and struct.unpack_from("<I", raw, 8)[0] == 1,
            "Replacement fixture binding failed")
    _, health_before = read("health-before.json", HEALTH)
    ready, ready_row = read("ready.bin", legacy.STATUS, struct.pack("<2I", boot, 0))
    s = status(ready, boot, 0)
    require(s["state"] == s["fault"] == s["first_fsp_error"] == 0, "Replacement detector not ready")
    legacy.verify_direct_configuration(s, readiness=True)
    try:
        for index, selected in enumerate([pattern] if pattern is not None else range(count)):
            current = index + 1; begin = time.time()
            read(f"{current}-arm.bin", legacy.ARM, struct.pack("<4I", boot, current, selected, 1))
            for poll in range(1000):
                raw, status_row = read(f"{current}-status-{poll}.bin", legacy.STATUS, struct.pack("<2I", boot, current))
                s = status(raw, boot, current)
                if s["state"] in (6, 7, 8): break
                require(s["fault"] == 0, "Replacement nonterminal detector fault")
                sleep(min(.005, max(0, deadline-clock())))
            require(s["state"] in (6, 7, 8), "Replacement polling limit")
            streams = []; raw_streams = []
            for stream, total in enumerate(legacy.stream_counts(s)):
                words = []
                while len(words) < total:
                    offset = len(words); n = min(1000, total-offset)
                    raw, _ = read(f"{current}-stream{stream}-{offset}.bin", legacy.DRAIN,
                                  struct.pack("<5I", boot, current, stream, offset, n))
                    words.extend(legacy.parse_chunk(raw, boot, current, stream, offset, n, max_words=1000))
                raw = struct.pack("<" + "I" * total, *words)
                raw_streams.append(raw); streams.append(save(f"{current}-stream{stream}.u32", raw))
            raw, final_row = read(f"{current}-drained.bin", legacy.STATUS, struct.pack("<2I", boot, current))
            final = status(raw, boot, current)
            require(all(final[k] == s[k] for k in s if not k.startswith("cursor_")), "Capture changed while draining")
            require([final["cursor_"+n] for n in legacy.SPLIT_NAMES] + [final["cursor_split_sof"]]
                    == legacy.stream_counts(s), "Incomplete replacement drain")
            row = {"status": status_row, "drained_status": final_row, "streams": streams,
                   "pattern": selected, "host_unix": [begin, time.time()]}
            epochs.append(row)
            save(f"{current}-index.json", json.dumps(row).encode())
            verify_epoch(s, raw_streams, selected)
        raw, final_identity = read("identity-after.json", IDENTITY)
        require(json.loads(raw) == info, "Replacement identity changed during acquisition")
        raw, final_control = read("control-after.bin", CONTROL_STATUS)
        require(control_status(raw) == boot, "Replacement reboot during acquisition")
        _, health_after = read("health-after.json", HEALTH)
    except BaseException as exc:
        failure = {"error": str(exc), "epochs": epochs, "physical_qualification": False}
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
            try:
                require(clock() < absolute_deadline, "No candidate budget remains for cancellation")
                save("cancel.bin", exchange(legacy.CANCEL, struct.pack("<2I", boot, current),
                                            absolute_deadline=absolute_deadline))
            except Exception as exc:
                save("cancel-error.json", json.dumps({"error": str(exc)}).encode())
                if primary is None: raise
    result = {"schema": SCHEMA, "backend": BACKEND, "identity": info, "boot": boot,
              "control_status": initial_row, "ready": ready_row, "epochs": epochs,
              "final_identity": final_identity, "final_control": final_control,
              "health_before": health_before, "health_after": health_after,
              "frames_each": len(epochs), "acquisition_unix": [started, time.time()],
              "image_sha256": manifest["image"]["sha256"], "source_commit": manifest["source_commit"],
              "source_binding_hash": manifest["source_binding_hash"], "build_receipt_sha256": manifest["build_receipt"]["sha256"],
              "programming_event": manifest["isolated_programming_event"],
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
            "profile": "titan-replacement", "backend": BACKEND, "bits_each": BITS, "bytes_each": 960,
            "firmware_dependency": "Final candidate binding and runtime v4 readiness required; this offline check does not establish fixture capability",
            "hardware_access": False, "physical_qualification": False}
        print(json.dumps(result, indent=2)); return 0
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "hardware_access": False})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
