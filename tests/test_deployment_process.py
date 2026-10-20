"""Offline lifecycle tests: only test-owned Python processes are executed."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from ael.deployment_process import run_deployment


@pytest.mark.parametrize('cancel', [None, signal.SIGTERM, signal.SIGINT])
def test_timeout_or_cancellation_reaps_child_after_term_cleanup(tmp_path, cancel):
    runner = tmp_path / 'gateway.py'
    runner.write_text('''import pathlib, signal, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
(root / 'child.pid').write_text(str(child.pid))
def cleanup(signum, frame):
    child.wait(timeout=2)
    (root / 'cleanup').write_text('child reaped before recovery')
    raise SystemExit(143)
signal.signal(signal.SIGTERM, cleanup)
(root / 'ready').write_text('ready')
while True: time.sleep(.01)
''')
    receipt = {}
    errors = []
    def cancellation():
        until = time.monotonic() + 2
        while not (tmp_path / 'ready').exists() and time.monotonic() < until:
            time.sleep(.005)
        if not (tmp_path / 'ready').exists():
            errors.append('gateway did not become ready')
            return
        os.kill(os.getpid(), cancel)
    thread = threading.Thread(target=cancellation) if cancel else None
    if thread:
        thread.start()
    try:
        with (tmp_path / 'output').open('wb') as out:
            with pytest.raises(KeyboardInterrupt if cancel else subprocess.TimeoutExpired):
                run_deployment([sys.executable, str(runner), str(tmp_path)], stdout=out,
                               timeout=2 if cancel else .2,
                               deadline=time.monotonic() + 3, process=receipt)
    finally:
        if thread:
            thread.join(3)
    assert not errors
    assert (tmp_path / 'cleanup').read_text() == 'child reaped before recovery'
    assert receipt['returncode'] == 143
    assert receipt['process_group_complete'] is True
    assert receipt['recovery_safe'] is True
    assert receipt['cleanup_forced'] is False
    with pytest.raises(ProcessLookupError):
        os.killpg(receipt['process_group_id'], 0)
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / 'child.pid').read_text()), 0)


def test_deadline_forces_owned_group_and_forbids_recovery(tmp_path):
    runner = tmp_path / 'ignore.py'
    runner.write_text('import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n')
    receipt = {}
    started = time.monotonic()
    deadline = started + .7
    with (tmp_path / 'output').open('wb') as out:
        with pytest.raises(subprocess.TimeoutExpired) as error:
            run_deployment([sys.executable, str(runner)], stdout=out, timeout=.2,
                           deadline=deadline, process=receipt)
    assert receipt['cleanup_forced'] is True
    assert receipt['recovery_safe'] is False
    assert receipt['process_group_complete'] is True
    assert receipt['returncode'] == -signal.SIGKILL
    assert any('recovery forbidden' in note for note in error.value.__notes__)
    assert time.monotonic() < deadline + .2
    with pytest.raises(ProcessLookupError):
        os.killpg(receipt['process_group_id'], 0)


def test_caller_records_forced_cleanup_and_does_not_start_recovery(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from ael import titan_isolated as isolated
    from ael.adapters import prism_bench_trial as bench
    monkeypatch.setattr(isolated, "require_broker_capture_route", lambda manifest: None)

    runner = tmp_path / 'ignore.py'
    runner.write_text('import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n')
    image = tmp_path / 'synthetic.hex'
    image.write_text('test data, never sent to a device')
    manifest = {'target': 'titan-replacement', 'port': 'TEST ONLY',
                'image': {'path': str(image)}, 'recovery': {'image': {'path': str(image)}},
                'isolated_qualification': {}}
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK', '1')
    monkeypatch.setattr(isolated, 'preflight', lambda *a, **k: {'fixture_id': 'TEST ONLY'})
    monkeypatch.setattr(isolated, 'usb_anchor', lambda *a, **k: {'location': 'TEST ONLY'})
    monkeypatch.setattr(bench, 'bound_file', lambda row: Path(row['path']).resolve())
    calls = []
    def argv(*args, **kwargs):
        calls.append(args[2])
        return [sys.executable, str(runner)]
    monkeypatch.setattr(bench, 'deployment_argv', argv)
    def bounded_run(argv, *, stdout, timeout, deadline, process):
        return run_deployment(argv, stdout=stdout, timeout=.15,
                              deadline=min(deadline, time.monotonic() + .6), process=process)
    monkeypatch.setattr(isolated, '_run_deployment', bounded_run)
    facts = {}
    with pytest.raises(subprocess.TimeoutExpired):
        isolated.execute(manifest, tmp_path, image, SimpleNamespace(logs_dir=tmp_path), facts)
    assert calls == ['candidate']
    assert facts['known_donor_program_and_verify_completed'] is False
    assert 'recovery forbidden' in facts['recovery_error']
    receipt = json.loads((tmp_path / 'candidate-process.json').read_text())
    assert receipt['outcome'] == 'timeout'
    assert receipt['cleanup_forced'] is True
    assert receipt['recovery_safe'] is False
    assert receipt['process_group_complete'] is True
    assert (tmp_path / 'isolated-transaction.json').is_file()
    assert not (tmp_path / 'donor-recovery-invocation.json').exists()
