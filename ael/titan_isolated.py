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

from ael.titan_waveform import UID, bound, digest, require
from ael.titan_loopback import BACKEND, SPLIT_BACKEND, DIRECT_BACKEND

JUMPERS = [["U18.7/P601", "U18.33/P603"], ["U18.12/P604", "U18.35/P602"]]
DIRECT_JUMPERS = [["U18.7/P601", "U18.33/P603"], ["U18.12/P604", "U18.36/P714"]]
EXCLUSION = ["P601-product-DIN", "P604-product-DIN"]
OPERATION = "titan-isolated-waveform-v2"


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
    from ael.adapters.prism_bench_trial import TITAN_RECOVERY_HEX_SHA256
    completion = completion_request(m)
    return {"identity": UID, "image_sha256":m["image"]["sha256"],
            "source_binding_hash":m["source_binding_hash"], "source_commit":m["source_commit"],
            "build_receipt_sha256":m["build_receipt"]["sha256"],
            "recovery_sha256":TITAN_RECOVERY_HEX_SHA256,
            "jumpers":DIRECT_JUMPERS if m["isolated_qualification"].get("backend") == DIRECT_BACKEND else JUMPERS, "electrically_excluded":EXCLUSION,
            "operation":OPERATION, "frames":m["isolated_qualification"]["frames"],
            **({"backend":DIRECT_BACKEND,"capture_schema":3} if m["isolated_qualification"].get("backend") == DIRECT_BACKEND else {}),
            "maximum_interruption_seconds":120,
            **({"completion": {"kind": completion["kind"],
                                "request_sha256": m["isolated_qualification"]["completion_request"]["sha256"]}}
               if completion is not None else {}),
            **({"pattern":m["isolated_qualification"]["pattern"]} if "pattern" in m["isolated_qualification"] else {}),
            **({"constant_timer_diagnostic":m["isolated_qualification"]["constant_timer_diagnostic"]} if "constant_timer_diagnostic" in m["isolated_qualification"] else {})}


def completion_request(m):
    """Validate one immutable computation request without acquiring hardware."""
    q = m.get("isolated_qualification", {})
    require(set(q) <= {"operation", "backend", "frames", "maximum_interruption_seconds",
                      "physical_confirmation", "bootstrap_authority", "prior_readiness",
                      "completion_request", "pattern", "constant_timer_diagnostic"},
            "Unknown isolated qualification request; no control, replay, SAVE or endurance")
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
    require(q.get("operation") == OPERATION and q.get("backend") in (BACKEND,SPLIT_BACKEND,DIRECT_BACKEND),
            "BLOCKED_CAPTURE_CAPABILITY: unsupported isolated backend")
    require(m.get("identity") == UID and m.get("target") == "titan-native", "Wrong isolated target")
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
    require("Writing data to the target device" in writing and "100%" in writing and
            re.search(r"\b100%",verifying) and verifying.rstrip().endswith("Operation successful"),
            "Programmer did not complete target verification")
    require(not re.search(r"\b(error|failed|failure)\b",text,re.I), "Programmer reported a failure")
    ranges = [(int(a,16),int(b,16)+1) for a,b in re.findall(
        r"\[Code MRAM [12]\]\s+([0-9A-F]{8}) - ([0-9A-F]{8})",verifying)]
    require(ranges and all(any(a <= lo < hi <= b for a,b in ranges) for lo,hi in spans),
            "Verified target ranges do not cover exact image")
    return {"readback_verified":True,"readback_method":"RFP1.17 -pv target-memory comparison",
            "raw_memory_dump_exported":False,"verified_ranges":ranges,"programmer_log_sha256":digest(raw)}


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


