"""Offline automatic-access consumer tests. All external boundaries are fakes."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path('/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts')
spec = importlib.util.spec_from_file_location('titan_access', SCRIPTS/'titan_access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)
PROBE = {'vid': 0x045b, 'pid': 0x82a0, 'serial': access.PROBE}
APP = {'vid': 0x045b, 'pid': 0x5310, 'ports': ['/dev/cu.TEST_ONLY']}
# Exact signature text retained from connection-diagnosis-01/result.json, 20 October 2026.
SIGNATURE = (Path(__file__).parent/'fixtures/titan-access-signature.txt').read_text()


class Fake:
    def __init__(self, devices=None, failure=None):
        self.devices = [dict(PROBE)] if devices is None else devices
        self.failure = failure
        self.calls = []
        self.group_complete = True
    def inventory(self): return self.devices
    def binding(self): return {'PRIOR_BUILD': 'admitted-build'}
    def stop(self, deadline):
        self.calls.append('stop')
        if self.failure == 'interrupt': raise KeyboardInterrupt('injected')
        if self.failure == 'stop': raise RuntimeError('old broker remains')
    def signature(self, deadline, receipt):
        self.calls.append('signature')
        if self.failure == 'timeout': raise TimeoutError('injected timeout')
        if self.failure == 'orphan':
            self.group_complete = False
            raise TimeoutError('group incomplete')
        text = SIGNATURE.replace(access.UID.upper(), 'WRONG') if self.failure == 'identity' else SIGNATURE
        return SimpleNamespace(returncode=0, stdout=text, stderr='')
    def verify(self, binding, deadline):
        self.calls.append('verify')
        if self.failure == 'identity': raise RuntimeError('wrong fresh identity')
        return {'bound': {'uid': access.UID, 'build': 'admitted-build'}}
    def restore(self, binding, deadline):
        self.calls.append('restore')
        if self.failure in ('bootstrap', 'stop', 'orphan'): raise RuntimeError('restoration unresolved')
        return self.verify(binding, deadline)


def run(tmp_path, ops):
    return access.ensure_access(ops=ops, state_dir=tmp_path/'state', lock=tmp_path/'lock')


def test_absent_application_triggers_once_and_latches_across_instances(tmp_path):
    ops = Fake()
    result = run(tmp_path, ops)
    assert result['status'] == 'recovered' and result['reset_attempted']
    assert result['settings_restoration'] == 'unverified'
    assert ops.calls == ['stop', 'signature', 'restore', 'verify']
    again = Fake()
    assert run(tmp_path, again)['status'] == 'outage-latched'
    assert again.calls == []
    healthy = Fake([PROBE, APP])
    assert run(tmp_path, healthy)['status'] == 'present'
    assert healthy.calls == ['verify']
    assert json.loads((tmp_path/'state/outage.json').read_text())['attempts'] == 0


@pytest.mark.parametrize('devices', [[PROBE, APP], [], [dict(PROBE, serial='WRONG')]])
def test_healthy_or_wrong_probe_never_resets(tmp_path, devices):
    ops = Fake(devices)
    assert run(tmp_path, ops)['reset_attempted'] is False
    assert ops.calls == []


def test_enumerated_application_without_cdc_triggers_recovery(tmp_path):
    ops = Fake([PROBE, dict(APP, ports=[])])
    assert run(tmp_path, ops)['reset_attempted'] is True


def test_ambiguous_application_refuses_without_lock_or_reset(tmp_path):
    with pytest.raises(RuntimeError, match='ambiguous'):
        run(tmp_path, Fake([PROBE, dict(APP, ports=['one', 'two'])]))
    assert not (tmp_path/'lock').exists()


def test_other_owner_is_preserved(tmp_path):
    lock = tmp_path/'lock'; lock.mkdir(); (lock/'owner').write_text('other')
    ops = Fake()
    assert run(tmp_path, ops)['status'] == 'active-owner'
    assert ops.calls == [] and (lock/'owner').read_text() == 'other'


@pytest.mark.parametrize('failure', ['identity', 'bootstrap', 'stop', 'timeout', 'orphan', 'interrupt'])
def test_error_paths_restore_or_retain_ownership_truthfully(tmp_path, failure):
    ops = Fake(failure=failure)
    if failure == 'interrupt':
        with pytest.raises(KeyboardInterrupt): run(tmp_path, ops)
        result = json.loads((tmp_path/'state/last-attempt.json').read_text())
    else:
        result = run(tmp_path, ops)
    assert 'restore' in ops.calls
    assert json.loads((tmp_path/'state/outage.json').read_text())['attempts'] == 1
    assert result['status'] != 'recovered'
    assert bool((tmp_path/'lock').exists()) == result['lock_retained']
    if failure in ('identity', 'bootstrap', 'stop', 'orphan'):
        assert result['broker_restored'] is False


def test_actual_ioreg_prefix_and_cdc_shape(monkeypatch):
    import plistlib
    raw = plistlib.dumps([{'idVendor': 0x045b, 'idProduct': 0x82a0, 'USB Serial Number': 'E2L: 5AS079228B'},
                         {'idVendor': 0x045b, 'idProduct': 0x5310}])
    def inventory_command(argv, **kwargs):
        assert argv == ['/usr/sbin/ioreg', '-a', '-l', '-p', 'IOUSB']
        assert kwargs['timeout'] == 5 and kwargs['check'] is True
        return SimpleNamespace(stdout=raw)
    monkeypatch.setattr(access.subprocess, 'run', inventory_command)
    from serial.tools import list_ports
    monkeypatch.setattr(list_ports, 'comports', lambda: [SimpleNamespace(vid=0x045b, pid=0x5310, device='/dev/cu.TEST_ONLY')])
    rows = access.usb_inventory()
    assert rows[0]['serial'] == access.PROBE
    assert access.application_present(rows)


def test_real_health_consumer_calls_recovery_unless_observe_only(monkeypatch):
    spec = importlib.util.spec_from_file_location('smc_access_test', SCRIPTS/'smc_titan.py')
    smc = importlib.util.module_from_spec(spec); spec.loader.exec_module(smc)
    calls = []
    monkeypatch.setitem(sys.modules, 'titan_access', SimpleNamespace(ensure_access=lambda: calls.append('access') or {'status': 'present'}))
    monkeypatch.setattr(smc, 'launchd', lambda label: {'loaded': True, 'state': 'running'})
    monkeypatch.setattr(smc, 'titan_usb', lambda: True)
    monkeypatch.setattr(smc, 'target', lambda: {})
    monkeypatch.setattr(smc, 'emitted_rate', lambda: 100)
    monkeypatch.setattr(smc, 'controller', lambda: {'write_state': {}})
    smc.health(observe_only=True)
    assert calls == []
    smc.health()
    assert calls == ['access']


def test_real_sigterm_cleanup_finishes_before_broker_restore(tmp_path, monkeypatch):
    import os
    import signal
    import threading
    import time
    runner = tmp_path/'fake_programmer.py'
    runner.write_text('''import pathlib, signal, subprocess, sys, time
root=pathlib.Path(sys.argv[1])
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
(root/'child.pid').write_text(str(child.pid))
def stop(number, frame):
    child.wait(timeout=2)
    (root/'cleaned').write_text('reaped')
    raise SystemExit(143)
signal.signal(signal.SIGTERM,stop)
(root/'ready').write_text('ready')
while True: time.sleep(.01)
''')
    monkeypatch.setattr(access, 'COMMAND', [sys.executable, str(runner), str(tmp_path)])
    class ProcessFake(Fake):
        signature = access.AccessOps.signature
        def restore(self, binding, deadline):
            assert self.group_complete and (tmp_path/'cleaned').read_text() == 'reaped'
            return super().restore(binding, deadline)
    errors = []
    def cancel():
        until=time.monotonic()+2
        while not (tmp_path/'ready').exists() and time.monotonic()<until: time.sleep(.005)
        if not (tmp_path/'ready').exists():
            errors.append('no readiness'); return
        os.kill(os.getpid(), signal.SIGTERM)
    sender=threading.Thread(target=cancel); sender.start()
    ops=ProcessFake()
    try:
        with pytest.raises(KeyboardInterrupt): run(tmp_path,ops)
    finally:
        sender.join(3)
    assert errors == []
    result=json.loads((tmp_path/'state/last-attempt.json').read_text())
    assert result['programmer_group_complete'] and result['broker_restored']
    assert not result['lock_retained'] and not (tmp_path/'lock').exists()
    with pytest.raises(ProcessLookupError): os.killpg(result['programmer_pgid'],0)
    with pytest.raises(ProcessLookupError): os.kill(int((tmp_path/'child.pid').read_text()),0)


def test_waiting_broker_is_not_bootstrapped_twice_and_failed_bootstrap_is_reported(monkeypatch):
    ops=access.AccessOps.__new__(access.AccessOps)
    ops.group_complete=True; ops.old_pid=None
    ops.unchanged=lambda binding: None
    ops.service=lambda deadline: (True,None)
    ops.verify=lambda binding,deadline: {'fresh':'identity'}
    calls=[]
    ops.command=lambda argv,deadline: calls.append(argv) or SimpleNamespace(returncode=5,stderr='refused')
    import time
    assert ops.restore({},time.monotonic()+1)=={'fresh':'identity'}
    assert calls==[]
    ops.service=lambda deadline: (False,None)
    with pytest.raises(RuntimeError,match='bootstrap failed'):
        ops.restore({},time.monotonic()+1)
    assert len(calls)==1 and calls[0][1]=='bootstrap'
