"""Narrow, single-use Titan isolated programming/capture/recovery transaction.

The operator's original confirmation records are inputs, never generated here.
The first-bootstrap exception must explicitly cover the otherwise circular
pre-program detector-readiness requirement. Normal strip deployment does not
use this transaction or its exception.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from ael.deployment_process import run_deployment as _run_deployment
from ael.titan_waveform import UID, bound, digest, require
from ael.titan_loopback import BACKEND, SPLIT_BACKEND, DIRECT_BACKEND
from ael.titan_replacement_observer import BACKEND as REPLACEMENT_BACKEND, PAIRED_BACKEND

JUMPERS = [["U18.7/P601", "U18.33/P603"], ["U18.12/P604", "U18.35/P602"]]
DIRECT_JUMPERS = [["U18.7/P601", "U18.33/P603"], ["U18.12/P604", "U18.36/P714"]]
EXCLUSION = ["P601-product-DIN", "P604-product-DIN"]
OPERATION = "titan-isolated-waveform-v2"
# Bound repair-session leave state. 120s is each operation's cap, not a session
# restoration window and not permission to invent a donor recovery.
REPAIR_SESSION = {
    "mode": "retain-verified-candidate",
    "leave_state": "verified-responsive-candidate",
    "maximum_operation_seconds": 120,
    "restoration": "explicit-end-session",
}
REPAIR_SESSION_SCHEMA = "prism.titan.repair-session.v1"
_QUALIFICATION_KEYS = {
    "operation", "backend", "frames", "maximum_interruption_seconds",
    "physical_confirmation", "bootstrap_authority", "prior_readiness",
    "completion_request", "pattern", "constant_timer_diagnostic", "repair_session", "repair_checkpoint",
}
_IDENTITY_LOSS = (
    "identity mismatch", "identity changed", "identity absent",
    "Wrong native UID", "source identity", "Replacement reboot", "binding failed",
)


def _record(row, schema):
    require(isinstance(row,dict) and set(row) >= {'path','sha256'},
            "Missing bound original record: "+schema)
    record = json.loads(bound(row))
    require(record.get("schema") == schema, "Wrong original record schema: " + schema)
    return record


def _fresh(value, age=120):
    require(type(value) in (int,float) and math.isfinite(value) and 0 <= time.time()-value <= age,
            "Stale/future physical authority or readiness record")


def _scope(m):
    completion = completion_request(m)
    return {"identity": UID, "image_sha256":m["image"]["sha256"],
            "source_binding_hash":m["source_binding_hash"], "source_commit":m["source_commit"],
            "build_receipt_sha256":m["build_receipt"]["sha256"],
            "recovery_sha256":m["recovery"]["image"]["sha256"],
            "jumpers":DIRECT_JUMPERS if m["isolated_qualification"].get("backend") in (DIRECT_BACKEND,REPLACEMENT_BACKEND,PAIRED_BACKEND) else JUMPERS, "electrically_excluded":EXCLUSION,
            "operation":OPERATION, "frames":m["isolated_qualification"]["frames"],
            **({"backend":DIRECT_BACKEND,"capture_schema":3} if m["isolated_qualification"].get("backend") == DIRECT_BACKEND else {}),
            **({"backend":m["isolated_qualification"]["backend"],"capture_schema":5 if m["isolated_qualification"]["backend"] == PAIRED_BACKEND else 4,"target":"titan-replacement",
                "bits_each":7680,"bytes_each":960,"cache":"dcache-noncache-mpu"}
               if m["isolated_qualification"].get("backend") in (REPLACEMENT_BACKEND,PAIRED_BACKEND) else {}),
            "maximum_interruption_seconds":120,
            **({"repair_session": REPAIR_SESSION} if m["isolated_qualification"].get("repair_session") else {}),
            **({"repair_checkpoint": m["isolated_qualification"]["repair_checkpoint"]}
               if m["isolated_qualification"].get("repair_checkpoint") else {}),
            **({"completion": {"kind": completion["kind"],
                                "request_sha256": m["isolated_qualification"]["completion_request"]["sha256"]}}
               if completion is not None else {}),
            **({"pattern":m["isolated_qualification"]["pattern"]} if "pattern" in m["isolated_qualification"] else {}),
            **({"constant_timer_diagnostic":m["isolated_qualification"]["constant_timer_diagnostic"]} if "constant_timer_diagnostic" in m["isolated_qualification"] else {})}


def completion_request(m):
    """Validate one immutable computation request without acquiring hardware."""
    q = m.get("isolated_qualification", {})
    require(set(q) <= _QUALIFICATION_KEYS,
            "Unknown isolated qualification request; no control, replay, SAVE or endurance")
    if "repair_session" in q:
        require(q.get("repair_session") == REPAIR_SESSION,
                "Repair session must bind the exact retain leave-state")
    if "repair_checkpoint" in q:
        require(m.get('target') == 'titan-replacement' and q.get('repair_session') == REPAIR_SESSION,
                'Native update checkpoint requires the replacement repair session')
        checkpoint = q['repair_checkpoint']
        require(isinstance(checkpoint, dict) and set(checkpoint) == {'path', 'sha256'},
                'Native update checkpoint must bind its exact file bytes')
        previous = json.loads(bound(checkpoint))
        require(previous.get('schema') == REPAIR_SESSION_SCHEMA and previous.get('closed') is False,
                'Native update checkpoint is not an open repair session')
    if "completion_request" not in q:
        return None
    require(not any(k in q for k in ("pattern", "constant_timer_diagnostic")),
            "Completion cannot combine with raw diagnostic stimulus")
    spec = json.loads(bound(q["completion_request"]))
    require(isinstance(spec, dict), "Completion request must be an object")
    keys = {"golden": {"kind", "trial", "pcm", "reference", "reference_pcm_sha256", "proxy_source_sha256"},
            "measure": {"kind", "seconds", "live_source", "observer_enabled"}}
    require(spec.get("kind") in keys and set(spec) == keys[spec["kind"]],
            "Isolated completion requires exactly one golden or measure request")
    from ael.prism_completion import prepare
    prepare(spec)
    return spec


def operator_record(row, schema, scope, *, physical_freshness=False):
    """Bind an actual operator statement and the exact request it answered.

    Hashes establish record integrity, not physical truth or message authorship.
    The invoking owner must obtain these original records from the real operator;
    this function cannot manufacture permission from a manifest boolean.
    """
    r = _record(row,schema)
    require(r.get("actor") == "Captain" and r.get("origin") == "operator-message",
            "Actual operator message required; agent attestation is insufficient")
    require(r.get("scope") == scope, "Operator record does not cover exact isolated scope")
    validity = r.get("validity", "recent-observation") if physical_freshness else None
    if physical_freshness:
        require(validity in ("recent-observation", "until-wiring-change"),
                "Unknown physical confirmation validity")
        require(not r.get("wiring_change_reported", False) and
                not r.get("wiring_change_requested", False),
                "Physical fixture changed or a wiring change was requested")
    if physical_freshness and validity == "recent-observation":
        _fresh(r.get("observed_unix"))
    else:
        issued=r.get("observed_unix")
        require(type(issued) in (int,float) and math.isfinite(issued) and 0 <= issued <= time.time(),
                "Invalid/future original authority time")
    message = bound(r["original_message"]).decode("utf-8")
    require(isinstance(r.get("message_reference"),str) and len(r["message_reference"]) >= 8,
            "Missing original operator message reference")
    require(isinstance(r.get("exact_quote"),str) and len(r["exact_quote"].strip()) >= 2 and
            r["exact_quote"] in message, "Original operator statement is not retained")
    if validity == "until-wiring-change":
        # Captain may explicitly keep this exact fixture unchanged throughout
        # a session. Preserve the actual observation time; never restamp it.
        # The invoking owner must retire this record before requesting a wiring
        # change, or immediately on receiving any report that it changed.
        quote = r.get("continuity_quote")
        require(isinstance(quote, str) and len(quote.strip()) >= 16 and quote in message,
                "Standing fixture validity needs the original operator instruction")
    request = json.loads(bound(r["reviewed_request"]))
    require(request.get("scope") == scope, "Operator reviewed a different request")
    return r


def preflight(m, *, consume=False, used_dir=None):
    q = m.get("isolated_qualification",{})
    require(q.get("operation") == OPERATION and q.get("backend") in (BACKEND,SPLIT_BACKEND,DIRECT_BACKEND,REPLACEMENT_BACKEND,PAIRED_BACKEND),
            "BLOCKED_CAPTURE_CAPABILITY: unsupported isolated backend")
    replacement = q.get("backend") in (REPLACEMENT_BACKEND,PAIRED_BACKEND)
    require(m.get("identity") == UID and m.get("target") == ("titan-replacement" if replacement else "titan-native"), "Wrong isolated target")
    if replacement:
        require("completion_request" not in q and "constant_timer_diagnostic" not in q,
                "Replacement does not support legacy fixture/completion operations")
    require(type(q.get("frames")) is int and 100 <= q["frames"] <= 120, "Need100..120 bounded frames")
    require(q.get("maximum_interruption_seconds") == 120, "Unbounded isolated interruption")
    diagnostic=q.get("constant_timer_diagnostic")
    require(diagnostic is None or type(diagnostic) is int and diagnostic in (1,2), "Unknown constant timer diagnostic")
    pattern=q.get("pattern")
    require(pattern is None or type(pattern) is int and 0 <= pattern < 120,"Invalid scoped pattern")
    require(pattern is None or diagnostic is None,"Cannot combine pattern and constant diagnostic")
    scope = _scope(m)
    fixture = operator_record(q["physical_confirmation"], "prism.titan.physical-exclusion.v1", scope,
                              physical_freshness=True)
    require(fixture.get("decision") == "physically-connected-and-product-excluded" and
            fixture.get("physical_basis") == "operator-direct-inspection-of-disconnected-DIN-and-installed-jumpers",
            "Software emit-off or unobserved wiring is not physical exclusion")
    require(isinstance(fixture.get("fixture_id"),str) and len(fixture["fixture_id"]) >= 8,
            "Missing named physical fixture")
    require(fixture.get("measurement_point") == "MCU-pads-P601-P604-3V3",
            "Unsupported/unqualified electrical measurement point")
    authority = operator_record(q["bootstrap_authority"], "prism.titan.isolated-authority.v1", scope)
    require(authority.get("fixture_id") == fixture["fixture_id"], "Authority/fixture mismatch")
    decision = authority.get("decision")
    if decision == "first-isolated-bootstrap-readiness-exception":
        require(authority.get("exception") ==
                "candidate-detector-runtime-readiness-after-program-before-stimulus",
                "Pre-program detector readiness exception was not explicitly covered")
    elif decision == "isolated-acquisition-with-prior-exact-image-readiness":
        # A prior generated acquisition must re-verify its raw observations.
        from ael.titan_loopback import verify_acquisition
        if replacement:
            raise RuntimeError("Replacement requires exact scoped bootstrap; prior readiness admission not yet qualified")
        prior = _record(q["prior_readiness"],"prism.titan.loopback-acquisition.v1")
        verify_acquisition(prior,m)
        require(prior.get("fixture_id") == fixture["fixture_id"], "Prior readiness fixture changed")
        _fresh(prior["acquisition_unix"][1])
    else:
        raise RuntimeError("BLOCKED_PREPROGRAM_DETECTOR_READINESS: explicit first-bootstrap exception or fresh exact-image readiness required")
    require(authority.get("decision_id") and re.fullmatch(r"[a-zA-Z0-9_-]{16,100}",authority["decision_id"]),
            "Missing single-use authority identity")
    # Scope binds the actual completed build and original hardware/ownership
    # records; the gateway validates those records before calling this consumer.
    from ael.adapters.prism_bench_trial import require_titan_recovery
    recovery = require_titan_recovery(m)
    if consume:
        directory = Path(used_dir) if used_dir else Path(__file__).resolve().parents[1]/"_scratch/titan-isolated-used"
        directory.mkdir(parents=True,exist_ok=True)
        try:
            with (directory/(authority["decision_id"]+".json")).open("x") as f:
                json.dump({"scope":scope,"fixture_id":fixture["fixture_id"],"consumed_unix":time.time()},f)
        except FileExistsError as exc:
            raise RuntimeError("Isolated authority was already consumed; no replay") from exc
    return {"scope":scope,"fixture_id":fixture["fixture_id"],"recovery":recovery,
            "preprogram_readiness":decision,"physical_confirmation":q["physical_confirmation"],
            "bootstrap_authority":q["bootstrap_authority"]}


def verify_program_log(raw, *, returncode, argv, image, spans):
    """Consume the retained RFP1.17 program-and-verify log, not exit0 alone.

    -pv performs target-memory comparison. This is a tool-verified comparison
    with the bound image, not a separately exported raw memory dump.
    """
    require(returncode == 0 and argv[-2:] == ["-pv",str(image)] and "-run" in argv,
            "Program/verify invocation did not complete")
    text = raw.decode("utf-8",errors="strict").replace("\r","\n")
    require(text.startswith("Renesas Flash Programmer CLI V1.17\n"), "Unreviewed programmer output version")
    require('Load: "'+str(image)+'"' in text and "Emulator power supply: OFF" in text and
            "Connected to R7KA8P1KFLCAC" in text and "Tool: E2 emulator Lite (5AS079228B)" in text,
            "Wrong programmer image/probe/target/power evidence")
    require(text.count("Verifying data on the target device") == 1 and
            text.count("Writing data to the target device") == 1,
            "Missing/ambiguous actual program-and-verify stages")
    writing, verifying = text.split("Verifying data on the target device")
    require("Writing data to the target device" in writing and verifying.rstrip().endswith("Operation successful"),
            "Programmer did not complete target verification")
    require(not re.search(r"\b(error|failed|failure)\b",text,re.I), "Programmer reported a failure")
    ranges = [(int(a,16),int(b,16)+1) for a,b in re.findall(
        r"\[Code MRAM [12]\]\s+([0-9A-F]{8}) - ([0-9A-F]{8})",verifying)]
    written = [(int(a,16),int(b,16)+1) for a,b in re.findall(
        r"\[Code MRAM [12]\]\s+([0-9A-F]{8}) - ([0-9A-F]{8})", writing)]
    require(ranges and written and all(any(a <= lo < hi <= b for a,b in rows) for rows in (written, ranges) for lo,hi in spans),
            "Verified target ranges do not cover exact image")
    return {"readback_verified":True,"readback_method":"RFP1.17 -pv target-memory comparison",
            "raw_memory_dump_exported":False,"verified_ranges":ranges,"programmer_log_sha256":digest(raw)}


def verify_sealed_program(receipt, *, image, programme_dir, spans):
    """Verify actual sealed-writer channels and its exact immutable projection."""
    from ael.adapters import prism_bench_trial as bench
    require(receipt.get("pass") is True and receipt.get("execute") is True and
            receipt.get("returncode") == 0, "Sealed writer did not complete program/verify")
    require(receipt.get("uid") == UID and receipt.get("hex_sha256") == bench.sha(image),
            "Sealed writer target/image binding mismatch")
    argv = receipt.get("command")
    require(isinstance(argv, list) and len(argv) == 15 and Path(argv[0]).name == "rfp-cli" and
            argv[1:14] == ["-d", "RA", "-t", "e2l:5AS079228B", "-if", "swd", "-s", "1000000",
                           "-noquery", "-run", "-range", "02000000,02c9f01f", "-pv"],
            "Sealed writer command differs from guarded route")
    actual = Path(argv[-1])
    projection = Path(str(programme_dir) + ".writer-view") / "rtthread.hex"
    require(actual == image or actual == projection, "Unexpected sealed writer image path")
    require(actual.is_file() and actual.read_bytes() == image.read_bytes(),
            "Sealed writer projection differs from admitted image bytes")
    stdout, stderr = receipt.get("stdout"), receipt.get("stderr")
    require(isinstance(stdout, str) and isinstance(stderr, str), "Missing sealed writer output channels")
    require("Interface: SWD" in stdout and "Speed: 1,000,000 Hz" in stdout,
            "Wrong programmer interface/speed evidence")
    require(not re.search(r"\b(error|failed|failure)\b", stderr, re.I), "Programmer stderr reported failure")
    evidence = verify_program_log(stdout.encode(), returncode=receipt["returncode"],
                                  argv=argv, image=actual, spans=spans)
    evidence.update(writer_image=str(actual), writer_stdout_sha256=digest(stdout.encode()),
                    writer_stderr_sha256=digest(stderr.encode()))
    return evidence


def wait_for_interface(port, deadline, *, clock=time.monotonic, sleep=time.sleep, present=None):
    """Read-only wait for the exact admitted CDC path; never scan or reopen."""
    require(isinstance(port,str) and port.startswith('/dev/cu.') and '*' not in port,
            "Explicit admitted CDC path required")
    present=present or (lambda:Path(port).is_char_device())
    while clock() < deadline:
        if present(): return
        sleep(min(.1,max(0,deadline-clock())))
    raise TimeoutError("Exact admitted CDC path did not reappear before capture deadline")


def usb_inventory():
    from serial.tools.list_ports import comports
    return list(comports())


def usb_anchor(port, *, deadline=None, inventory=usb_inventory):
    """Bind the freshly identified donor's physical USB location before flashing."""
    if deadline is not None:
        require(time.monotonic() < deadline, "Candidate deadline before USB anchor")
    rows = [p for p in inventory() if p.device == port and
            p.vid == 0x045b and p.pid == 0x5310]
    if deadline is not None:
        require(time.monotonic() < deadline, "Candidate deadline after USB anchor")
    require(len(rows) == 1, "Missing/ambiguous admitted donor USB interface")
    p = rows[0]
    require(isinstance(p.location, str) and p.location, "Missing donor USB location")
    return {"device":p.device, "location":p.location, "serial":p.serial_number,
            "vid":p.vid, "pid":p.pid}


