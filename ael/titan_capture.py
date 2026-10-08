"""Isolated Titan qualification preflight and read-only analyser status.

No supported local instrument currently meets the complete-frame capture
contract. This module resolves that capability before any program/serial action;
it never transforms wiring declarations into observations.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlparse
import requests
from ael.titan_waveform import require, bound, verify_manifest, diagnostic_payload, digest

# Source: experiments/esp32jtag/port_d_loopback.py, 496us at132MHz.
# These are documentary capabilities, never a live instrument identity.
DOCUMENTED = {
 "esp32jtag-instant-v1": {"channels":16,"max_sample_rate_hz":264000000,
   "sample_depth_estimate":65536,"depth_basis":"AEL source comment496us at132MHz; actual firmware depth not locally available","raw_format":"status-byte+big-endian-u16",
   "read_only_endpoints":["/api/version","/la_status"],
   "complete_frame_backend":False,
   "reason":"65536 samples at>=100MHz cover<=655360ns; frame alone requires>=4800000ns. No documented lossless streaming/segmented full-frame backend."},
 "esp32-meter-v1": {"complete_frame_backend":False,
   "reason":"Digital aggregate/voltage API has no raw shared-clock edge acquisition."},
}

def capability(backend):
    require(backend in DOCUMENTED,"BLOCKED_CAPTURE_CAPABILITY: unsupported backend")
    result=dict(DOCUMENTED[backend])
    result["backend"]=backend
    result["status"]="BLOCKED_CAPTURE_CAPABILITY"
    result["required"]={"physical_channels":2,"max_edge_uncertainty_ns":10,
                         "minimum_frame_window_ns":5360001,"candidate_window_ns":5692000,"frames_each":100,
                         "minimum_contiguous_samples_at100MHz":536001}
    return result

def read_only_status(endpoint, *, timeout=3):
    """Explicit endpoint only; no historical IP default, discovery, or capture GET.

    Authentication is supplied by normal requests environment/netrc. Returned
    status is not readiness or physical wiring proof.
    """
    url=urlparse(endpoint)
    require(url.scheme=="https" and url.hostname and not url.username and
            not url.password and url.path in ("", "/") and not url.query and not url.fragment,
            "Explicit HTTPS instrument origin required")
    results={"endpoint":endpoint,"physical_readiness":False}
    for path in DOCUMENTED["esp32jtag-instant-v1"]["read_only_endpoints"]:
        response=requests.get(endpoint.rstrip("/")+path,timeout=timeout,allow_redirects=False)
        response.raise_for_status()
        require(response.status_code==200,"Unexpected instrument response")
        results[path]=response.json()
    return results

def isolated_preflight(m):
    q=m.get("isolated_qualification",{})
    require(q.get("operation")=="titan-isolated-waveform-v1", "Missing isolated qualification operation")
    # Evaluate real capability before asking for disruptive physical isolation.
    c=capability(q.get("backend"))
    require(c["complete_frame_backend"],c["status"]+": "+c["reason"])
    # Deliberately unreachable for current documentary backends. Adding a backend
    # requires implemented, tested physical isolation/readiness/program/readback/
    # capture/recovery operations, not toggling a metadata boolean.
    raise RuntimeError("BLOCKED_PHYSICAL_ISOLATION: no independently observed isolation interlock implementation")

def consume_output_proof(m, proof):
    require(proof.get("schema")=="prism.titan.output-qualification.v2","Wrong raw qualification schema")
    capture=json.loads(bound(proof["capture_manifest"]))
    result=verify_manifest(capture,m)
    require(capture.get("origin")=="physical-acquisition","Synthetic capture cannot qualify output")
    c=capability(capture.get("backend"))
    require(c["complete_frame_backend"],"BLOCKED_CAPTURE_CAPABILITY: "+c["reason"])
    # Raw waveform correctness is useful independently. Acquisition provenance
    # remains refused until an adequate, identified and isolated producer exists.
    raise RuntimeError("BLOCKED_PHYSICAL_ISOLATION: capture provenance is not an observed fixture")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    s=p.add_subparsers(dest="action",required=True)
    c=s.add_parser("patterns"); c.add_argument("--frames",type=int,default=120); c.add_argument("--output",type=Path,required=True)
    c=s.add_parser("capability"); c.add_argument("--backend",required=True)
    c=s.add_parser("status"); c.add_argument("--endpoint",required=True)
    c=s.add_parser("isolated-preflight"); c.add_argument("--manifest",type=Path,required=True)
    a=p.parse_args()
    try:
        if a.action=="patterns":
            require(100 <= a.frames <= 256, "Need100..256 diagnostic pairs")
            raw=b"".join(diagnostic_payload(frame,lane) for frame in range(a.frames) for lane in (0,1))
            with a.output.open("xb") as f: f.write(raw)
            result={"pattern_set":"pattern-set-v1", "frames_each":a.frames,"expected_payload_sha256":digest(raw),
                    "physical_qualification":False,"warning":"Fixture-only; all-ones frame must never reach product strip"}
        elif a.action=="capability":
            result=capability(a.backend)
        elif a.action=="status":
            result=read_only_status(a.endpoint)
        else:
            result=isolated_preflight(json.loads(a.manifest.read_text()))
        print(json.dumps(result,indent=2)); return 2 if result.get("status","").startswith("BLOCKED") else 0
    except (RuntimeError,KeyError,ValueError,OSError,TypeError,requests.RequestException) as exc:
        print(json.dumps({"ok":False,"hardware_mutated":False,"error":str(exc)})); return 2

if __name__=="__main__": raise SystemExit(main())
