"""Repair-session retention. Collector replies are framed fakes; no device is opened."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import time

import pytest

from ael import prism_native, titan_isolated as isolated, titan_replacement_observer as observer
from ael import titan_loopback as loop
from ael.adapters import prism_bench_trial as bench
from ael.titan_waveform import UID, digest
from test_titan_isolated import bind, fake_deployment_with_settings, mock_deployment, rfp_log
from test_titan_replacement_observer import Detector, info, packed

ORIGINAL_PREFLIGHT = isolated.preflight


@pytest.mark.parametrize("channel", range(4))
def test_leave_proof_refuses_actual_dmac_active_bit(tmp_path, monkeypatch, channel):
    m = _scope_manifest(tmp_path, monkeypatch)
    facts = _run(m, tmp_path, Framing(corrupt=True), [], monkeypatch)
    checkpoint = json.loads(Path(facts["repair_session_path"]).read_text())
    proof = json.loads(Path(checkpoint["leave_proof"]["path"]).read_text())
    raw = bytearray(Path(proof["cancel_raw"]["path"]).read_bytes())
    struct.pack_into("<I", raw, 4 * (72 + channel), 0x80)
    proof["cancel_raw"] = bind(tmp_path, "active-cancel.bin", bytes(raw))
    altered = bind(tmp_path, "active-leave.json", proof)
    with pytest.raises(RuntimeError, match="DMA ACT still set"):
        observer.revalidate_leave_proof(altered)


def _scope_manifest(tmp, monkeypatch):
    monkeypatch.setattr(isolated, "require_broker_capture_route", lambda manifest: None)
    monkeypatch.setattr(isolated.time, "time", lambda: 1000.)
    monkeypatch.setattr(bench, "require_titan_recovery", lambda m: {
        "exact_donor": "TEST ONLY", "build_source_sha256": bench.TITAN_RECOVERY_BUILD,
        "image_sha256": m["recovery"]["image"]["sha256"]})
    monkeypatch.setattr(bench, "hex_spans", lambda p: [(0x2000000, 0x2000010)])
    monkeypatch.setattr(bench, "recovery_programmed_spans", lambda m, image: [(0x2000000, 0x2000010)])
    monkeypatch.setenv("K1_RFP_SWD_EXECUTE_OK", "1")
    monkeypatch.setattr(bench, "deployment_argv", fake_deployment_with_settings)
    monkeypatch.setattr(isolated, "usb_anchor", lambda *a, **k: {"location": "TEST ONLY"})
    real = ORIGINAL_PREFLIGHT
    monkeypatch.setattr(isolated, "preflight", lambda m, consume=False: real(m, consume=consume, used_dir=tmp / "used"))
    owner = tmp / "owner.json"
    monkeypatch.setattr(prism_native, "OWNER_LEASE_PATH", owner)
    lease = bind(tmp, "owner.json", {"pid": os.getpid(), "task": "TEST ONLY"})
    image = bind(tmp, "candidate.hex", b"candidate test bytes")
    m = {"target": "titan-replacement", "identity": UID, "port": "/dev/cu.TEST-NO-HARDWARE",
         "source_binding_hash": "b" * 64, "source_commit": "c" * 40, "image": image,
         "build_receipt": {"sha256": "d" * 64}, "owner_lease": lease,
         "recovery": {"image": bind(tmp, "donor.hex", b"donor test bytes")},
         "isolated_qualification": {"operation": isolated.OPERATION, "backend": observer.BACKEND,
             "frames": 100, "pattern": 2, "maximum_interruption_seconds": 120,
             "repair_session": isolated.REPAIR_SESSION}}
    scope = isolated._scope(m)
    raw = bind(tmp, "actual-user-message.txt",
               b"TEST ONLY: first isolated bootstrap approved; jumpers installed and both product DIN feeds physically disconnected.")
    reviewed = bind(tmp, "reviewed.json", {"scope": scope})
    common = {"scope": scope, "actor": "Captain", "origin": "operator-message", "observed_unix": 999.,
              "original_message": raw, "message_reference": "TEST-ONLY-message-id", "exact_quote": "TEST ONLY:",
              "reviewed_request": reviewed, "fixture_id": "TEST-ONLY-fixture"}
    m["isolated_qualification"]["physical_confirmation"] = bind(tmp, "physical.json", dict(
        common, schema="prism.titan.physical-exclusion.v1", decision="physically-connected-and-product-excluded",
        physical_basis="operator-direct-inspection-of-disconnected-DIN-and-installed-jumpers",
        measurement_point="MCU-pads-P601-P604-3V3"))
    m["isolated_qualification"]["bootstrap_authority"] = bind(tmp, "authority.json", dict(
        common, schema="prism.titan.isolated-authority.v1", decision="first-isolated-bootstrap-readiness-exception",
        exception="candidate-detector-runtime-readiness-after-program-before-stimulus",
        decision_id="TEST-ONLY-once-id-0001"))
    return m


def _sealed_run(calls, root):
    def run(argv, stdout, timeout, **kw):
        name = "candidate" if argv[-1].endswith("candidate-programme") else "donor-recovery"
        calls.append(name)
        image = Path(root) / ("candidate.hex" if name == "candidate" else "donor.hex")
        stdout.write(b"gateway\n")
        programme = Path(argv[-1])
        programme.mkdir()
        inner = ["/opt/rfp-cli", "-d", "RA", "-t", "e2l:5AS079228B", "-if", "swd", "-s", "1000000",
                 "-noquery", "-run", "-range", "02000000,02c9f01f", "-pv", str(image)]
        (programme / "receipt.json").write_text(json.dumps({
            "pass": True, "execute": True, "returncode": 0, "uid": UID, "hex_sha256": digest(image.read_bytes()),
            "command": inner, "stdout": rfp_log(image).decode(), "stderr": ""}))
        Path(str(programme) + ".stdout").write_bytes(rfp_log(image))
        return type("R", (), {"returncode": 0})()
    return run


class Framing(Detector):
    """Real acquire transport. Optional one-shot data corruption after a full drain."""

    def __init__(self, *, corrupt=False, identity_fail=False, cancel_fail=False):
        super().__init__()
        self.payloads = []
        self.corrupt = corrupt
        self.identity_fail = identity_fail
        self.cancel_fail = cancel_fail
        self.identity_reads = 0

    def exchange(self, opcode, payload=b"", *, absolute_deadline=None):
        self.payloads.append((opcode, bytes(payload)))
        if opcode == observer.IDENTITY:
            self.identity_reads += 1
            if self.identity_fail and self.identity_reads > 1:
                bad = info(); bad["uid"] = "wrong"
                return json.dumps(bad).encode()
        if opcode == loop.CANCEL and self.cancel_fail:
            raise TimeoutError("cancel unconfirmed")
        raw = super().exchange(opcode, payload, absolute_deadline=absolute_deadline)
        if opcode == loop.DRAIN and self.corrupt:
            self.corrupt = False
            return raw[:-1] + bytes([raw[-1] ^ 0xFF])
        return raw


def _run(m, logs, detector, calls, monkeypatch, root=None):
    root = Path(m["image"]["path"]).parent if root is None else root
    mock_deployment(monkeypatch, _sealed_run(calls, root))
    facts = {}
    try:
        isolated.execute(m, logs, Path(m["image"]["path"]), type("C", (), {"logs_dir": logs})(), facts,
                         exchange_override=detector.exchange)
    except Exception as exc:
        facts["_error"] = exc
    return facts


def test_validation_failure_retains_exact_responsive_candidate_without_recovery(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []
    detector = Framing(corrupt=True)
    mock_deployment(monkeypatch, _sealed_run(calls, tmp_path))
    facts = {}
    try:
        isolated.execute(m, tmp_path, Path(m["image"]["path"]), type("C", (), {"logs_dir": tmp_path})(), facts,
                         exchange_override=detector.exchange)
    except Exception as exc:
        facts["_error"] = exc
    assert calls == ["candidate"]
    assert isinstance(facts["_error"], RuntimeError)
    assert "donor" not in str(facts["_error"]).lower() or facts.get("known_donor_program_and_verify_completed") is False
    assert facts["capture_result"] == "FAIL"
    assert facts["known_donor_program_and_verify_completed"] is False
    assert facts["recovery_deadline_monotonic"] is None
    checkpoint = json.loads((tmp_path / "repair-checkpoint.json").read_text())
    proof = observer.revalidate_leave_proof(checkpoint["leave_proof"])
    assert proof["classification"] == "capture_verification_failed"
    assert checkpoint["boot"] == proof["boot"] == 7
    assert checkpoint["fixture_epoch"] == proof["terminal_epoch"] == 1
    assert proof["identity"]["source_id"] == m["source_binding_hash"]
    assert (tmp_path / "replacement-loopback" / "leave-proof.consumed").is_file()
    arms = [struct.unpack("<4I", payload)[1] for op, payload in detector.payloads if op == loop.ARM]
    assert arms == [1]
    assert any(op == loop.CANCEL for op, _ in detector.payloads)


def test_repeat_arms_next_epoch_without_program_or_reset(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []
    detector = Framing(corrupt=True)
    first = _run(m, tmp_path, detector, calls, monkeypatch)
    original = (tmp_path / "repair-checkpoint.json").read_bytes()
    second_logs = tmp_path / "repeat"
    second_logs.mkdir()
    mock_deployment(monkeypatch, _sealed_run(calls, tmp_path))
    before = len(detector.payloads)
    facts = {}
    isolated.execute(m, second_logs, Path(m["image"]["path"]), type("C", (), {"logs_dir": second_logs})(), facts,
                     resume="capture", session_path=tmp_path / "repair-checkpoint.json",
                     session_sha256=first["repair_session_sha256"], epoch_lineage=1,
                     exchange_override=detector.exchange)
    assert calls == ["candidate"]
    assert (tmp_path / "repair-checkpoint.json").read_bytes() == original
    new_arms = [struct.unpack("<4I", payload)[1] for op, payload in detector.payloads[before:] if op == loop.ARM]
    assert new_arms == [2]
    assert not (second_logs / "donor-usb-anchor.json").exists()
    assert not (second_logs / "candidate-programme").exists()
    assert facts["reflash"] is False and facts["capture_result"] == "PASS"
    assert (second_logs / "repair-checkpoint.json").is_file()


def test_generic_broker_error_is_not_a_responsive_leave(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []
    mock_deployment(monkeypatch, _sealed_run(calls, tmp_path))

    def broken(*args, **kwargs):
        raise ValueError("Broker collector failed: synthetic")

    monkeypatch.setattr(prism_native, "run_session", broken)
    facts = {}
    with pytest.raises(ValueError, match="Broker collector failed"):
        isolated.execute(m, tmp_path, Path(m["image"]["path"]), type("C", (), {"logs_dir": tmp_path})(), facts)
    assert calls == ["candidate", "donor-recovery"]
    assert not (tmp_path / "repair-checkpoint.json").exists()


def test_programming_and_identity_failures_recover(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []

    def fail_program(argv, stdout, timeout, **kw):
        calls.append("candidate" if "candidate-programme" in argv[-1] else "donor-recovery")
        if calls[-1] == "candidate":
            stdout.write(b"gateway\n")
            return type("R", (), {"returncode": 7})()
        return _sealed_run(calls, tmp_path)(argv, stdout, timeout, **kw)

    # _sealed_run appends again; use a direct donor success instead.
    def run(argv, stdout, timeout, **kw):
        name = "candidate" if argv[-1].endswith("candidate-programme") else "donor-recovery"
        calls.append(name)
        stdout.write(b"gateway\n")
        if name == "candidate":
            return type("R", (), {"returncode": 7})()
        image = Path(stdout.name).parent / "donor.hex"
        programme = Path(argv[-1]); programme.mkdir()
        inner = ["/opt/rfp-cli", "-d", "RA", "-t", "e2l:5AS079228B", "-if", "swd", "-s", "1000000",
                 "-noquery", "-run", "-range", "02000000,02c9f01f", "-pv", str(image)]
        (programme / "receipt.json").write_text(json.dumps({"pass": True, "execute": True, "returncode": 0, "command": inner}))
        Path(str(programme) + ".stdout").write_bytes(rfp_log(image))
        return type("R", (), {"returncode": 0})()

    mock_deployment(monkeypatch, run)
    facts = {}
    with pytest.raises(RuntimeError):
        isolated.execute(m, tmp_path, Path(m["image"]["path"]), type("C", (), {"logs_dir": tmp_path})(), facts)
    assert calls == ["candidate", "donor-recovery"]
    assert facts["known_donor_program_and_verify_completed"] is True
    assert not (tmp_path / "repair-checkpoint.json").exists()


def test_identity_loss_recovers_and_unconfirmed_cancel_stops(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []
    facts = _run(m, tmp_path, Framing(corrupt=True, identity_fail=True), calls, monkeypatch)
    assert calls == ["candidate", "donor-recovery"]
    assert not (tmp_path / "repair-checkpoint.json").exists()
    calls.clear()
    logs = tmp_path / "cancel"
    logs.mkdir()
    m2 = _scope_manifest(logs, monkeypatch)
    facts = _run(m2, logs, Framing(corrupt=True, cancel_fail=True), calls, monkeypatch)
    assert calls == ["candidate"]
    assert facts["known_donor_program_and_verify_completed"] is False
    assert "quiesc" in facts["recovery_error"] or "cancel" in facts["recovery_error"]
    assert not (logs / "repair-checkpoint.json").exists()


def test_checkpoint_rejects_wrong_boot_tamper_and_stale_epoch(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []
    first = _run(m, tmp_path, Framing(corrupt=True), calls, monkeypatch)
    path = tmp_path / "repair-checkpoint.json"
    original = path.read_bytes()
    sha = first["repair_session_sha256"]
    tampered = tmp_path / "tampered.json"
    tampered.write_bytes(original + b" ")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        isolated._load_repair_session(tampered, sha, m)
    assert path.read_bytes() == original
    body = json.loads(original)
    body["boot"] = body["boot"] + 1
    wrong = tmp_path / "wrong-boot.json"
    wrong.write_text(json.dumps(body))
    with pytest.raises(RuntimeError, match="boot"):
        isolated._load_repair_session(wrong, digest(wrong.read_bytes()), m)
    assert path.read_bytes() == original
    body["image_sha256"] = "f" * 64
    body["boot"] = json.loads(original)["boot"]
    changed = tmp_path / "changed-image.json"
    changed.write_text(json.dumps(body))
    with pytest.raises(RuntimeError):
        isolated._load_repair_session(changed, digest(changed.read_bytes()), m)
    mock_deployment(monkeypatch, _sealed_run(calls, tmp_path))
    with pytest.raises(RuntimeError, match="Stale repair epoch"):
        isolated.execute(m, tmp_path / "stale", Path(m["image"]["path"]),
                         type("C", (), {"logs_dir": tmp_path / "stale"})(), {},
                         resume="capture", session_path=path, session_sha256=sha, epoch_lineage=0,
                         exchange_override=Framing().exchange)
    assert calls == ["candidate"]
    assert path.read_bytes() == original


def test_end_restores_original_settings_once(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    calls = []
    first = _run(m, tmp_path, Framing(corrupt=True), calls, monkeypatch)
    settings = json.loads((tmp_path / "repair-checkpoint.json").read_text())["prior_settings"]
    assert digest(Path(settings["path"]).read_bytes()) == settings["sha256"]
    end_logs = tmp_path / "end"
    end_logs.mkdir()
    mock_deployment(monkeypatch, _sealed_run(calls, tmp_path))
    facts = {}
    isolated.execute(m, end_logs, Path(m["image"]["path"]), type("C", (), {"logs_dir": end_logs})(), facts,
                     resume="end", session_path=tmp_path / "repair-checkpoint.json",
                     session_sha256=first["repair_session_sha256"])
    assert calls == ["candidate", "donor-recovery"]
    assert facts["repair_session_closed"] is True
    assert (tmp_path / "repair-checkpoint.json").read_bytes()
    (tmp_path / "end2").mkdir()
    with pytest.raises(RuntimeError, match="already started"):
        isolated.execute(m, tmp_path / "end-again", Path(m["image"]["path"]),
                         type("C", (), {"logs_dir": tmp_path / "end2"})(), {},
                         resume="end", session_path=tmp_path / "repair-checkpoint.json",
                         session_sha256=first["repair_session_sha256"])
    assert calls == ["candidate", "donor-recovery"]


def test_replayed_and_stale_grants_are_refused(tmp_path, monkeypatch):
    owner = tmp_path / "owner.json"
    monkeypatch.setattr(prism_native, "OWNER_LEASE_PATH", owner)
    lease = bind(tmp_path, "owner.json", {"pid": os.getpid(), "task": "TEST ONLY"})
    scope = {"repair_session": isolated.REPAIR_SESSION}
    facts = {"scope": scope, "fixture_id": "TEST ONLY"}
    monkeypatch.setattr(isolated, "preflight", lambda *a, **k: facts)
    event = bind(tmp_path, "event.json", {"test": True})
    manifest = {"target": "titan-replacement", "identity": prism_native.UID,
                "source_binding_hash": "b" * 64, "image": {"sha256": "c" * 64},
                "owner_lease": lease, "isolated_programming_event": event, "resident_epoch": 0}
    grant = {"kind": "replacement-isolated-v4",
             "scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
             "fixture_id": "TEST ONLY", "owner_lease_sha256": lease["sha256"],
             "expires_at": time.time() + 30, "epoch_lineage": 0}
    admission = {"uid": prism_native.UID, "build": "b" * 64, "hex_sha256": "c" * 64, "isolated_capture_grant": grant}
    current = {"uid": prism_native.UID, "build": "b" * 64, "protocol": "titan-native"}
    req = {"manifest": bind(tmp_path, "manifest.json", manifest),
           "operation": bind(tmp_path, "operation.json", {"isolated_capture": {}}),
           "output": str(tmp_path), "deadline": time.monotonic() + 20, "session": "test"}
    prism_native.validate_broker_capture(req, admission, current)
    with pytest.raises(FileExistsError):
        prism_native.validate_broker_capture(req, admission, current)
    fresh = copy.deepcopy(admission)
    fresh["isolated_capture_grant"]["epoch_lineage"] = 4
    manifest["resident_epoch"] = 0
    req["manifest"] = bind(tmp_path, "manifest-stale.json", manifest)
    with pytest.raises(ValueError, match="Stale or missing repair epoch"):
        prism_native.validate_broker_capture(req, fresh, current)
    fresh["isolated_capture_grant"]["epoch_lineage"] = 0
    current["uid"] = "wrong"
    req["manifest"] = bind(tmp_path, "manifest-uid.json", manifest)
    with pytest.raises(ValueError, match="mismatch"):
        prism_native.validate_broker_capture(req, fresh, current)


@pytest.mark.parametrize("backend", [observer.BACKEND, observer.PAIRED_BACKEND])
def test_hundred_epoch_verifier_keeps_acquisition_time_separate_from_epoch(tmp_path, monkeypatch, backend):
    monkeypatch.setattr(bench, "hex_spans", lambda p: [(0x2000000, 0x2000010)])
    image = bind(tmp_path, "candidate.hex", b":020000040000FA\n")
    programme = tmp_path / "candidate-programme"
    programme.mkdir()
    inner = ["/opt/rfp-cli", "-d", "RA", "-t", "e2l:5AS079228B", "-if", "swd", "-s", "1000000",
             "-noquery", "-run", "-range", "02000000,02c9f01f", "-pv", image["path"]]
    receipt_body = {"pass": True, "execute": True, "returncode": 0, "uid": UID, "hex_sha256": image["sha256"],
                    "command": inner, "stdout": rfp_log(Path(image["path"])).decode(), "stderr": ""}
    (programme / "receipt.json").write_text(json.dumps(receipt_body))
    event = {"identity": UID, "image_sha256": image["sha256"], "readback_sha256": image["sha256"],
             "readback_verified": True, "source_binding_hash": "b" * 64, "completed_unix": time.time(),
             "image_file": image, "argv": ["/bin/bash", "deploy_titan_image.sh"], "returncode": 0,
             "sealed_writer_receipt": {"path": str((programme / "receipt.json").resolve()),
                                       "sha256": digest((programme / "receipt.json").read_bytes())},
             "programme_directory": str(programme.resolve()),
             "programmer_log": bind(tmp_path, "gateway.log", b"gateway\n")}
    event_row = bind(tmp_path, "event.json", event)
    manifest = {"target": "titan-replacement", "identity": UID, "source_binding_hash": "b" * 64,
                "source_commit": "c" * 40, "image": image, "build_receipt": {"sha256": "d" * 64},
                "isolated_programming_event": event_row,
                "isolated_qualification": {"repair_session": isolated.REPAIR_SESSION, "frames": 100,
                                           "backend": backend}}
    if backend == observer.PAIRED_BACKEND:
        from test_titan_paired_capture import PairedDetector
        detector = PairedDetector()
    else:
        detector = Detector()
    out = tmp_path / "cap"
    out.mkdir()
    # A real host wall-clock step caused a prior full-run failure. Keep the
    # transaction chronology on the monotonic clock when wall time moves back.
    wall_anchor = event["completed_unix"] + .001
    wall_calls = [0]
    def stepped_wall():
        wall_calls[0] += 1
        return wall_anchor if wall_calls[0] == 1 else wall_anchor - 1
    monkeypatch.setattr(observer.time, "time", stepped_wall)
    identity = info()
    identity['capabilities']['isolated_raw_capture'] = backend
    acquired = observer.acquire(detector.exchange, manifest, {"frames": 100, "budget_seconds": 60, "start_epoch": 0},
                                out, identity, absolute_deadline=time.monotonic() + 60)
    verdict = observer.verify_acquisition(acquired, manifest)
    assert verdict["frames_each"] == 100 and verdict["raw_capture_consistent"] is True
    opened = acquired["acquisition_unix"][0]
    acquired["epochs"][0]["host_unix"] = [opened - 1, acquired["epochs"][0]["host_unix"][1]]
    with pytest.raises(RuntimeError, match="Stale/reordered"):
        observer.verify_acquisition(acquired, manifest)
    bare = dict(event)
    bare.pop("sealed_writer_receipt")
    bare.pop("programme_directory")
    with pytest.raises(RuntimeError, match="no bound sealed writer receipt"):
        observer.verify_replacement_program(bare, Path(image["path"]), [(0x2000000, 0x2000010)])