def wait_for_native_interface(anchor, deadline, *, clock=time.monotonic,
                              sleep=time.sleep, inventory=usb_inventory):
    """Resolve re-enumeration without opening arbitrary ports.

    Native platform/titan/usb.h formats BSP UID bytes in address order;
    board_uid.h formats those same bytes in reverse order for application INFO.
    Both serial and original USB socket must match. INFO UID/schema/source checks
    in run_session still precede binding, readiness and diagnostic stimulus.
    """
    serial = bytes.fromhex(UID)[::-1].hex()
    while clock() < deadline:
        rows = [p for p in inventory() if p.vid == 0x045b and p.pid == 0x5310 and
                p.location == anchor["location"] and
                isinstance(p.serial_number, str) and p.serial_number.lower() == serial and
                p.device.startswith('/dev/cu.') and '*' not in p.device]
        require(len(rows) <= 1, "Ambiguous native USB identity at admitted socket")
        if clock() >= deadline:
            break
        if rows:
            p = rows[0]
            return {"device":p.device, "location":p.location, "serial":p.serial_number,
                    "vid":p.vid, "pid":p.pid}
        sleep(min(.1, max(0, deadline-clock())))
    raise TimeoutError("Native USB identity did not reappear at admitted socket before capture deadline")


def require_interface_unowned(port, deadline):
    remaining = deadline-time.monotonic()
    require(remaining > 0, "No candidate budget remains for interface ownership")
    owner = subprocess.run(['lsof','-t',port],capture_output=True,text=True,
                           check=False,timeout=min(3,remaining))
    require(owner.returncode == 1 and not owner.stdout.strip() and not owner.stderr.strip(),
            "Resolved native interface is owned or ownership check failed")