def execute(m, source, image, ctx, facts):
    """Called under the existing hardware lock, after normal owner admission.

    Exactly one candidate programming attempt and one known-donor recovery
    attempt are allowed. Any capture failure still takes the recovery path.
    """
    from ael.adapters import prism_bench_trial as bench
    from ael.prism_native import run_session
    require(os.environ.get("K1_RFP_SWD_EXECUTE_OK") == "1", "Existing RFP root-owner execution gate required")
    pre = preflight(m,consume=True)
    logs = Path(ctx.logs_dir)
    facts.update(hardware_access=False, programmed=False, candidate_program_attempted=False,
                 candidate_readback_verified=False)
    started = time.monotonic()
    capture_deadline=started+80
    recovery_deadline=started+120
    facts.update(candidate_deadline_monotonic=capture_deadline,
                 recovery_deadline_monotonic=recovery_deadline)
    def write_json(name,obj):
        p=logs/name
        with p.open("x") as f: json.dump(obj,f,indent=2)
        return {"path":str(p.resolve()),"sha256":digest(p.read_bytes())}
    def program(candidate, name):
        nonlocal attempted
        cutoff=capture_deadline if name=='candidate' else recovery_deadline
        require(time.monotonic() < cutoff, name+" deadline before image validation")
        expected=m['image'] if name=='candidate' else m['recovery']['image']
        require(bench.bound_file(expected) == candidate.resolve(),"Programming image changed after admission")
        argv = bench.programmer_argv(m,candidate,"titan",recover=name=="donor-recovery")
        write_json(name+"-invocation.json",{"argv":argv,"image_sha256":bench.sha(candidate),
                    "identity":UID,"fixture_id":pre["fixture_id"],"invoked_unix":time.time()})
        log = logs/(name+".log")
        with log.open("xb") as out:
            remaining=cutoff-time.monotonic()
            require(remaining > 0, name+" deadline before programmer invocation")
            if name == "candidate":
                attempted=True
                facts.update(hardware_access=True, candidate_program_attempted=True)
            result = subprocess.run(argv,stdout=out,stderr=subprocess.STDOUT,check=False,
                                    timeout=min(30 if name=="candidate" else 35, remaining))
        evidence = verify_program_log(log.read_bytes(),returncode=result.returncode,argv=argv,
                                     image=candidate,spans=bench.hex_spans(candidate))
        bench.bound_file(expected)
        if name == "candidate":
            facts.update(programmed=True, candidate_readback_verified=True,
                         candidate_readback_method=evidence["readback_method"])
        evidence.update(identity=UID,image_sha256=bench.sha(candidate),readback_sha256=bench.sha(candidate),
                        source_binding_hash=m["source_binding_hash"] if name=="candidate" else
                        bench.TITAN_RECOVERY_BUILD,completed_unix=time.time(),
                        programmer_log={"path":str(log.resolve()),"sha256":digest(log.read_bytes())},
                        argv=argv,returncode=result.returncode,image_file=expected)
        event=write_json(name+"-programming-event.json",evidence)
        if name=='donor-recovery':
            facts.update(donor_recovery_event=event,known_donor_program_and_verify_completed=True)
        require(time.monotonic() <= cutoff, name+" deadline after programming/readback evidence")
        return event
    attempted=False
    try:
        anchor=usb_anchor(m["port"],deadline=capture_deadline)
        facts["donor_usb_anchor"]=anchor
        write_json("donor-usb-anchor.json",anchor)
        event=program(image,"candidate")
        resolved=wait_for_native_interface(anchor,capture_deadline)
        facts["native_usb_interface"]=resolved
        write_json("native-usb-interface.json",resolved)
        require_interface_unowned(resolved["device"],capture_deadline)
        remaining=capture_deadline-time.monotonic()
        require(remaining >= 1,"Candidate programming exhausted bounded interruption")
        completion = completion_request(m)
        operation=write_json("isolated-operation.json", {"completion": completion} if completion is not None else {"isolated_capture":{
            "frames":m["isolated_qualification"]["frames"],"budget_seconds":min(60,remaining),
            **({"pattern":m["isolated_qualification"]["pattern"]} if "pattern" in m["isolated_qualification"] else {}),
            **({"constant_timer_diagnostic":m["isolated_qualification"]["constant_timer_diagnostic"]} if "constant_timer_diagnostic" in m["isolated_qualification"] else {})}})
        runtime=dict(m,port=resolved["device"],isolated_programming_event=event,
                     isolated_fixture_id=pre["fixture_id"])
        result=run_session(runtime,logs,80,operation["path"],deadline=capture_deadline,
                           operation_sha256=operation["sha256"])
        facts["isolated_completion" if completion is not None else "isolated_capture"]=result
        require(time.monotonic() <= capture_deadline,"Capture exceeded recovery reserve")
        facts["candidate_programming_event"]=event
        facts["physical_qualification"]=False
    finally:
        if attempted:
            primary_error=sys.exc_info()[1]
            if primary_error is not None: facts["primary_error"]=str(primary_error)
            try:
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
