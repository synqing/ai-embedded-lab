from pathlib import Path
import hashlib, json, re, subprocess
SOURCE = Path("/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001")
OLD = SOURCE / "docs/emotiscope-port-001/evidence/arm-palette-003"
NEW = Path("/Users/spectrasynq/ai-embedded-lab/_scratch/lanes-titan-build/arm-palette-003-rebuild")
OUT = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
a = json.loads((OLD / "receipt.json").read_text())
b = json.loads((NEW / "receipt.json").read_text())
assert b["pass"] is True
assert a["build_id"] == b["build_id"]
assert a["sources"] == b["sources"]
source_mismatch = [k for k,v in b["sources"].items() if sha(SOURCE / (b["live_defaults"] if k == "external/live_defaults.json" else k)) != v]
assert not source_mismatch, source_mismatch
artifacts = {p.name: {"sha256":sha(p), "bytes":p.stat().st_size} for p in NEW.iterdir() if p.is_file()}
for k,v in b["artifacts"].items(): assert artifacts[k]["sha256"] == v, k
x=(OLD/"rtthread.elf").read_bytes(); y=(NEW/"rtthread.elf").read_bytes()
diff=[i for i,(u,v) in enumerate(zip(x,y)) if u!=v]
# The existing RT-Thread version banner embeds __DATE__ and __TIME__.
pattern = rb"[0-2][0-9]:[0-5][0-9]:[0-5][0-9]\x00\x00\x00\x00[A-Z][a-z]{2} [ 0-9][0-9] 20[0-9]{2}"
mx=list(re.finditer(pattern,x)); my=list(re.finditer(pattern,y))
assert len(mx)==len(my)==1
assert mx[0].span()==my[0].span()
start,end=mx[0].span()
assert len(x)==len(y) and all(start<=i<end for i in diff)
assert (OLD/"rtthread.map").read_bytes()==(NEW/"rtthread.map").read_bytes()
tracked=subprocess.check_output(["git","-C",str(SOURCE),"status","--porcelain","--untracked-files=no"],text=True)
assert tracked=="", tracked
head=subprocess.check_output(["git","-C",str(SOURCE),"rev-parse","HEAD"],text=True).strip()
assert head=="119ba2c498054fb0206e453cf38f6968222431c9"
result={"scope":"HOST fresh build and file readback only; no hardware access", "source_root":str(SOURCE),"head":head,"tracked_clean":True,"source_files":len(b["sources"]),"source_hashes_match_recorded_and_current":True,"build_id":b["build_id"],"recorded_receipt":str(OLD/"receipt.json"),"fresh_receipt":str(NEW/"receipt.json"),"binary_comparison":{"elf_equal":x==y,"changed_bytes":len(diff),"offsets":diff,"only_compile_banner_changed":True,"old_banner":mx[0].group().decode().replace(chr(0)," "),"new_banner":my[0].group().decode().replace(chr(0)," "),"map_equal":True},"artifacts":artifacts,"live_boot_brightness":b["live_boot_brightness"],"live_emit_default":b["live_emit_default"],"npu_enabled":b["npu"],"size":b["size"],"verification":"all assertions passed"}
(OUT/"build-summary.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2))