def require_broker_capture_route(manifest):
    """Check current route eligibility before consuming authority or programming."""
    from ael.prism_native import validate_isolated_grant, require_current_owner
    require(manifest.get('target') == 'titan-replacement' and completion_request(manifest) is None,
            'Broker capture route requires replacement isolated collector; historical/completion collector unsupported')
    record = json.loads(Path(manifest['deployment']['admission']).read_text())
    facts = preflight(manifest, consume=False)
    current = {'protocol': 'titan-native', 'uid': manifest['identity'], 'build': manifest['source_binding_hash']}
    validate_isolated_grant(manifest, record, current, facts)
    require_current_owner(manifest, caller=True)


def _repair_value(m):
    repair = (m.get("isolated_qualification") or {}).get("repair_session")
    if repair is None:
        return None
    require(repair == REPAIR_SESSION, "Repair session must bind the exact retain leave-state")
    return repair


def _identity_lost(exc):
    if exc is None:
        return False
    if getattr(exc, "identity_lost", False):
        return True
    text = str(exc)
    return any(part in text for part in _IDENTITY_LOSS)


def _take_leave_proof(logs, exc):
    """Re-read the collector's raw leave proof. A boolean on the exception is not proof."""
    if exc is not None and getattr(exc, "collector_quiesced", True) is False:
        return None
    if isinstance(exc, (KeyboardInterrupt, SystemExit, TimeoutError)):
        return None
    if exc is not None and getattr(exc, "identity_lost", False):
        return None
    path = Path(logs) / "replacement-loopback" / "leave-proof.json"
    if not path.is_file():
        return None
    from ael.titan_replacement_observer import revalidate_leave_proof
    proof = revalidate_leave_proof(path)
    if exc is None and proof["classification"] != "complete":
        return None
    if exc is not None and proof["classification"] != "capture_verification_failed":
        return None
    proof["path"] = str(path.resolve())
    proof["sha256"] = digest(path.read_bytes())
    proof["_claim"] = str(path.with_name("leave-proof.consumed"))
    return proof


