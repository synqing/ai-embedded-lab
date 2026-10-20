"""Host checks for native and legacy deployment admission. No hardware, no deploy script."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HELPER = Path("/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts/deploy_admission.py")
SPEC = importlib.util.spec_from_file_location("deploy_admission", HELPER)
admission = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admission)

UID = admission.UID
V4 = "92eee4ff5334b37d91c80873b4ed71b5204869ea6840efcfe9254eebec7a9281"
HOST009 = "715156513a4ebcccdcd72c50c460378a37d7bd979b2478a10fb4f5d3aa86649b"


def legacy_tree(tmp: Path):
    build = tmp / "build"
    build.mkdir()
    (build / "rtthread.hex").write_bytes(b"HEX")
    (build / "rtthread.elf").write_bytes(b"ELF-build-id-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    receipt = {
        "pass": True,
        "build_id": "a" * 64,
        "source_pin": "b" * 40,
        "artifacts": {
            "rtthread.hex": admission.sha256_file(build / "rtthread.hex"),
            "rtthread.elf": admission.sha256_file(build / "rtthread.elf"),
        },
        "live_schema": {"sha256": "c" * 64},
    }
    # The sealed writer requires the build id bytes inside the ELF.
    (build / "rtthread.elf").write_bytes(b"ELF" + receipt["build_id"].encode())
    (build / "receipt.json").write_text(json.dumps(receipt))
    admitted = {
        "uid": UID,
        "build": receipt["build_id"],
        "schema_sha256": "c" * 64,
        "hex_sha256": receipt["artifacts"]["rtthread.hex"],
        "elf_sha256": admission.sha256_file(build / "rtthread.elf"),
        "ops": ["emotiscope_get", "emotiscope_patch"],
    }
    # ELF hash changed after the first write. Recompute and store the final bytes.
    receipt["artifacts"]["rtthread.elf"] = admission.sha256_file(build / "rtthread.elf")
    admitted["elf_sha256"] = receipt["artifacts"]["rtthread.elf"]
    (build / "receipt.json").write_text(json.dumps(receipt))
    path = tmp / "admission.json"
    path.write_text(json.dumps(admitted))
    return build, path, receipt


def healthy():
    return {
        "titan_usb": True,
        "broker_log_age_s": 1,
        "frames_per_s": 100,
        "target": {"uid": UID, "latched_frames": 10, "led_faults": 0},
        "launchd": {"com.spectrasynq.titan-broker": {"loaded": True, "state": "running"}},
        "controller": {
            "ready": True,
            "confirmed": True,
            "emission_enabled": True,
            "output_brightness": 100,
            "blockers": [{"code": "no_mixer"}],
        },
    }


def test_legacy_prepare_keeps_original_build_and_emotiscope_ops(tmp_path):
    build, admitted, receipt = legacy_tree(tmp_path)
    binding = admission.prepare(build, admitted, tmp_path / "view")
    assert binding["protocol"] == "legacy"
    assert binding["writer_build"] == str(build.resolve())
    assert binding["build_id"] == receipt["build_id"]
    assert not (tmp_path / "view").exists()


def test_legacy_admission_refuses_hash_mismatch_and_missing_ops(tmp_path):
    build, admitted, _receipt = legacy_tree(tmp_path)
    row = json.loads(admitted.read_text())
    row["hex_sha256"] = "d" * 64
    admitted.write_text(json.dumps(row))
    with pytest.raises(admission.Refusal, match="hash"):
        admission.prepare(build, admitted, tmp_path / "view")
    row["hex_sha256"] = json.loads((build / "receipt.json").read_text())["artifacts"]["rtthread.hex"]
    row["ops"] = ["native_identity"]
    admitted.write_text(json.dumps(row))
    with pytest.raises(admission.Refusal, match="emotiscope"):
        admission.prepare(build, admitted, tmp_path / "view")


def test_native_prepare_projects_real_bytes_and_refuses_emotiscope_ops(tmp_path):
    profile = "4" * 64
    core = "0b6d1fb7f9a22a951818c1508b3de9ca289f4bdf"
    build = tmp_path / "native"
    build.mkdir()
    (build / "titan-native.hex").write_bytes(b"NATIVE")
    (build / "titan-native.elf").write_bytes(b"elf" + profile.encode() + core.encode())
    receipt = {
        "exit_code": 0,
        "build_profile": "titan-replacement",
        "development_core": False,
        "schema": "prism-product-build.v1",
        "source_profile_sha256": profile,
        "core_commit": core,
        "core_tag": "v0.12.0-rc.2",
        "artefacts": {
            "titan-native.hex": admission.sha256_file(build / "titan-native.hex"),
            "titan-native.elf": admission.sha256_file(build / "titan-native.elf"),
        },
    }
    (build / "receipt.json").write_text(json.dumps(receipt))
    row = {
        "protocol": "titan-native",
        "uid": UID,
        "build": profile,
        "schema_sha256": admission.HEALTH_SCHEMA,
        "health_schema": admission.HEALTH_SCHEMA,
        "identity_opcode": admission.IDENTITY_OPCODE,
        "health_opcode": admission.HEALTH_OPCODE,
        "hex_sha256": receipt["artefacts"]["titan-native.hex"],
        "elf_sha256": receipt["artefacts"]["titan-native.elf"],
        "ops": ["native_identity", "native_health", "native_status", "native_scene", "native_global", "native_durable", "native_durable_read"],
    }
    admitted = tmp_path / "native-admission.json"
    admitted.write_text(json.dumps(row))
    binding = admission.prepare(build, admitted, tmp_path / "view")
    projected = json.loads((tmp_path / "view" / "receipt.json").read_text())
    assert binding["protocol"] == "native"
    assert projected["build_id"] == profile
    assert projected["artifacts"]["rtthread.hex"] == receipt["artefacts"]["titan-native.hex"]
    assert (tmp_path / "view" / "rtthread.hex").read_bytes() == b"NATIVE"
    row["ops"] = ["emotiscope_get", "emotiscope_patch"]
    admitted.write_text(json.dumps(row))
    with pytest.raises(admission.Refusal, match="native admission"):
        admission.prepare(build, admitted, tmp_path / "again")
    assert not (tmp_path / "again").exists()


def test_current_show_and_host009_are_not_added_to_pinned_recovery():
    show = admission.CURRENT_SHOW_RECOVERY
    assert show[0].startswith("aadd38b2")
    assert show[1] != V4
    assert not admission.recovery_allowed(*show)
    assert not admission.current_show_recovery("a" * 64, V4, "b" * 64, "c" * 40, "d" * 64)
    assert admission.current_show_recovery(*show)
    assert not admission.current_show_recovery("a" * 64, V4, "b" * 64, "c" * 40, "d" * 64)
    assert not admission.recovery_allowed("a" * 64, V4, "b" * 64, "c" * 40, "d" * 64)
    assert not admission.recovery_allowed("a" * 64, HOST009, "b" * 64, "c" * 40, "d" * 64)
    assert admission.recovery_allowed(
        "becb0186f0a66fbb04b0e0f4a79c0480b8b963db0fe3f518a91af9bb2dd2b5c7",
        "df7a33785ac2a12b01e5065722ba9ce8bb758802e1bbd0d78e4bfc92007dd776",
        "97923cbb8ff0b7ea80548e775b68765475da87b583d5b08a2683016e62a2b6e3",
        "7f86939bd7c16c4a6dd5789813e9d551246ed134",
        "e40f6598e57c9493de6f3e6d19935d404d9f5cdbb35c064770fe365ad476a0bb",
    )


def client_health():
    return {
        "identity": {
            "uid": UID,
            "controls_persistent": False,
            "capabilities": {"controls": "replacement-control-v1", "health": admission.HEALTH_SCHEMA},
        },
        "boot": 4,
        "snapshot": {
            "schema": admission.HEALTH_SCHEMA,
            "snapshot_us": 20_000_000,
            "boot_id": 4,
            "physical_qualified": False,
            "startup": {"ready": 1, "failures": 0, "last_driver_error": 0},
            "capture": {"errors": [0, 0]},
            "output": {
                "completed_count": 12,
                "completed": {"sequence": 12},
                "first_fault": 0,
                "failures": 0,
                "last_completed_us": 19_500_000,
            },
        },
        "interpretation": "Software observation only; no physical qualification",
    }


def test_preflight_legacy_and_native_client_document_and_absent_usb():
    admission.check_preflight(healthy(), UID)
    dead = healthy()
    dead["frames_per_s"] = 0
    with pytest.raises(admission.Refusal, match="advancing"):
        admission.check_preflight(dead, UID)
    absent = {"titan_usb": False}
    with pytest.raises(admission.Refusal) as caught:
        admission.check_preflight(absent, UID)
    assert caught.value.code == 3
    flat = {"protocol": "titan-native", "completed_frames": 9, "startup": {}, "output": {}, "physical_qualified": False}
    with pytest.raises(admission.Refusal, match="client health"):
        admission.check_preflight(flat, UID)
    document = client_health()
    produced = admission.native_preflight_from_client(document, UID)
    assert produced["faults"] == 0 and produced["completed_count"] == 12 and produced["physical_qualified"] is False
    document["snapshot"]["startup"] = {}
    with pytest.raises(admission.Refusal, match="ready"):
        admission.native_preflight_from_client(document, UID)
    document = client_health()
    document["snapshot"]["output"]["first_fault"] = 1
    with pytest.raises(admission.Refusal, match="fault"):
        admission.native_preflight_from_client(document, UID)
    document = client_health()
    document["snapshot"]["output"]["last_completed_us"] = 1
    with pytest.raises(admission.Refusal, match="fresh"):
        admission.native_preflight_from_client(document, UID)
    show = admission.produce_preflight(healthy(), None, "native")
    assert show["kind"] == "legacy-show"
    with pytest.raises(admission.Refusal, match="show health"):
        admission.produce_preflight(None, {"samples": [client_health(), client_health()]}, "native")
    first, second = client_health(), client_health()
    second["snapshot"]["output"]["completed_count"] = 13
    second["snapshot"]["output"]["completed"]["sequence"] = 13
    second["snapshot"]["output"]["last_completed_us"] = 20_000_000
    second["snapshot"]["snapshot_us"] = 20_100_000
    with pytest.raises(admission.Refusal, match="two health samples"):
        admission.produce_preflight({"titan_usb": True}, client_health(), "legacy")
    running = admission.produce_preflight({"titan_usb": True}, {"samples": [first, second]}, "legacy")
    assert running["code"] == 4
    second["snapshot"]["output"]["completed_count"] = 12
    with pytest.raises(admission.Refusal, match="did not advance"):
        admission.native_advancing(first, second, UID)


def test_identity_and_restoration(tmp_path):
    info = tmp_path / "handoff-info.json"
    info.write_text(json.dumps({"info": {"uid": UID, "build": "a" * 64, "schema_sha256": "c" * 64}}))
    assert admission.legacy_identity_line(info, "a" * 64, "c" * 64) == "MATCH"
    assert admission.legacy_identity_line(info, "b" * 64, "c" * 64).startswith("MISMATCH")
    assert admission.legacy_identity_line(tmp_path / "missing.json", "a" * 64, "c" * 64).startswith("MISMATCH no-info")
    plan = admission.restoration_plan(0, False)
    assert plan["write_began"] is True and plan["firmware_rolled_back"] is False
    assert plan["restore_broker_on_previous_admission"] is True
    failed = admission.restoration_plan(2, False)
    assert failed["write_began"] == "unverified"


def test_both_write_legs_bind_image_bytes_before_the_gateway(tmp_path):
    from ael.adapters import prism_bench_trial as bench

    build, admitted, _receipt = legacy_tree(tmp_path)
    image = build / "rtthread.hex"
    manifest = {"deployment": {"build_dir": str(build), "admission": str(admitted)},
                "recovery": {"deployment": {"build_dir": str(build), "admission": str(admitted)}}}
    for name in ("candidate", "donor-recovery"):
        argv = bench.deployment_argv(manifest, image, name, tmp_path / (name + "-programme"))
        assert argv[0] == "/bin/bash" and argv[1].endswith("deploy_titan_image.sh")
        assert "--recover-known-image" not in argv
        assert argv[2] == str(build.resolve())
    wrong = tmp_path / "other.hex"
    wrong.write_bytes(b"not-the-receipt-image")
    with pytest.raises(RuntimeError, match="image bytes"):
        bench.deployment_argv(manifest, wrong, "candidate", tmp_path / "unused-programme")
    (tmp_path / "candidate-programme").mkdir()
    with pytest.raises(RuntimeError, match="must not exist"):
        bench.deployment_argv(manifest, image, "candidate", tmp_path / "candidate-programme")


def _serve(sock_path, replies):
    import socket
    import threading
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.settimeout(3)
    server.bind(str(sock_path))
    server.listen(1)
    received, errors = [], []

    def run():
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(3)
                for op, reply in replies.items():
                    buf = b""
                    while b"\n" not in buf:
                        chunk = conn.recv(4096)
                        if not chunk:
                            return  # Expected when the client refuses an earlier reply.
                        buf += chunk
                    request = json.loads(buf)
                    expected = {"op": op}
                    if op != "hello":
                        expected["session"] = "s"
                    assert request == expected, (request, expected)
                    received.append(op)
                    conn.sendall((json.dumps(reply) + "\n").encode())
        except Exception as exc:
            errors.append(exc)
        finally:
            server.close()
            sock_path.unlink(missing_ok=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.received, thread.errors = received, errors
    thread.start()
    return thread


def test_pull_broker_health_cli_uses_the_socket(tmp_path):
    import copy
    import subprocess
    import tempfile

    good = {
        "hello": {"ok": True, "session": "s", "bound": {
            "uid": admission.UID, "build": "a" * 64, "protocol": "titan-native"}},
        "native_identity": {"ok": True, "identity": {"uid": admission.UID, "source_id": "a" * 64}},
        "native_health": {"ok": True, "faults": 0, "completed_count": 4, "boot": 3},
        "native_status": {"ok": True, "boot": 3, "target_matches": True},
    }
    # Unix sockets have a short pathname limit; this owned directory avoids both
    # long pytest paths and deleting another test's socket before binding.
    with tempfile.TemporaryDirectory(prefix="tbh-", dir="/tmp") as directory:
        sock = Path(directory) / "broker.sock"
        thread = _serve(sock, good)
        out = tmp_path / "health.json"
        ok = subprocess.run(
            [sys.executable, str(HELPER), "pull-broker-health", "--socket", str(sock),
             "--uid", admission.UID, "--out", str(out)], capture_output=True, text=True, timeout=5,
        )
        thread.join(4)
        assert not thread.is_alive() and not thread.errors, thread.errors
        assert ok.returncode == 0, ok.stderr
        assert thread.received == list(good)
        saved = json.loads(out.read_text())
        assert saved["protocol"] == "native"
        assert saved["bound"] == good["hello"]["bound"]

        assert saved["broker_health"]["completed_count"] == 4
        assert saved["broker_status"]["boot"] == saved["broker_health"]["boot"] == 3
        assert saved["broker_status"]["target_matches"] is True
        # Actual SMC JSON always has legacy-shaped keys even while native runs.
        smc=healthy();smc['controller']['ready']=False;smc['frames_per_s']=None
        smc['target']['build']='a'*64
        smc_path=tmp_path/'native-era-smc.json';smc_path.write_text(json.dumps(smc))
        selected=subprocess.run([sys.executable,str(HELPER),'produce-preflight',
            '--smc',str(smc_path),'--native',str(out),'--installing','legacy'],capture_output=True,text=True,timeout=5)
        assert selected.returncode==4, selected.stderr
        assert json.loads(selected.stdout)['kind']=='native-running'
        with pytest.raises(admission.Refusal):admission.produce_preflight(smc,saved,'native')
        assert admission.produce_preflight(smc,saved,'native',repair_update=True)['code']==4
        update_selected=subprocess.run([sys.executable,str(HELPER),'produce-preflight',
            '--smc',str(smc_path),'--native',str(out),'--installing','native','--repair-update'],
            capture_output=True,text=True,timeout=5)
        assert update_selected.returncode==4, update_selected.stderr
        for area,key,value in [('bound','uid','wrong'),('broker_health','faults',1),
                ('broker_health','completed_count',0),('broker_health','cached',True),
                ('broker_status','boot',4),('broker_status','target_matches',False)]:
            bad=copy.deepcopy(saved);bad[area][key]=value
            with pytest.raises(admission.Refusal):admission.produce_preflight(smc,bad,'legacy')
            with pytest.raises(admission.Refusal):admission.produce_preflight(smc,bad,'native',repair_update=True)

        cases = [
            ("hello", ("bound", "uid"), "wrong", "UID", ["hello"]),
            ("hello", ("bound", "protocol"), "legacy", "protocol", ["hello"]),
            ("native_identity", ("identity", "source_id"), "b" * 64, "identity", list(good)[:2]),
            ("native_status", ("boot",), 4, "target/boot", list(good)),
            ("native_status", ("target_matches",), False, "target/boot", list(good)),
        ]
        for op, keys, value, reason, expected_requests in cases:
            bad = copy.deepcopy(good)
            row = bad[op]
            for key in keys[:-1]:
                row = row[key]
            row[keys[-1]] = value
            thread = _serve(sock, bad)
            refused = subprocess.run(
                [sys.executable, str(HELPER), "broker-ready", "--socket", str(sock),
                 "--uid", admission.UID, "--build", "a" * 64, "--protocol", "native"],
                capture_output=True, text=True, timeout=5,
            )
            thread.join(4)
            assert not thread.is_alive() and not thread.errors, thread.errors
            assert refused.returncode == 1, refused.stderr
            assert reason in refused.stderr
            assert thread.received == expected_requests


def test_shell_sigterm_does_not_execute_the_writer(tmp_path):
    """Run the real trap in a temporary tree with no production boundary reachable."""
    import os
    import re
    import shutil
    import signal
    import subprocess
    import time

    build, admitted, receipt = legacy_tree(tmp_path)
    scripts = HELPER.parent
    isolated = tmp_path / "deployment"
    isolated.mkdir()
    firmware = tmp_path / "firmware"
    (firmware / "scripts").mkdir(parents=True)
    (firmware / "tools" / "serial-studio").mkdir(parents=True)
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    ready, release = tmp_path / "bootout-ready", tmp_path / "bootout-release"
    calls, launch_calls = tmp_path / "writer-calls.txt", tmp_path / "launch.txt"
    plist = tmp_path / "broker.plist"
    plist.write_text("test-owned service file\n")

    def executable(path, body):
        path.write_text(body)
        path.chmod(0o755)

    # The PATH contains only reviewed, inert utilities and test-owned boundaries.
    for command in ("dirname", "basename", "id", "date", "shasum", "awk", "mkdir",
                    "tee", "seq", "sleep", "cat", "rm", "cp", "ls"):
        resolved = shutil.which(command)
        assert resolved, command
        (stub_dir / command).symlink_to(resolved)
    (stub_dir / "python3").symlink_to(sys.executable)
    fail = "#!/bin/sh\necho 'unexpected isolated boundary' >&2\nexit 97\n"
    for command in ("PlistBuddy", "rfp-cli", "ioreg", "zsh"):
        executable(stub_dir / command, fail)
    executable(stub_dir / "plutil", "#!/bin/sh\nexit 0\n")
    executable(stub_dir / "pgrep", "#!/bin/sh\nexit 1\n")
    executable(stub_dir / "launchctl", f'''#!{sys.executable}
import pathlib, sys, time
root = pathlib.Path({str(tmp_path)!r})
with (root / 'launch.txt').open('a') as stream:
    stream.write(' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'bootout':
    (root / 'bootout-ready').write_text('ready')
    deadline = time.monotonic() + 8
    while not (root / 'bootout-release').exists():
        if time.monotonic() >= deadline:
            raise SystemExit(98)
        time.sleep(0.01)
elif sys.argv[1] not in ('bootstrap', 'print'):
    raise SystemExit(97)
''')
    writer = firmware / "scripts" / "programme_rfp_swd.py"
    writer.write_text(f"import sys\nfrom pathlib import Path\n"
                      f"with Path({str(calls)!r}).open('a') as stream:\n"
                      "    stream.write(' '.join(sys.argv[1:]) + '\\n')\n"
                      "raise SystemExit(99 if '--execute' in sys.argv else 0)\n")
    (isolated / "smc_titan.py").write_text("import sys\nassert '--observe-only' in sys.argv\nprint('{}')\n")
    # Import-only serial shim also makes any accidental serial access fail closed.
    (isolated / "serial.py").write_text("def Serial(*args, **kwargs):\n    raise RuntimeError('serial forbidden')\n")
    for target in (isolated / "replacement_client.py",
                   firmware / "tools" / "serial-studio" / "titan_broker.py"):
        target.write_text("raise RuntimeError('device access forbidden')\n")
    executable(isolated / "noattach_cycle.sh", fail)
    prepared = {
        "build_id": receipt["build_id"], "hex_sha256": receipt["artifacts"]["rtthread.hex"],
        "elf_sha256": receipt["artifacts"]["rtthread.elf"], "source": receipt["source_pin"],
        "schema": receipt["live_schema"]["sha256"], "protocol": "legacy", "writer_build": str(build),
    }
    prior = {"PRIOR_BUILD": receipt["build_id"], "PRIOR_PROTOCOL": "legacy",
             "SAVED_ADMISSION_SOURCE": str(admitted), "SAVED_ADMISSION_SHA": admission.sha256_file(admitted)}
    (isolated / "deploy_admission.py").write_text(
        "import sys\n"
        f"prepared = {prepared!r}\n"
        "if sys.argv[1] == 'prepare':\n"
        "    import shlex\n"
        "    print('\\n'.join(key + '=' + shlex.quote(value) for key, value in prepared.items()))\n"
        "elif sys.argv[1] == 'prior-binding':\n"
        "    import shlex\n"
        f"    print('\\n'.join(key + '=' + shlex.quote(value) for key, value in {prior!r}.items()))\n"
        "elif sys.argv[1] == 'capture-settings':\n"
        "    import hashlib\n"
        "    from pathlib import Path\n"
        "    target = Path(sys.argv[sys.argv.index('--file') + 1])\n"
        "    target.write_text('{\"test_only\":\"isolated original controls\"}')\n"
        "    print(hashlib.sha256(target.read_bytes()).hexdigest())\n"
        "elif sys.argv[1] not in ('produce-preflight', 'bind-writer', 'broker-ready', 'restore-settings'):\n"
        "    raise SystemExit('unexpected isolated admission command: ' + sys.argv[1])\n"
    )
    replacements = {
        "/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001": str(firmware),
        "~/Library/LaunchAgents/com.spectrasynq.titan-broker.plist": str(plist),
        "/usr/libexec/PlistBuddy": str(stub_dir / "PlistBuddy"),
        "/Users/spectrasynq/Applications/Renesas/RFP_CLI_V3.24.00/rfp-cli": str(stub_dir / "rfp-cli"),
        "/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/scripts/replacement_client.py": str(isolated / "replacement_client.py"),
        "/dev/cu.usbmodem00000000000011": str(tmp_path / "absent-device"),
        "/tmp/titan-emotiscope-control/titan-control.sock": str(tmp_path / "no-socket"),
        "/opt/homebrew/opt/python@3.14/bin/python3.14": sys.executable,
        "/opt/homebrew/opt/python@3.13/bin/python3.13": sys.executable,
    }
    for name in ("deploy_titan_image.sh", "deploy_restore.sh"):
        source = (scripts / name).read_text()
        for original, replacement in replacements.items():
            source = source.replace(original, replacement)
        # Fail before Popen if a new absolute host/device boundary appears.
        inspected = source.replace(str(tmp_path), "TEST_ROOT").replace(sys.executable, "TEST_PYTHON")
        assert not re.search(r"/(?:Users|usr|opt|Library|tmp|var)/|/dev/(?!null(?:\W|$))", inspected), inspected
        absolute_paths = re.findall(r"(?:[\s\"'=:\[])(/[\w.@+-]+(?:/[\w.@+-]+)*)", inspected)
        assert set(absolute_paths) <= {"/bin/bash", "/dev/null"}, absolute_paths
        assert "~/" not in inspected
        (isolated / name).write_text(source)
    assert (isolated / "deploy_restore.sh").is_file()
    assert all(path.is_relative_to(tmp_path) for path in (isolated, firmware, plist, writer, stub_dir))
    assert "trap on_term TERM" in (isolated / "deploy_titan_image.sh").read_text()
    assert "exit 143" in (isolated / "deploy_restore.sh").read_text()
    env = {"PATH": str(stub_dir), "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "TITAN_DEPLOY_PYTHON": sys.executable, "PYTHONPATH": str(isolated),
           "PYTHONNOUSERSITE": "1"}
    out = tmp_path / "programme-out"
    proc = None
    with (tmp_path / "shell-output.txt").open("w+") as output:
        try:
            proc = subprocess.Popen(
                ["/bin/bash", str(isolated / "deploy_titan_image.sh"), str(build), str(admitted), str(out)],
                cwd=tmp_path, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            )
            deadline = time.monotonic() + 8
            while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            output.flush()
            assert ready.exists(), (tmp_path / "shell-output.txt").read_text()
            # Bash defers its trap while the foreground fake bootout waits. Queue
            # TERM first, then release exactly that child: no blind sleep race.
            proc.send_signal(signal.SIGTERM)
            release.write_text("release")
            code = proc.wait(timeout=8)
        finally:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=3)
    assert code == 143, (tmp_path / "shell-output.txt").read_text()
    assert calls.exists(), "the isolated dry-run must have been reached"
    assert "--execute" not in calls.read_text()
    launch_lines = launch_calls.read_text().splitlines()
    assert len(launch_lines) == 2, launch_lines
    assert launch_lines[0].startswith("bootout ")
    assert launch_lines[1].startswith("bootstrap ")
    assert "broker ready on verified installed identity" in (tmp_path / "shell-output.txt").read_text()


def test_native_finish_does_not_hand_admission_to_the_show_broker():
    class Boundary:
        def __init__(self):
            self.plist = None
            self.boots = []
            self.readback = 0
        def set_emotiscope_admission(self, path):
            self.plist = ("show", path)
        def set_native_admission(self, path):
            self.plist = ("native", path)
        def bootstrap_previous(self, admission):
            self.boots.append(admission)
        def legacy_readback(self):
            self.readback += 1
    boundary = Boundary()
    result = admission.finish_deployment(
        boundary, protocol="native", identity_ok=True, programme_rc=0,
        new_admission="/native.json", prior_admission="/show.json")
    assert boundary.plist == ("native", "/native.json") and boundary.boots == ["/native.json"] and boundary.readback == 0
    assert result["native_handed_to_emotiscope_broker"] is False
    assert result["firmware_rolled_back"] is False and result["installed"] == "native"
    failed = Boundary()
    timeout = admission.finish_deployment(
        failed, protocol="legacy", identity_ok=False, programme_rc=2,
        new_admission="/next.json", prior_admission="/show.json")
    assert failed.plist is None and failed.boots == ["/show.json"]
    assert timeout["write_began"] == "unverified"
    legacy = Boundary()
    ok = admission.finish_deployment(
        legacy, protocol="legacy", identity_ok=True, programme_rc=0,
        new_admission="/show.json", prior_admission="/old.json")
    assert legacy.plist == ("show", "/show.json") and legacy.readback == 1 and ok["installed"] == "legacy"


def test_gateway_resolves_renumbered_native_usb_without_guessing(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from ael import titan_isolated as isolated
    now=[10.]
    def endpoint(device, serial, location='exact-socket'):
        return SimpleNamespace(device=device,serial_number=serial,location=location,vid=0x045b,pid=0x5310)
    donor=endpoint('/dev/cu.DONOR','donor')
    monkeypatch.setattr(isolated,'usb_inventory',lambda:[donor])
    monkeypatch.setattr(isolated.time,'monotonic',lambda:now[0])
    anchor=admission.native_usb_anchor(20.)
    serial=bytes.fromhex(admission.UID)[::-1].hex()
    native=endpoint('/dev/cu.RENUMBERED',serial)
    real=isolated.wait_for_native_interface
    observed=[]
    def inventory():
        observed.append(now[0])
        return [] if len(observed)==1 else [native]
    def sleep(seconds): now[0]+=seconds
    monkeypatch.setattr(isolated,'wait_for_native_interface',lambda a,d:real(a,d,clock=lambda:now[0],sleep=sleep,inventory=inventory))
    resolved=admission.resolve_native_usb(anchor,12.)
    assert resolved['device']=='/dev/cu.RENUMBERED' and len(observed)==2
    path=tmp_path/'anchor.json';path.write_text(json.dumps(anchor))
    assert admission.main(['resolve-native-port','--file',str(path),'--deadline','12']) == 0
    assert capsys.readouterr().out.strip() == '/dev/cu.RENUMBERED'
    with pytest.raises(admission.Refusal,match='explicit native port'):
        admission.resolve_native_usb(anchor,12.,'/dev/cu.DONOR')
    for field,value in [('serial_number','wrong'),('location','other-socket')]:
        setattr(native,field,value)
        with pytest.raises(TimeoutError):admission.resolve_native_usb(anchor,now[0]+.2)
        setattr(native,field,serial if field=='serial_number' else 'exact-socket')
    assert now[0] < 12.


def test_gateway_anchor_refuses_missing_or_ambiguous_device(monkeypatch):
    from types import SimpleNamespace
    from ael import titan_isolated as isolated
    endpoint=SimpleNamespace(device='/dev/cu.TEST',vid=0x045b,pid=0x5310,location='test',serial_number='test')
    for rows in ([],[endpoint,endpoint]):
        monkeypatch.setattr(isolated,'usb_inventory',lambda:rows)
        with pytest.raises(admission.Refusal):admission.native_usb_anchor(admission.time.monotonic()+20)


@pytest.mark.parametrize('application_present',[True,False])
def test_all_gateway_internal_observations_disable_auto_recovery(tmp_path,application_present):
    import re
    import shlex
    import subprocess
    import sys
    source=Path('/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts/deploy_titan_image.sh').read_text()
    calls=re.findall(r'python3 "\$HERE/smc_titan.py" ([a-z]+)([^>\n;]*)',source)
    assert len(calls)==2
    marker=tmp_path/'unexpected-reset'
    fake=tmp_path/'smc.py'
    fake.write_text('import sys\nfrom pathlib import Path\n' +
        f'present={application_present!r}\n' +
        f'if not present and "--observe-only" not in sys.argv: Path({str(marker)!r}).touch()\n' +
        'assert "--observe-only" in sys.argv\nprint("observed")\n')
    for action,options in calls:
        argv=[sys.executable,str(fake),action,*shlex.split(options)]
        assert subprocess.run(argv,capture_output=True,text=True,check=False).returncode==0
    assert not marker.exists()


def return_documents():
    smc=healthy();smc['target']['build']='a'*64
    smc['controller']['blockers']=[{'code':'no_mixer','text':'No mixer input','detail':'no physical MIDI'}]
    smc['problems']=['No mixer input: no physical MIDI','com.spectrasynq.titan-mixer is running OLD code (native_control.py changed after it started)']
    settings={'restored':True,'capture_sha256':'b'*64,'identity':{'uid':UID,'build':'a'*64,'protocol':'legacy'},'replayed':False}
    return smc,settings

def test_actual_postreturn_cli_retains_mixer_and_stale_notices(tmp_path):
    import subprocess
    smc,settings=return_documents()
    health=tmp_path/'health.json';health.write_text(json.dumps(smc))
    restored=tmp_path/'settings.json';restored.write_text(json.dumps(settings))
    out=tmp_path/'return.json'
    result=subprocess.run([sys.executable,str(HELPER),'check-legacy-return','--smc',str(health),
        '--build','a'*64,'--settings',str(restored),'--capture-sha','b'*64,'--out',str(out)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
    proof=json.loads(out.read_text())
    assert proof['application_ready'] and proof['settings_equality_verified']
    assert proof['notices']==smc['problems']

@pytest.mark.parametrize('failure',['ready','confirmed','frames','fault','build','blocker','unknown_problem','active_capture','write_error','settings','capture_hash','settings_target'])
def test_postreturn_keeps_target_and_settings_failures(failure):
    smc,settings=return_documents()
    if failure in ('ready','confirmed'):smc['controller'][failure]=False
    elif failure=='frames':smc['frames_per_s']=0
    elif failure=='fault':smc['target']['led_faults']=1
    elif failure=='build':smc['target']['build']='wrong'
    elif failure=='blocker':smc['controller']['blockers'].append({'code':'titan_down'})
    elif failure=='unknown_problem':smc['problems'].append('Target failure')
    elif failure=='active_capture':smc['captures']={'active':True}
    elif failure=='write_error':smc['controller']['write_state']={'state':'error'}
    elif failure=='settings':settings['restored']=False
    elif failure=='capture_hash':settings['capture_sha256']='wrong'
    else:settings['identity']['uid']='wrong'
    with pytest.raises(admission.Refusal):admission.check_legacy_return(smc,'a'*64,settings,'b'*64)


def test_current_show_readiness_uses_full_version8_get(monkeypatch):
    """The installed show rejects the older GET command before state readback."""
    import socket
    import tempfile
    import threading

    monkeypatch.setattr(admission, 'broker_hello_fields', lambda: {})
    errors, reads = [], []
    with tempfile.TemporaryDirectory(prefix='tgv8-', dir='/tmp') as directory:
        path = str(Path(directory) / 'control.sock')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)

        def serve():
            try:
                conn, _ = listener.accept()
                with conn, conn.makefile('rwb') as stream:
                    conn.settimeout(2)
                    for _ in range(4):
                        row = json.loads(stream.readline())
                        if row['op'] == 'hello':
                            reply = {'ok': True, 'session': 's', 'bound': {
                                'uid': UID, 'build': admission.CURRENT_SHOW_RECOVERY[0]}}
                        elif row['op'] == 'legacy_health':
                            reply = {'ok': True, 'faults': 0, 'completed_count': 12,
                                     'info': {'uid': UID, 'build': admission.CURRENT_SHOW_RECOVERY[0], 'boot_id': 7}}
                        elif row['op'] == 'emotiscope_get' and row.get('state_version') == 8:
                            reads.append(row['board'])
                            reply = {'ok': True, 'state': {'version': 8, 'boot_id': 7,
                                                         'selected_board': row['board']}}
                        else:
                            reply = {'ok': False, 'error': 'invalid'}
                        stream.write((json.dumps(reply) + '\n').encode())
                        stream.flush()
            except BaseException as error:
                errors.append(error)
            finally:
                listener.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            result = admission.query_broker(path, UID, admission.CURRENT_SHOW_RECOVERY[0], 2, 'legacy')
            assert [scene['version'] for scene in result['broker_status']['scenes']] == [8, 8]
        finally:
            thread.join(3)
        assert not thread.is_alive() and not errors
        assert reads == [0, 1]
