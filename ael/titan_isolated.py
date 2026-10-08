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
from ael.titan_loopback import BACKEND

JUMPERS = [["U18.7/P601", "U18.33/P603"], ["U18.12/P604", "U18.35/P602"]]
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
    return {"identity": UID, "image_sha256":m["image"]["sha256"],
            "source_binding_hash":m["source_binding_hash"], "source_commit":m["source_commit"],
            "build_receipt_sha256":m["build_receipt"]["sha256"],
            "recovery_sha256":TITAN_RECOVERY_HEX_SHA256,
            "jumpers":JUMPERS, "electrically_excluded":EXCLUSION,
            "operation":OPERATION, "frames":m["isolated_qualification"]["frames"],
            "maximum_interruption_seconds":120}


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
    if physical_freshness:
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
    request = json.loads(bound(r["reviewed_request"]))
    require(request.get("scope") == scope, "Operator reviewed a different request")
    return r


def preflight(m, *, consume=False, used_dir=None):
    q = m.get("isolated_qualification",{})
    require(q.get("operation") == OPERATION and q.get("backend") == BACKEND,
            "BLOCKED_CAPTURE_CAPABILITY: unsupported isolated backend")
    require(m.get("identity") == UID and m.get("target") == "titan-native", "Wrong isolated target")
    require(type(q.get("frames")) is int and 100 <= q["frames"] <= 120, "Need100..120 bounded frames")
    require(q.get("maximum_interruption_seconds") == 120, "Unbounded isolated interruption")
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
    def write_json(name,obj):
        p=logs/name
        with p.open("x") as f: json.dump(obj,f,indent=2)
        return {"path":str(p.resolve()),"sha256":digest(p.read_bytes())}
    def program(candidate, name):
        nonlocal attempted
        expected=m['image'] if name=='candidate' else m['recovery']['image']
        require(bench.bound_file(expected) == candidate.resolve(),"Programming image changed after admission")
        argv = bench.programmer_argv(m,candidate,"titan",recover=name=="donor-recovery")
        write_json(name+"-invocation.json",{"argv":argv,"image_sha256":bench.sha(candidate),
                    "identity":UID,"fixture_id":pre["fixture_id"],"invoked_unix":time.time()})
        log = logs/(name+".log")
        with log.open("xb") as out:
            if name == "candidate":
                attempted=True
                facts.update(hardware_access=True, candidate_program_attempted=True)
            result = subprocess.run(argv,stdout=out,stderr=subprocess.STDOUT,check=False,
                                    timeout=30 if name=="candidate" else 35)
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
        return write_json(name+"-programming-event.json",evidence)
    attempted=False
    try:
        event=program(image,"candidate")
        wait_for_interface(m["port"],capture_deadline)
        remaining=capture_deadline-time.monotonic()
        require(remaining >= 1,"Candidate programming exhausted bounded interruption")
        operation=write_json("isolated-operation.json",{"isolated_capture":{
            "frames":m["isolated_qualification"]["frames"],"budget_seconds":min(60,remaining)}})
        runtime=dict(m,isolated_programming_event=event,isolated_fixture_id=pre["fixture_id"])
        facts["isolated_capture"]=run_session(runtime,logs,80,operation["path"],deadline=capture_deadline)
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
                facts["known_donor_program_and_verify_completed"]=False
                facts["recovery_error"]=str(exc)
                write_json("recovery-failed.json",facts)
                raise
            finally:
                facts["interruption_elapsed_seconds"]=time.monotonic()-started
                facts["optical_leave_state_verified"]=False
                write_json("isolated-transaction.json",facts)
    require(facts["interruption_elapsed_seconds"] <= 120,"Interruption exceeded120s authority")