def _load_repair_session(path, sha256, manifest):
    """Replay the checkpoint only when its bytes and raw replies still match.

    Plain JSON flags are not a responsiveness verdict. The previous file is
    not rewritten.
    """
    require(path and isinstance(sha256, str) and len(sha256) == 64, "Repair resume needs the checkpoint sha256")
    file = Path(path)
    raw = file.read_bytes()
    require(digest(raw) == sha256, "Repair checkpoint hash mismatch")
    session = json.loads(raw)
    require(session.get("schema") == REPAIR_SESSION_SCHEMA, "Wrong repair session schema")
    require(session.get("image_sha256") == manifest["image"]["sha256"], "Checkpoint image is not the retained candidate")
    require(session.get("closed") is not True, "Repair session is already closed")
    from ael.adapters import prism_bench_trial as bench
    from ael.titan_replacement_observer import revalidate_leave_proof
    proof = revalidate_leave_proof(session["leave_proof"])
    require(session.get("boot") == proof["boot"], "Checkpoint boot does not match the control reply")
    require(session.get("fixture_epoch") == proof["terminal_epoch"], "Checkpoint epoch does not match the status reply")
    require(session.get("classification") == proof["classification"], "Checkpoint classification does not match the leave proof")
    require(proof["identity"].get("uid") == manifest.get("identity"), "Checkpoint identity is not this candidate")
    require(proof["identity"].get("source_id") == manifest.get("source_binding_hash"),
            "Checkpoint source does not match the admitted candidate")
    event = json.loads(bound(session["programming_event"]))
    require(event.get("image_sha256") == manifest["image"]["sha256"], "Checkpoint programming event image mismatch")
    require(event.get("source_binding_hash") == manifest["source_binding_hash"], "Checkpoint source binding mismatch")
    require(session.get("recovery_sha256") == manifest["recovery"]["image"]["sha256"], "Checkpoint recovery image mismatch")
    require(digest(Path(manifest["recovery"]["image"]["path"]).read_bytes()) == session["recovery_sha256"],
            "Recovery image bytes changed after the checkpoint")
    require(digest(Path(manifest["image"]["path"]).read_bytes()) == manifest["image"]["sha256"],
            "Candidate image bytes changed after the checkpoint")
    settings = bound(session["prior_settings"])
    require(len(settings) > 2, "Original settings capture is empty")
    receipt = json.loads(bound(session["sealed_writer_receipt"]))
    image = bench.bound_file(manifest["image"])
    verify_sealed_program(receipt, image=image, programme_dir=Path(session["programme_directory"]),
                          spans=bench.hex_spans(image))
    session["boot"] = proof["boot"]
    session["fixture_epoch"] = proof["terminal_epoch"]
    session["_proof"] = proof
    return session


