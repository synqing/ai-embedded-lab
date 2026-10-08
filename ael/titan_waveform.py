"""Titan raw two-lane waveform verification. No declaration is physical proof.

The interchange stream is ASCII: TITAN-EDGES-1 followed by time_ns,A,B.
First and last rows are acquisition boundaries, all interior rows are transitions
on a shared instrument clock. Simultaneous edges occupy one row. No inferred
frame-count field is accepted. Raw acquisition provenance is a separate gate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time

VERSION = "titan-waveform/1"
UID = "545433931bd25436593630352d068363"
PRIMARY_SHA256 = "a9bf86bd23b324918456d39ff4f1e0e7e9a8220815da13605594b405ea41be96"
# Worldsemi WS2816C-1313 v1.1, 20210603, page4 (inner headings say B).
# Manufacturer-authored PDF mirrored by LCSC C5446703. Fitted applicability
# remains a separate physical prerequisite, not inferred from this filename.
REQUIREMENTS = {
    "part": "WS2816C-1313", "source_sha256": PRIMARY_SHA256,
    "source_url": "https://datasheet.lcsc.com/datasheet/pdf/2f9452c1f8bf5827b31560b2a8aff4ad.pdf?productCode=C5446703",
    "page": 4, "t0h_ns": [200, 320], "t1h_ns": [520, 800],
    "t0l_ns": [800, 1200], "t1l_ns": [480, 1000],
    "period_min_ns": 1250, "reset_min_ns_exclusive": 280000,
    "bits_per_lane": 3840, "frames_per_lane_min": 100,
    "order": "G15..G0,R15..R0,B15..B0; MSB-first",
    "max_edge_uncertainty_ns": 10,
    "uncertainty_policy_origin": "experiment guard, not manufacturer requirement; interval fully inside specified bounds",
}

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def bound(row):
    p = Path(row["path"])
    data = p.read_bytes()
    require(digest(data) == row["sha256"], "Changed bound artefact: " + str(p))
    return data

def parse_edges(raw):
    require(0 < len(raw) <= 100_000_000, "Empty or oversized raw capture")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise RuntimeError("Non-ASCII capture") from exc
    require(lines[0] == "TITAN-EDGES-1" and len(lines) >= 4, "Unknown/empty capture format")
    rows = []
    for line in lines[1:]:
        require(re.fullmatch(r"(?:0|[1-9][0-9]*),[01],[01]", line) is not None, "Malformed transition row")
        t, a, b = map(int, line.split(","))
        require(t <= 120_000_000_000, "Capture exceeds bounded120s window")
        require(not rows or t > rows[-1][0], "Nonmonotonic/duplicate timestamp")
        rows.append((t,a,b))
    require(rows[0] == (0,0,0), "Capture must start at known LOW on both physical lanes")
    require(rows[-1][1:] == (0,0), "Terminal held-HIGH")
    for before, after in zip(rows, rows[1:-1]):
        require(before[1:] != after[1:], "Redundant interior sample is not a transition")
    return rows

def parse_esp32jtag_instant(raw):
    """Strict decode of documented status-byte + big-endian16 sample format.

    This only decodes bytes; status semantics/timebase/readiness still require
    instrument firmware evidence. Never silently discard a trailing byte.
    """
    require(len(raw) >= 5 and len(raw) % 2 == 1, "Truncated ESP32JTAG capture")
    return raw[0], [x[0] for x in struct.iter_unpack(">H", raw[1:])]


def diagnostic_payload(frame, lane):
    """Independent host implementation of Kx pattern-set-v1; fixture-only.

    Never send these bytes to an attached product: frame1 is all ones.
    """
    require(type(frame) is int and 0 <= frame < 256 and lane in (0,1), "Invalid pattern identity")
    if frame < 3:
        return bytes([0 if frame==0 else 255 if frame==1 else (0xAA if lane==0 else 0x55)])*480
    x=(0x9e3779b9 ^ ((frame*0x85ebca6b)&0xffffffff) ^ ((lane*0xc2b2ae35)&0xffffffff))
    data=bytearray()
    for _ in range(480):
        x ^= (x<<13)&0xffffffff
        x ^= x>>17
        x ^= (x<<5)&0xffffffff
        data.append(x&255)
    boundary=(frame-3)%4
    data[0]=(data[0]&0x7f)|((boundary>>1)<<7)
    data[-1]=(data[-1]&0xfe)|(boundary&1)
    return bytes(data)

def expected_payloads(row):
    raw = bound(row)
    require(len(raw) >= 100*2*480 and len(raw) % 960 == 0, "Expected payload requires >=100 full pairs")
    require(len(raw)//960 <= 256, "Stimulus exceeds256 frames")
    expected=[[raw[i+j:i+j+480] for i in range(0,len(raw),960)] for j in (0,480)]
    require(all(p==diagnostic_payload(f,lane) for lane in (0,1) for f,p in enumerate(expected[lane])),
            "Expected payload does not match frozen pattern-set-v1")
    return expected

def verify_raw(raw, expected, uncertainty_ns=0):
    require(type(uncertainty_ns) in (int,float) and math.isfinite(uncertainty_ns)
            and 0 <= uncertainty_ns <= 10, "Unresolved/inadequate timebase uncertainty")
    rows = parse_edges(raw)
    require(len(expected) == 2 and len(expected[0]) == len(expected[1])
            and 100 <= len(expected[0]) <= 256, "Need100..256 frames on EACH lane")
    uncertainty = 2*uncertainty_ns
    def within(v, bounds):
        return bounds[0] <= v-uncertainty and v+uncertainty <= bounds[1]
    results=[]
    for lane in range(2):
        pulses=[]; rising=None; previous=0
        for t,a,b in rows[1:]:
            level=(a,b)[lane]
            if level != previous:
                if level:
                    rising=t
                else:
                    require(rising is not None, "Unpaired falling edge")
                    pulses.append((rising,t))
                    rising=None
                previous=level
        require(rising is None and pulses, "Empty/one-sided/held-HIGH capture")
        frames=[]; frame=[]; last_fall=0
        for rise,fall in pulses:
            low=rise-last_fall
            if low-uncertainty > REQUIREMENTS["reset_min_ns_exclusive"]:
                if frame: frames.append(frame)
                frame=[]
            elif not frame:
                raise RuntimeError("Missing initial reset LOW")
            frame.append((rise,fall))
            last_fall=fall
        frames.append(frame)
        require(rows[-1][0]-last_fall-uncertainty > REQUIREMENTS["reset_min_ns_exclusive"], "Truncated terminal reset LOW")
        require(len(frames) == len(expected[lane]), "Missing/extra frames on lane"+str(lane))
        payload_hashes=[]
        for index,pulses in enumerate(frames):
            require(len(pulses) == 3840, "Missing/extra bits in full3840-bit frame")
            require(len(expected[lane][index]) == 480, "Expected frame is not480 bytes")
            output=bytearray(480)
            for bit,(rise,fall) in enumerate(pulses):
                high=fall-rise
                candidates=[v for v in (0,1) if within(high,REQUIREMENTS[f"t{v}h_ns"])]
                require(len(candidates)==1, "HIGH pulse outside independent bounds/uncertain")
                value=candidates[0]
                output[bit//8] |= value << (7-bit%8)
                if bit+1 < len(pulses):
                    low=pulses[bit+1][0]-fall
                    require(within(low,REQUIREMENTS[f"t{value}l_ns"]), "LOW pulse outside independent bounds/uncertain")
                    require(pulses[bit+1][0]-rise-uncertainty >=1250, "Bit period too short/uncertain")
            require(bytes(output)==expected[lane][index], "Payload/order/physical-lane mismatch")
            payload_hashes.append(digest(output))
        results.append({"lane": "AB"[lane], "pin": ("P601","P604")[lane],
                        "frames":len(frames),"bits_per_frame":3840,"payload_sha256":payload_hashes,
                        "terminal_low_ns":rows[-1][0]-last_fall})
    return {"schema":"prism.titan.waveform-verdict.v1", "verifier":VERSION,
            "requirements_sha256":digest(json.dumps(REQUIREMENTS,sort_keys=True).encode()),
            "raw_sha256":digest(raw),"measured_waveform_pass":True,
            "physical_qualification":False,"provenance":"raw data alone does not establish physical acquisition",
            "duration_ns":rows[-1][0],"lanes":results}

def verify_manifest(manifest, candidate=None):
    require(manifest.get("schema")=="prism.titan.capture.v1", "Wrong capture manifest schema")
    require(manifest.get("identity")==UID, "Wrong capture UID")
    for field in ("image_sha256","source_commit","source_binding_hash","build_receipt_sha256"):
        require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(manifest.get(field,""))) is not None,"Missing identity binding: "+field)
    if candidate:
        for field,value in (("identity",candidate["identity"]),("image_sha256",candidate["image"]["sha256"]),
                            ("source_commit",candidate["source_commit"]),("source_binding_hash",candidate["source_binding_hash"]),
                            ("build_receipt_sha256",candidate["build_receipt"]["sha256"])):
            require(manifest[field]==value,"Capture/candidate mismatch: "+field)
    require(manifest.get("physical_pins")=={"A":"P601","B":"P604"},"Wrong physical pin mapping")
    require(manifest.get("requirements")==REQUIREMENTS,"Changed frozen timing requirements")
    event=json.loads(bound(manifest["programming_event"]))
    require(event.get("identity")==UID and event.get("image_sha256")==manifest["image_sha256"]
            and event.get("source_binding_hash")==manifest["source_binding_hash"]
            and event.get("readback_sha256")==manifest["image_sha256"]
            and event.get("readback_verified") is True,"Wrong image/program/readback binding")
    require(manifest.get("pattern_set")=="pattern-set-v1", "Unknown diagnostic pattern")
    for name in ("fixture_witness", "instrument_status", "acquisition_settings", "fitted_part_evidence"):
        bound(manifest[name])  # Binds original records; does not assert their truth.
    require(type(manifest.get("host_clock_uncertainty_ns")) in (int,float) and
            0 <= manifest["host_clock_uncertainty_ns"] <= 10000000, "Unbounded host clock uncertainty")
    start,end=manifest["acquisition_unix"]
    require(all(type(t) in (int,float) and math.isfinite(t) for t in (start,end)),"Invalid acquisition times")
    require(event["completed_unix"] <= start < end <= start+120,"Stale capture/program event ordering")
    require(0 <= time.time()-end <= 86400, "Stale/future acquisition")
    raw=bound(manifest["raw"])
    result=verify_raw(raw,expected_payloads(manifest["expected_payload"]),manifest["edge_uncertainty_ns"])
    require(abs((end-start)*1e9-result["duration_ns"]) <= manifest.get("host_clock_uncertainty_ns",0),"Capture time coverage mismatch")
    result.update(manifest_sha256=digest(json.dumps(manifest,sort_keys=True).encode()),
                  image_sha256=manifest["image_sha256"],identity=UID)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        result=verify_manifest(json.loads(a.manifest.read_text()))
    except (RuntimeError,ValueError,KeyError,OSError,TypeError) as exc:
        result={"measured_waveform_pass":False,"physical_qualification":False,"error":str(exc)}
    with a.output.open("x") as f:
        json.dump(result,f,indent=2); f.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k!="lanes"},sort_keys=True))
    return 0 if result["measured_waveform_pass"] else 1

if __name__=="__main__":
    raise SystemExit(main())
