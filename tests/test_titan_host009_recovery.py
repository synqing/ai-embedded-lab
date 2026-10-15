"""Host-only host009 recovery checks; semantic faults isolate only hash binding."""
import copy
import json
from pathlib import Path

import pytest
from ael.adapters import prism_bench_trial as bench

FIELDS = Path(__file__).resolve().parents[1] / "_scratch/packet_c_execution_20261016/host009-recovery-fields.REVIEW-ONLY.json"


@pytest.fixture
def manifest():
    if not FIELDS.is_file():
        pytest.skip("Retained real host009 evidence is not installed in this checkout")
    return json.loads(FIELDS.read_text())


def bind(path):
    return {"path": str(path), "sha256": bench.sha(path)}


def test_real_host009_ranged_bytes_and_historical_receipt(manifest):
    result = bench.require_titan_recovery(manifest)
    memory, _ = bench.recovery_hex_bytes(manifest["recovery"]["image"]["path"])
    assert len(memory) == 648792
    assert result["historical_source_verified_ranges"] == [[0x02000000, 0x0209E660]]
    assert result["derived_image_programmed"] is False
    assert result["image_sha256"] == "715156513a4ebcccdcd72c50c460378a37d7bd979b2478a10fb4f5d3aa86649b"


@pytest.mark.parametrize("key", ["source_image", "qualification_receipt"])
def test_wrong_bound_source_or_receipt_hash(manifest, key):
    manifest["recovery"][key]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="Missing or changed bound file"):
        bench.require_titan_recovery(manifest)


def test_wrong_uid(manifest):
    manifest["identity"] = "wrong"
    with pytest.raises(RuntimeError, match="Recovery wrong Titan UID"):
        bench.require_titan_recovery(manifest)


# Frozen expected semantic refusals; pin monkeypatches expose these exact checks.
RECEIPT_FAULTS = [
    ("probe", "e2l:WRONG", "Original programmer scope mismatch"),
    ("power", None, "Original programmer evidence mismatch"),
    ("verify_range", None, "Historical verified ranges do not cover derived recovery"),
    ("uid", "wrong", "Original programmed identity mismatch"),
    ("source", "wrong", "Original programmed identity mismatch"),
]


@pytest.mark.parametrize("fault,value,refusal", RECEIPT_FAULTS)
def test_receipt_semantic_fault(manifest, tmp_path, monkeypatch, fault, value, refusal):
    r = json.loads(Path(manifest["recovery"]["qualification_receipt"]["path"]).read_text())
    if fault == "power":
        r["stdout"] = r["stdout"].replace("Emulator power supply: OFF", "Emulator power supply: ON")
    elif fault == "verify_range":
        before, after = r["stdout"].split("Verifying data on the target device", 1)
        r["stdout"] = before + "Verifying data on the target device" + after.replace("0209E65F", "0209E64F")
    else:
        r[{"source": "source_pin"}.get(fault, fault)] = value
    p = tmp_path / "receipt.json"; p.write_text(json.dumps(r))
    manifest["recovery"]["qualification_receipt"] = bind(p)
    monkeypatch.setattr(bench, "TITAN_HOST009_RECOVERY_RECEIPT_SHA256", bench.sha(p))
    with pytest.raises(RuntimeError, match=refusal):
        bench.require_titan_recovery(manifest)


@pytest.mark.parametrize("fault", ["changed", "omitted"])
def test_derived_byte_equivalence_after_hash_isolation(manifest, tmp_path, monkeypatch, fault):
    rows = Path(manifest["recovery"]["image"]["path"]).read_text().splitlines()
    index = next(i for i, line in enumerate(rows) if bytes.fromhex(line[1:])[3] == 0)
    if fault == "omitted":
        rows.pop(index)
    else:
        record = bytearray.fromhex(rows[index][1:]); record[4] ^= 1
        record[-1] = (-sum(record[:-1])) & 255
        rows[index] = ":" + record.hex().upper()
    p = tmp_path / "image.hex"; p.write_text("\n".join(rows) + "\n")
    manifest["recovery"]["image"] = bind(p)
    monkeypatch.setattr(bench, "TITAN_HOST009_RECOVERY_HEX_SHA256", bench.sha(p))
    d = json.loads(Path(manifest["recovery"]["derivation"]["path"]).read_text())
    d["derived_sha256"] = bench.sha(p)
    dp = tmp_path / "derivation.json"; dp.write_text(json.dumps(d))
    manifest["recovery"]["derivation"] = bind(dp)
    monkeypatch.setattr(bench, "TITAN_HOST009_RECOVERY_DERIVATION_SHA256", bench.sha(dp))
    with pytest.raises(RuntimeError, match="Derived recovery must preserve every in-range byte"):
        bench.require_titan_recovery(manifest)


def test_changed_byte_fails_pinned_hash_before_semantics(manifest, tmp_path):
    p = tmp_path / "changed.hex"
    p.write_bytes(Path(manifest["recovery"]["image"]["path"]).read_bytes() + b"\n")
    manifest["recovery"]["image"] = bind(p)
    with pytest.raises(RuntimeError, match="Recovery must be exact known donor"):
        bench.require_titan_recovery(manifest)