def _fixture_epoch(result, exc, default):
    if exc is not None and type(getattr(exc, "fixture_epoch", None)) is int:
        return exc.fixture_epoch
    measured = (result or {}).get("isolated_capture") if isinstance(result, dict) else None
    measured = measured or {}
    start = measured.get("start_epoch", default)
    epochs = measured.get("epochs") or []
    if type(start) is int and epochs:
        return start + len(epochs)
    return default if type(start) is not int else start


def _write_repair_session(logs, facts, m, *, fixture_epoch, capture_result, prior_settings):
    session = {
        "schema": REPAIR_SESSION_SCHEMA,
        "leave_state": REPAIR_SESSION["leave_state"],
        "mode": REPAIR_SESSION["mode"],
        "image_sha256": m["image"]["sha256"],
        "source_binding_hash": m["source_binding_hash"],
        "source_commit": m["source_commit"],
        "recovery_sha256": m["recovery"]["image"]["sha256"],
        "recovery_image": m["recovery"]["image"],
        "fixture_epoch": fixture_epoch,
        "capture_result": capture_result,
        "candidate_readback_verified": True,
        "responsive": True,
        "programmed": True,
        "reflash_on_repeat": False,
        "restoration": "explicit-end-session",
        "maximum_operation_seconds": 120,
        "session_duration": "multiple-operations",
        "prior_settings": prior_settings,
        "logs_dir": str(Path(logs).resolve()),
        "closed": False,
    }
    path = Path(logs) / "repair-session.json"
    path.write_text(json.dumps(session, indent=2))
    facts["repair_session_path"] = str(path.resolve())
    facts["repair_session_sha256"] = digest(path.read_bytes())
    facts["fixture_epoch"] = fixture_epoch
    return session


def original_programme_settings(logs, manifest):
    """A native update carries the original legacy capture through its checkpoint."""
    checkpoint = manifest.get('isolated_qualification', {}).get('repair_checkpoint')
    stem = 'candidate-programme.repair-original-settings' if checkpoint is not None else 'candidate-programme.prior-settings'
    captured, captured_hash = Path(logs)/(stem+'.json'), Path(logs)/(stem+'.sha256')
    require(captured.is_file() and captured_hash.is_file(), 'outbound original settings capture missing')
    original = {'path': str(captured.resolve()), 'sha256': captured_hash.read_text().strip()}
    raw = bound(original)
    if checkpoint is not None:
        previous = json.loads(bound(checkpoint))
        require(raw == bound(previous['prior_settings']),
                'native update changed the original legacy settings lineage')
    return original


