"""Offline broker capture authority and quiescence; no serial/service is opened."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import pytest
from ael import prism_native as native
from ael import titan_isolated as isolated
SHOW = Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-K1-RA8P1-Firmware/.worktrees/titan-emotiscope-port-001/tools/serial-studio')
sys.path.insert(0, str(SHOW))
from titan_broker import Broker
from titan_control_server import RestrictedControlPlane, NATIVE_OPS

def bind(path, doc):
    path.write_text(json.dumps(doc))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

@pytest.fixture
def case(tmp_path, monkeypatch):
    owner = tmp_path / 'owner.json'
    monkeypatch.setattr(native, 'OWNER_LEASE_PATH', owner)
    lease = bind(owner, {'pid': os.getpid(), 'task': 'TEST ONLY'})
    event = bind(tmp_path / 'event.json', {'test': True})
    facts = {'scope': {'exact': 'TEST ONLY'}, 'fixture_id': 'TEST ONLY'}
    monkeypatch.setattr(isolated, 'preflight', lambda *a, **k: facts)
    manifest = {'target': 'titan-replacement', 'identity': native.UID,
                'source_binding_hash': 'b'*64, 'image': {'sha256': 'c'*64},
                'owner_lease': lease, 'isolated_programming_event': event}
    grant = {'kind': 'replacement-isolated-v4', 'scope_sha256': hashlib.sha256(json.dumps(facts['scope'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
             'fixture_id': facts['fixture_id'], 'owner_lease_sha256': lease['sha256'], 'expires_at': time.time()+30}
    admission = {'uid': native.UID, 'build': 'b'*64, 'hex_sha256': 'c'*64, 'isolated_capture_grant': grant}
    current = {'uid': native.UID, 'build': 'b'*64, 'protocol': 'titan-native'}
    req = {'manifest': bind(tmp_path/'manifest.json',manifest), 'operation': bind(tmp_path/'operation.json',{'isolated_capture': {}}), 'output': str(tmp_path), 'deadline': time.monotonic()+20, 'session': 'test'}
    return req, admission, current, manifest, facts

def test_exact_binding_claims_once(case):
    req, admission, current, manifest, facts = case
    assert native.validate_broker_capture(req,admission,current)[0] == manifest
    with pytest.raises(FileExistsError):
        native.validate_broker_capture(req,admission,current)

@pytest.mark.parametrize('bad', ['grant','fixture','scope','owner','expired','uid','build','image','historical','operation','lease_bytes'])
def test_refusal_before_collector(case,bad):
    req,a,c,m,f=case
    if bad=='grant': a.pop('isolated_capture_grant')
    elif bad in ('fixture','scope','owner'): a['isolated_capture_grant'][{'fixture':'fixture_id','scope':'scope_sha256','owner':'owner_lease_sha256'}[bad]]='wrong'
    elif bad=='expired': a['isolated_capture_grant']['expires_at']=0
    elif bad in ('uid','build'): c[bad]='wrong'
    elif bad=='image': a['hex_sha256']='wrong'
    elif bad=='historical': m['target']='titan-native'; req['manifest']=bind(Path(req['manifest']['path']),m)
    elif bad=='operation': req['operation']=bind(Path(req['operation']['path']),{'completion': {}})
    else: Path(m['owner_lease']['path']).write_text('{}')
    with pytest.raises((ValueError,RuntimeError)):
        native.validate_broker_capture(req,a,c)
    assert not list(Path(req['output']).glob('capture-*.claim'))

@pytest.mark.parametrize('mode', ['success','lost_arm','cancel_failed','forgot_cancel','validation'])
def test_real_broker_transport_quiescence(case,monkeypatch,mode):
    req,a,c,m,f=case
    calls=[]
    def exchange(op,payload,timeout):
        calls.append(op)
        if mode=='lost_arm' or (mode=='cancel_failed' and op==0x50524604):
            raise TimeoutError('synthetic transport timeout')
        return {'ok':True,'body':b'{}'}
    broker=object.__new__(Broker)
    broker.transport=SimpleNamespace(native_exchange=exchange, _isolated_fixture_exchange=exchange)
    broker._sched=threading.Lock()
    def collector(*args,exchange_override,**kw):
        exchange_override(0x50524601)
        if mode!='forgot_cancel': exchange_override(0x50524604)
        return {'test': True}
    monkeypatch.setattr(native,'run_session',collector)
    if mode=='validation': a.pop('isolated_capture_grant')
    if mode=='success':
        assert broker._isolated_capture(req,a,c)=={'test':True}
        assert calls==[0x50524601,0x50524604]
    else:
        with pytest.raises(Exception) as caught: broker._isolated_capture(req,a,c)
        assert caught.value.collector_quiesced is (mode=='validation')
        if mode=='validation': assert calls==[]

def test_historical_gateway_fails_before_deployment(monkeypatch):
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    with pytest.raises(RuntimeError,match='historical/completion'):
        isolated.execute({'target':'titan-native'},None,None,None,{})


def test_named_dispatch_requires_separate_grant(case,monkeypatch,tmp_path):
    req,a,c,m,f=case
    import titan_control_server
    monkeypatch.setattr(titan_control_server, 'OWNER_LEASE_PATH', tmp_path / 'absent-controller-owner.json')
    monkeypatch.setenv('TITAN_LIVE_CONTROL_ADMITTED','1')
    a.update(protocol='titan-native',schema_sha256='replacement-health-v1',controls_persistent=False,durable_commit='explicit-v1',ops=list(NATIVE_OPS))
    c.update(schema_sha256='replacement-health-v1',controls_persistent=False,durable_commit='explicit-v1')
    path=tmp_path/'accepted-candidate.json'
    path.write_text(json.dumps(a))
    calls=[]
    plane=RestrictedControlPlane(transact=lambda *x: pytest.fail('unexpected raw transport'),evidence=tmp_path,bound=c,isolated_execute=lambda *args: calls.append(args) or {'ok':True})
    hello=plane.handle({'op':'hello'})
    req.update(op='native_isolated_capture',session=hello['session'],admission_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert plane.handle(req)['ok'] is True
    assert len(calls)==1
    a.pop('isolated_capture_grant');path.write_text(json.dumps(a))
    req['admission_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    reply=plane.handle(req)
    assert reply['ok'] is False and reply['capture_finished'] is True
    assert len(calls)==1
    assert 'native_isolated_capture' not in NATIVE_OPS


def test_same_grant_cannot_replay_with_new_event(case):
    req,a,c,m,f=case
    native.validate_broker_capture(req,a,c)
    m['isolated_programming_event']=bind(Path(req['output'])/'event2.json',{'changed': True})
    req['manifest']=bind(Path(req['manifest']['path']),m)
    with pytest.raises(FileExistsError): native.validate_broker_capture(req,a,c)

@pytest.mark.parametrize('bad',['different_pid','wrong_command','many','missing',None])
def test_gateway_requires_actual_existing_broker_owner(monkeypatch,bad):
    from ael.adapters import prism_bench_trial as bench
    def run(argv,**kw):
        if argv[0]=='ps':
            value='wrong' if bad=='wrong_command' else str(SHOW/'titan_broker.py')
        elif argv[-1]=='serial': value='123'
        else: value={'different_pid':'456','many':'123 456','missing':''}.get(bad,'123')
        return SimpleNamespace(returncode=1 if bad=='missing' else 0,stdout=value,stderr='')
    monkeypatch.setattr(bench.subprocess,'run',run)
    if bad:
        with pytest.raises(RuntimeError): bench.require_gateway_broker_owner('serial','socket')
    else: assert bench.require_gateway_broker_owner('serial','socket')['pid']==123


@pytest.mark.parametrize('finished',[True,False])
def test_client_uses_temporary_socket_and_propagates_quiescence(tmp_path,finished,monkeypatch):
    import socket
    import tempfile
    with tempfile.TemporaryDirectory(prefix='tbc-') as short:
        path=str(Path(short)/'socket')
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        listener.bind(path);listener.listen(1);listener.settimeout(3)
        owner_path = tmp_path / 'client-owner.json'
        monkeypatch.setattr(native, 'OWNER_LEASE_PATH', owner_path)
        lease = bind(owner_path, {'pid': os.getpid(), 'task': 'isolated client fixture'})
        admission=tmp_path/'admission.json';admission.write_text('{}')
        manifest={'source_binding_hash':'b'*64,'deployment':{'admission':str(admission)},
                  'owner_lease': lease}
        frozen=bind(tmp_path/'manifest.json',manifest)
        manifest.update(broker_manifest=frozen,broker_socket=path)
        operation=bind(tmp_path/'operation.json',{'isolated_capture':{}})
        calls=[]
        def serve():
            conn,_=listener.accept()
            with conn,conn.makefile('rwb') as stream:
                for reply in ({'ok':True,'session':'test','bound':{'uid':native.UID,'build':'b'*64}},
                              {'ok':finished,'capture_finished':finished,'error':'synthetic','result':{'test':True}}):
                    calls.append(json.loads(stream.readline()))
                    stream.write((json.dumps(reply)+'\n').encode());stream.flush()
        worker=threading.Thread(target=serve);worker.start()
        try:
            if finished:
                assert native.broker_capture(manifest,tmp_path,operation['path'],operation['sha256'],time.monotonic()+2)=={'test':True}
            else:
                with pytest.raises(ValueError) as caught:
                    native.broker_capture(manifest,tmp_path,operation['path'],operation['sha256'],time.monotonic()+2)
                assert caught.value.collector_quiesced is False
        finally:
            worker.join(3);listener.close()
        assert not worker.is_alive()
        assert [r['op'] for r in calls]==['hello','native_isolated_capture']
        assert calls[0] == {'op': 'hello', 'maintenance': {'owner_lease_sha256': lease['sha256']}}
        assert calls[1]['session']=='test'
        assert calls[1]['manifest'] == frozen
        assert calls[1]['admission_sha256'] == hashlib.sha256(admission.read_bytes()).hexdigest()


def test_scheduler_deadline_prevents_transport_write(case,monkeypatch):
    req,a,c,m,f=case
    broker=object.__new__(Broker)
    broker.transport=SimpleNamespace(native_exchange=lambda *a,**k: pytest.fail('transport after deadline'))
    class Busy:
        def acquire(self,timeout):
            assert 0 < timeout <= 20
            return False
    broker._sched=Busy()
    def collector(*args,exchange_override,**kw): exchange_override(0x50524601)
    monkeypatch.setattr(native,'run_session',collector)
    with pytest.raises(TimeoutError) as caught: broker._isolated_capture(req,a,c)
    assert caught.value.collector_quiesced is True


def test_collector_fixture_uses_real_framed_transport(case, monkeypatch):
    import struct
    import zlib
    from titan_transport import FakeSerial, Transport, ObserveDenied
    req, admission, current, manifest, facts = case
    class FixtureDevice(FakeSerial):
        def __init__(self):
            super().__init__()
            self.ops = []
        def write(self, frame):
            magic, op, seq, size, crc, version, head_crc = struct.unpack('<4sIQIIII', frame[:32])
            assert magic == b'K1S1' and version == 1
            assert zlib.crc32(frame[:28]) & 0xffffffff == head_crc
            assert size == len(frame[32:]) and zlib.crc32(frame[32:]) & 0xffffffff == crc
            self.ops.append(op)
            body = b'{}'
            header = struct.pack('<4sIQIII', b'K1R1', 0, seq, len(body), 0, zlib.crc32(body))
            self.rx.extend(header + struct.pack('<I', zlib.crc32(header)) + body)
            return len(frame)
    device = FixtureDevice()
    broker = object.__new__(Broker)
    broker.transport = Transport(device, campaign=True)
    broker._sched = threading.Lock()
    def collector(*args, exchange_override, **kwargs):
        for opcode in (0x50524601, 0x50524602, 0x50524603, 0x50524604):
            assert exchange_override(opcode, b'exact fixture request') == b'{}'
        return {'test': True}
    monkeypatch.setattr(native, 'run_session', collector)
    assert broker._isolated_capture(req, admission, current) == {'test': True}
    assert device.ops == [0x50524601, 0x50524602, 0x50524603, 0x50524604]
    with pytest.raises(ObserveDenied): broker.transport.native_exchange(0x50524601)
    with pytest.raises(ObserveDenied): broker.transport._isolated_fixture_exchange(0x50524203)
    with pytest.raises(ObserveDenied): broker.transport._isolated_fixture_exchange(0x50524605)
    assert len(device.ops) == 4