def execute(m, source, image, ctx, facts, *, resume=None, session_path=None, session_sha256=None,
            epoch_lineage=None, exchange_override=None):
    """Called under the existing hardware lock, after normal owner admission.

    One-shot mode programs one candidate and always recovers the known donor.
    A bound repair_session retains that verified responsive candidate after
    success or a capture data-validation failure. Repeat captures and donor
    restoration are explicit resumes and do not replay a consumed grant.
    """
    from ael.adapters import prism_bench_trial as bench
    from ael.prism_native import run_session
    from ael.prism_native import require_current_owner
    require(os.environ.get("K1_RFP_SWD_EXECUTE_OK") == "1", "Existing RFP root-owner execution gate required")
    require(resume in (None, "capture", "end"), "Unknown repair resume")
    repair = _repair_value(m)
    if resume is not None:
        require(repair, "Resume requires the bound repair session")
    session = _load_repair_session(session_path, session_sha256, m) if resume else None
    active = m
    if repair and resume is None:
        active = dict(m, resident_epoch=0)
    elif resume == "capture":
        require(type(epoch_lineage) is int and epoch_lineage == session["fixture_epoch"],
                "Stale repair epoch lineage")
        require(session["image_sha256"] == m["image"]["sha256"], "Repeat image is not the retained candidate")
        require(session["recovery_sha256"] == m["recovery"]["image"]["sha256"],
                "Repeat changed the checked recovery image")
        active = dict(m, resident_epoch=session["fixture_epoch"], resident_boot=session["boot"])
    elif resume == "end":
        require(session["image_sha256"] == m["image"]["sha256"], "End-session image is not the retained candidate")
        require(session["recovery_sha256"] == m["recovery"]["image"]["sha256"],
                "End-session changed the checked recovery image")
    if resume == "end":
        require_current_owner(m, caller=True)
        pre = preflight(m, consume=False)
    else:
        require_broker_capture_route(active)
        # The programming decision is single-use. Repeats re-check it and do not replay it.
        pre = preflight(active, consume=resume is None)
    logs = Path(ctx.logs_dir)
    settings_logs = Path(session["logs_dir"]) if session and session.get("logs_dir") else logs
    facts.update(hardware_access=False, programmed=False, candidate_program_attempted=False,
                 candidate_readback_verified=False)
    started = time.monotonic()
    capture_deadline=started+80
    recovery_deadline=started+120
    facts.update(candidate_deadline_monotonic=capture_deadline)
    # One-shot mode owns one 120s interruption that includes donor restoration.
    # Repair mode does not schedule that restoration unless this operation must recover.
    if repair:
        facts["recovery_deadline_monotonic"] = None
        facts["session_duration"] = "multiple-operations"
        facts["maximum_operation_seconds"] = 120
    else:
        facts["recovery_deadline_monotonic"] = recovery_deadline
    def write_json(name,obj):
        p=logs/name
        with p.open("x") as f: json.dump(obj,f,indent=2)
        return {"path":str(p.resolve()),"sha256":digest(p.read_bytes())}
    deployment_recovery_safe = True
    def program(candidate, name):
        nonlocal attempted, deployment_recovery_safe
        cutoff=capture_deadline if name=='candidate' else recovery_deadline
        require(time.monotonic() < cutoff, name+" deadline before image validation")
        expected=m['image'] if name=='candidate' else m['recovery']['image']
        require(bench.bound_file(expected) == candidate.resolve(),"Programming image changed after admission")
        programme_dir = logs / (name + "-programme")
        restore_settings = None
        if name == 'donor-recovery':
            restore_settings = session['prior_settings'] if session else original_programme_settings(settings_logs, m)
            bound(restore_settings)
        argv = bench.deployment_argv(m, candidate, name, programme_dir, restore_settings=restore_settings)
        if name == "candidate":
            argv += ["--deadline", str(cutoff)]
        write_json(name+"-invocation.json",{"argv":argv,"image_sha256":bench.sha(candidate),
                    "identity":UID,"fixture_id":pre["fixture_id"],"invoked_unix":time.time()})
        log = logs/(name+".log")
        with log.open("xb") as out:
            remaining=cutoff-time.monotonic()
            require(remaining > 0, name+" deadline before programmer invocation")
            if name == "candidate":
                attempted=True
                facts.update(hardware_access=True, candidate_program_attempted=True)
            timeout=min(70 if name=="candidate" else 90, remaining)
            process = {"argv":argv, "cwd":str(Path.cwd()), "started_unix":time.time(),
                       "started_monotonic":time.monotonic(), "timeout_seconds":timeout,
                       "deadline_monotonic":cutoff, "returncode":None}
            process_error = None
            try:
                deployment_recovery_safe = False
                result = _run_deployment(argv, stdout=out, timeout=timeout,
                                         deadline=cutoff, process=process)
                process.update(outcome="returned", returncode=result.returncode)
            except BaseException as exc:
                process_error = exc
                process.update(outcome="timeout" if isinstance(exc,subprocess.TimeoutExpired) else "exception",
                               exception_type=type(exc).__name__, exception_message=str(exc),
                               returncode_unavailable=process.get("returncode") is None)
            finally:
                deployment_recovery_safe = process.get("recovery_safe", False)
                facts[name+"_process_group_complete"] = process.get("process_group_complete", False)
                process.update(finished_unix=time.time(), finished_monotonic=time.monotonic())
                process["elapsed_seconds"]=process["finished_monotonic"]-process["started_monotonic"]
                try:
                    out.flush()
                    process["combined_output"]={"path":str(log.resolve()),"sha256":digest(log.read_bytes())}
                    facts[name+"_process_receipt"]=write_json(name+"-process.json",process)
                except BaseException as receipt_error:
                    if process_error is None:
                        raise
                    process_error.add_note("Programmer process receipt could not be retained: "+str(receipt_error))
        gateway_rc = process.get("returncode")
        facts[name+"_gateway_returncode"] = gateway_rc
        if gateway_rc != 0:
            facts[name+"_gateway_error"] = log.read_text(errors="replace")
        receipt_path = programme_dir / "receipt.json"
        if receipt_path.is_file():
            sealed = json.loads(receipt_path.read_text())
            facts[name+"_sealed_writer_receipt"] = {"path": str(receipt_path), "sha256": digest(receipt_path.read_bytes())}
            evidence = verify_sealed_program(sealed, image=candidate, programme_dir=programme_dir,
                         spans=(bench.recovery_programmed_spans(m, candidate)
                                if name == "donor-recovery" else bench.hex_spans(candidate)))
        else:
            if process_error is not None:
                raise process_error
            raise RuntimeError("Gateway exited %s without a sealed writer receipt; program/verify unconfirmed" % gateway_rc)
        bench.bound_file(expected)
        if name == "candidate":
            facts.update(programmed=True, candidate_readback_verified=True,
                         candidate_readback_method=evidence["readback_method"])
        evidence.update(identity=UID,image_sha256=bench.sha(candidate),readback_sha256=bench.sha(candidate),
                        source_binding_hash=m["source_binding_hash"] if name=="candidate" else
                        pre['recovery']['build_source_sha256'],completed_unix=time.time(),completed_monotonic=time.monotonic(),
                        programmer_log={"path":str(log.resolve()),"sha256":digest(log.read_bytes())},
                        argv=argv,returncode=gateway_rc,image_file=expected,
                        sealed_writer_receipt=facts[name+"_sealed_writer_receipt"],
                        programme_directory=str(programme_dir.resolve()))
        event=write_json(name+"-programming-event.json",evidence)
        if name=='donor-recovery':
            facts.update(donor_recovery_event=event,known_donor_program_and_verify_completed=True)
        else:
            facts["candidate_programming_event"] = event
        if process_error is not None:
            raise process_error
        require(gateway_rc == 0,
                name+" gateway failed after verified program/readback (exit "+str(gateway_rc)+"); "
                +log.read_text(errors="replace")[-4000:])
        require(time.monotonic() <= cutoff, name+" deadline after programming/readback evidence")
        return event
    attempted=False
    capture_started=False
    result=None
    def capture(event, start_epoch):
        nonlocal capture_started, result
        # Gateway restores the sole broker owner. Do not reopen its serial port.
        resolved = {'broker_socket': m.get('broker_socket', '/tmp/titan-emotiscope-control/titan-control.sock')}
        facts['native_broker_owner'] = resolved
        write_json('native-broker-owner.json', resolved)
        remaining=capture_deadline-time.monotonic()
        require(remaining >= 1,"Candidate programming exhausted bounded interruption")
        completion = completion_request(m)
        payload = {"frames":m["isolated_qualification"]["frames"],"budget_seconds":min(60,remaining),
                   **({"pattern":m["isolated_qualification"]["pattern"]} if "pattern" in m["isolated_qualification"] else {}),
                   **({"constant_timer_diagnostic":m["isolated_qualification"]["constant_timer_diagnostic"]} if "constant_timer_diagnostic" in m["isolated_qualification"] else {})}
        if repair and completion is None:
            payload["start_epoch"] = start_epoch
        operation=write_json("isolated-operation.json", {"completion": completion} if completion is not None else {"isolated_capture":payload})
        runtime=dict(active, isolated_programming_event=event, isolated_fixture_id=pre['fixture_id'],
                     resident_epoch=start_epoch)
        runtime.pop('broker_socket', None)
        if start_epoch > 0:
            runtime["resident_boot"] = session["boot"]
        runtime_binding=write_json('isolated-broker-manifest.json', runtime)
        runtime.update(broker_socket=resolved['broker_socket'], broker_manifest=runtime_binding)
        capture_started=True
        facts["hardware_access"] = True
        result=run_session(runtime,logs,80,operation["path"],deadline=capture_deadline,
                           operation_sha256=operation["sha256"], exchange_override=exchange_override)
        facts["isolated_completion" if completion is not None else "isolated_capture"]=result
        require(time.monotonic() <= capture_deadline,"Capture exceeded recovery reserve")
        facts["physical_qualification"]=False
        return result
    try:
        if resume == "end":
            claim = Path(str(session_path) + ".restoration")
            try:
                with claim.open("x") as stream:
                    stream.write(session_sha256)
            except FileExistsError as error:
                raise RuntimeError("Repair restoration already started") from error
            facts["recovery_deadline_monotonic"] = recovery_deadline
            program(bench.bound_file(m["recovery"]["image"]), "donor-recovery")
            closed = {k: v for k, v in session.items() if k != "_proof"}
            closed["closed"] = True
            closed["restored_from"] = {"path": str(Path(session_path).resolve()), "sha256": session_sha256}
            restored = logs / "repair-restoration.json"
            with restored.open("x") as stream:
                json.dump(closed, stream, indent=2)
            facts["repair_session_closed"] = True
            facts["repair_session_path"] = str(restored.resolve())
            facts["repair_session_sha256"] = digest(restored.read_bytes())
        elif resume == "capture":
            facts["reflash"] = False
            capture(session["programming_event"], session["fixture_epoch"])
        else:
            anchor=usb_anchor(m["port"],deadline=capture_deadline)
            facts["donor_usb_anchor"]=anchor
            write_json("donor-usb-anchor.json",anchor)
            event=program(image,"candidate")
            capture(event, 0)
            facts["candidate_programming_event"]=event
    finally:
        primary_error=sys.exc_info()[1]
        if primary_error is not None: facts["primary_error"]=str(primary_error)
        proof = _take_leave_proof(logs, primary_error) if repair and resume != "end" and capture_started else None
        retain = proof is not None
        if retain:
            facts["collector_quiesced"] = getattr(primary_error, "collector_quiesced", True)
            facts["candidate_retained"] = True
            facts["leave_state"] = REPAIR_SESSION["leave_state"]
            facts["capture_result"] = "FAIL" if primary_error is not None else "PASS"
            facts["known_donor_program_and_verify_completed"] = False
            facts["restoration"] = "explicit-end-session"
            facts["recovery_deadline_monotonic"] = None
            facts["reflash"] = False
            epoch = proof["terminal_epoch"]
            prior = session.get("prior_settings") if session else None
            if prior is None:
                prior = original_programme_settings(logs, m)
            programming_event = (session or {}).get("programming_event") or facts.get("candidate_programming_event")
            event_body = json.loads(bound(programming_event)) if programming_event else {}
            if not prior or not event_body.get("sealed_writer_receipt") or not event_body.get("programme_directory"):
                raise RuntimeError("Verified leave proof has no bound settings or sealed programming receipt")
            claim = Path(proof["_claim"])
            try:
                with claim.open("x") as stream:
                    stream.write(proof["proof_sha256"])
            except FileExistsError as error:
                raise RuntimeError("Leave proof was already consumed") from error
            stored = {
                "schema": REPAIR_SESSION_SCHEMA,
                "leave_state": REPAIR_SESSION["leave_state"],
                "mode": REPAIR_SESSION["mode"],
                "image_sha256": m["image"]["sha256"],
                "source_binding_hash": m["source_binding_hash"],
                "source_commit": m["source_commit"],
                "recovery_sha256": m["recovery"]["image"]["sha256"],
                "recovery_image": m["recovery"]["image"],
                "boot": proof["boot"],
                "fixture_epoch": epoch,
                "classification": proof["classification"],
                "capture_result": facts["capture_result"],
                "restoration": "explicit-end-session",
                "maximum_operation_seconds": 120,
                "session_duration": "multiple-operations",
                "prior_settings": prior,
                "programming_event": programming_event,
                "sealed_writer_receipt": event_body["sealed_writer_receipt"],
                "programme_directory": event_body["programme_directory"],
                "leave_proof": {"path": proof["path"], "sha256": proof["sha256"]},
                "previous_checkpoint": None if session_path is None else {
                    "path": str(Path(session_path).resolve()), "sha256": session_sha256},
                "logs_dir": str((Path(session["logs_dir"]) if session else logs).resolve()),
                "closed": False,
            }
            target = logs / "repair-checkpoint.json"
            with target.open("x") as stream:
                json.dump(stored, stream, indent=2)
            facts["repair_session_path"] = str(target.resolve())
            facts["repair_session_sha256"] = digest(target.read_bytes())
            facts["fixture_epoch"] = epoch
            facts["boot"] = proof["boot"]
            facts["interruption_elapsed_seconds"]=time.monotonic()-started
            facts["operation_elapsed_seconds"]=facts["interruption_elapsed_seconds"]
            facts["interruption_boundary_exceeded"]=False
            facts["optical_leave_state_verified"]=False
            write_json("isolated-transaction.json",facts)
            if facts["operation_elapsed_seconds"] > 120 and primary_error is None:
                raise TimeoutError("Operation exceeded 120s bound; candidate retained and donor restoration was not started")
            if primary_error is not None:
                raise primary_error
        elif attempted or resume == "end" or (resume == "capture" and capture_started):
            try:
                if resume != "end":
                    facts["recovery_deadline_monotonic"] = recovery_deadline
                    require(deployment_recovery_safe, "Deployment process group cleanup unresolved; donor recovery forbidden")
                    collector_quiesced = getattr(primary_error, "collector_quiesced", True)
                    facts["collector_quiesced"] = collector_quiesced
                    require(collector_quiesced, "Broker collector cancellation unresolved; donor recovery forbidden")
                    recovery=bench.bound_file(m["recovery"]["image"])
                    facts["donor_recovery_event"]=program(recovery,"donor-recovery")
                    facts["known_donor_program_and_verify_completed"]=True
            except BaseException as exc:
                facts.setdefault("known_donor_program_and_verify_completed",False)
                facts["recovery_error"]=str(exc)
                write_json("recovery-failed.json",facts)
                if primary_error is not None:
                    primary_error.add_note("Donor recovery also failed its contract: "+str(exc))
                    raise primary_error from exc
                raise
            finally:
                facts["interruption_elapsed_seconds"]=time.monotonic()-started
                facts["interruption_boundary_exceeded"]=facts["interruption_elapsed_seconds"] > 120
                facts["optical_leave_state_verified"]=False
                write_json("isolated-transaction.json",facts)
                if facts["interruption_boundary_exceeded"] and primary_error is None and not facts.get("recovery_error"):
                    raise TimeoutError("Interruption exceeded120s authority; recovery evidence retained")
    require(facts["interruption_elapsed_seconds"] <= 120,"Interruption exceeded120s authority")
