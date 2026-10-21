"""No hardware: adversarial admission and bounded recovery orchestration."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ael import titan_isolated as isolated
from ael.adapters import prism_bench_trial as bench
from ael.titan_waveform import UID,digest


def mock_deployment(monkeypatch, callback):
    """Isolate gateway calls while preserving separate real lifecycle tests."""
    def run(argv, *, stdout, timeout, deadline, process):
        process.update(process_group_complete=True, recovery_safe=True)
        if "--deadline" in argv:
            assert float(argv[-1]) == deadline
            argv = argv[:-2]
        result = callback(argv, stdout=stdout, timeout=timeout,
                          stderr=subprocess.STDOUT, check=False)
        # Historical orchestration fixtures now emit the actual sealed receipt channels.
        programme = Path(argv[-1]); receipt_path = programme/'receipt.json'
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text())
            if 'stdout' not in receipt:
                image = Path(receipt['command'][-1])
                receipt.update(uid=UID, hex_sha256=bench.sha(image),
                    command=['/opt/rfp-cli','-d','RA','-t','e2l:5AS079228B','-if','swd','-s','1000000',
                             '-noquery','-run','-range','02000000,02c9f01f','-pv',str(image)],
                    stdout=Path(str(programme)+'.stdout').read_text(), stderr='')
                receipt_path.write_text(json.dumps(receipt))
        return result
    monkeypatch.setattr(isolated, '_run_deployment', run)


def fake_deployment_with_settings(m, image, name, programme_dir, *, restore_settings=None):
    """Synthetic gateway boundary; exercise actual outbound-to-return settings wiring."""
    programme_dir = Path(programme_dir)
    if name == 'candidate':
        capture = Path(str(programme_dir) + '.prior-settings.json')
        capture.write_text('{"test_only":"original complete settings boundary"}')
        Path(str(programme_dir) + '.prior-settings.sha256').write_text(digest(capture.read_bytes()))
        assert restore_settings is None
    else:
        assert restore_settings is not None
        capture = Path(restore_settings['path'])
        assert capture.name == 'candidate-programme.prior-settings.json'
        assert digest(capture.read_bytes()) == restore_settings['sha256']
    return ['/bin/bash','/Users/spectrasynq/.claude/skills/smc-titan-mixer/scripts/deploy_titan_image.sh',
            '/build','/admission.json',str(programme_dir)]


def bind(tmp,name,data):
    p=tmp/name
    p.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode())
    return {'path':str(p),'sha256':digest(p.read_bytes())}


@pytest.mark.parametrize('failure',['exit','timeout','exception','exit_recovery_timeout'])
def test_program_process_receipt_precedes_validation_and_preserves_recovery(tmp_path,monkeypatch,failure):
    from ael import prism_native
    m=admission(tmp_path,monkeypatch)
    now=[10.]; calls=[]; validated=[]; receipts={}; errors={}
    real_preflight=isolated.preflight
    monkeypatch.setattr(isolated,'preflight',lambda m,consume=False:
        real_preflight(m,consume=consume,used_dir=tmp_path/'used'))
    monkeypatch.setattr(isolated.time,'monotonic',lambda:now[0])
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    monkeypatch.setattr(bench,'deployment_argv',fake_deployment_with_settings)
    monkeypatch.setattr(bench,'hex_spans',lambda p:[(0x2000000,0x2000010)])
    monkeypatch.setattr(isolated,'usb_anchor',lambda *a,**kw:{'location':'TEST ONLY'})
    forbidden=Mock(side_effect=AssertionError('Failed candidate must never reach capture/USB resolution'))
    monkeypatch.setattr(isolated,'wait_for_native_interface',forbidden)
    monkeypatch.setattr(prism_native,'run_session',forbidden)
    real_verify=isolated.verify_program_log
    def verify(raw,**kw):
        name='candidate' if kw['image'].name=='candidate.hex' else 'donor-recovery'
        receipt=json.loads((tmp_path/(name+'-process.json')).read_text())
        assert receipt['returncode']==kw['returncode'] or (kw['returncode']==0 and receipt['returncode']==0)
        if kw['returncode']==0:
            assert digest(raw)==digest(Path(str(tmp_path/(name+'-programme'))+'.stdout').read_bytes())
        else:
            assert receipt['combined_output']['sha256']==digest(raw)
        validated.append(name)
        return real_verify(raw,**kw)
    monkeypatch.setattr(isolated,'verify_program_log',verify)
    def run(argv,stdout,timeout,**kw):
        assert argv[1].endswith('deploy_titan_image.sh') and 'rfp-cli' not in argv[1]
        name='candidate' if argv[-1].endswith('candidate-programme') else 'donor-recovery'
        calls.append(name)
        assert timeout==(70 if name=='candidate' else 90)
        assert kw=={'stderr':subprocess.STDOUT,'check':False}
        stdout.write(b'gateway\n')
        now[0]+=2
        mode=failure if name=='candidate' else ('timeout' if failure=='exit_recovery_timeout' else 'success')
        if mode in ('timeout','exception'):
            exc=subprocess.TimeoutExpired(argv,timeout) if mode=='timeout' else OSError('TEST ONLY launch unavailable')
            errors[name]=exc
            raise exc
        rc=0 if name=='donor-recovery' else 23
        if rc==0:
            image=tmp_path/'donor.hex'
            programme=Path(argv[-1]); programme.mkdir()
            inner=['/opt/rfp-cli','-d','RA','-t','e2l:5AS079228B','-if','swd','-s','1000000','-noquery','-run','-range','02000000,02c9f01f','-pv',str(image)]
            (programme/'receipt.json').write_text(json.dumps({'pass':True,'execute':True,'returncode':0,'command':inner}))
            Path(str(programme)+'.stdout').write_bytes(rfp_log(image))
        return SimpleNamespace(returncode=rc)
    mock_deployment(monkeypatch, run)
    facts={}
    expected_type={'timeout':subprocess.TimeoutExpired,'exception':OSError}.get(failure,RuntimeError)
    with pytest.raises(expected_type) as caught:
        isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    assert calls==['candidate','donor-recovery']
    forbidden.assert_not_called()
    for name,start,limit,deadline in [('candidate',10.,70,90.),('donor-recovery',12.,90,130.)]:
        path=tmp_path/(name+'-process.json');r=json.loads(path.read_text());receipts[name]=r
        assert facts[name+'_process_receipt']=={'path':str(path.resolve()),'sha256':digest(path.read_bytes())}
        assert r['argv'][1].endswith('deploy_titan_image.sh')
        assert r['argv'][4].endswith(name+'-programme')
        assert not any(part.endswith('rfp-cli') for part in r['argv'])
        assert r['cwd']==str(Path.cwd()) and r['started_unix']==r['finished_unix']==1000.
        assert r['started_monotonic']==start and r['finished_monotonic']==start+2
        assert r['elapsed_seconds']==2 and r['timeout_seconds']==limit and r['deadline_monotonic']==deadline
        assert r['combined_output']=={'path':str((tmp_path/(name+'.log')).resolve()),
                                      'sha256':digest((tmp_path/(name+'.log')).read_bytes())}
        if name in errors:
            assert r['returncode'] is None and r['returncode_unavailable'] is True
            assert r['exception_type']==type(errors[name]).__name__
            assert r['exception_message']==str(errors[name])
            assert r['outcome']==('timeout' if isinstance(errors[name],subprocess.TimeoutExpired) else 'exception')
        else:
            assert r['returncode']==(23 if name=='candidate' else 0) and r['outcome']=='returned'
    assert validated==([n for n in calls if n not in errors and n != 'candidate'])
    assert facts['candidate_program_attempted'] and not facts['candidate_readback_verified']
    assert facts['known_donor_program_and_verify_completed'] is (failure!='exit_recovery_timeout')
    if failure in ('exit','exit_recovery_timeout'):
        assert 'without a sealed writer receipt; program/verify unconfirmed' in str(caught.value)
    else:
        assert caught.value is errors['candidate']
    if failure=='exit_recovery_timeout':
        assert caught.value.__cause__ is errors['donor-recovery']
    assert json.loads((tmp_path/'isolated-transaction.json').read_text())['primary_error']==str(caught.value)


def admission(tmp,monkeypatch):
    # Historical fixtures test pure recovery orchestration, not current broker eligibility.
    # The real replacement grant/refusal path is covered in test_broker_isolated_capture.
    monkeypatch.setattr(isolated, "require_broker_capture_route", lambda manifest: None)
    monkeypatch.setattr(isolated.time,'time',lambda:1000.)
    monkeypatch.setattr(bench,'require_titan_recovery',lambda m:{'exact_donor':'TEST ONLY','build_source_sha256':bench.TITAN_RECOVERY_BUILD,
        'image_sha256':m['recovery']['image']['sha256']})
    m={'target':'titan-native','identity':UID,'port':'/dev/cu.TEST-NO-HARDWARE','source_binding_hash':'b'*64,'source_commit':'c'*40,
       'image':bind(tmp,'candidate.hex',b'candidate test bytes'),
       'build_receipt':{'sha256':'d'*64},
       'recovery':{'image':bind(tmp,'donor.hex',b'donor test bytes')},
       'isolated_qualification':{'operation':isolated.OPERATION,'backend':isolated.BACKEND,
         'frames':100,'maximum_interruption_seconds':120}}
    scope=isolated._scope(m)
    raw=bind(tmp,'actual-user-message.txt',b'TEST ONLY: first isolated bootstrap approved; jumpers installed and both product DIN feeds physically disconnected.')
    reviewed=bind(tmp,'reviewed.json',{'scope':scope})
    common={'scope':scope,'actor':'Captain','origin':'operator-message','observed_unix':999.,
            'original_message':raw,'message_reference':'TEST-ONLY-message-id','exact_quote':'TEST ONLY:',
            'reviewed_request':reviewed,'fixture_id':'TEST-ONLY-fixture'}
    fixture=dict(common,schema='prism.titan.physical-exclusion.v1',
                 decision='physically-connected-and-product-excluded',
                 physical_basis='operator-direct-inspection-of-disconnected-DIN-and-installed-jumpers',
                 measurement_point='MCU-pads-P601-P604-3V3')
    authority=dict(common,schema='prism.titan.isolated-authority.v1',
                   decision='first-isolated-bootstrap-readiness-exception',
                   exception='candidate-detector-runtime-readiness-after-program-before-stimulus',
                   decision_id='TEST-ONLY-once-id-0001')
    q=m['isolated_qualification']
    q['physical_confirmation']=bind(tmp,'physical.json',fixture)
    q['bootstrap_authority']=bind(tmp,'authority.json',authority)
    return m


def replace_record(m,key,tmp,change):
    row=m['isolated_qualification'][key]
    r=json.loads(Path(row['path']).read_text());change(r)
    m['isolated_qualification'][key]=bind(tmp,'changed-'+key+'.json',r)


def test_exact_original_confirmation_and_explicit_bootstrap_exception_once(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    result=isolated.preflight(m,consume=True,used_dir=tmp_path/'used')
    assert result['preprogram_readiness']=='first-isolated-bootstrap-readiness-exception'
    with pytest.raises(RuntimeError,match='already consumed'):
        isolated.preflight(m,consume=True,used_dir=tmp_path/'used')


def test_exact_scope_authorisation_does_not_expire_while_preparing(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    replace_record(m,'bootstrap_authority',tmp_path,lambda r:r.update(observed_unix=1.))
    assert isolated.preflight(m)['preprogram_readiness']=='first-isolated-bootstrap-readiness-exception'


def standing_fixture(m,tmp):
    message=bind(tmp,'standing-fixture-message.txt',
                 b'TEST ONLY: The wires remain connected as confirmed until I report a change or you request one.')
    def change(r):
        r.update(observed_unix=1.,original_message=message,exact_quote='TEST ONLY:',
                 validity='until-wiring-change',
                 continuity_quote='The wires remain connected as confirmed until I report a change or you request one.')
    replace_record(m,'physical_confirmation',tmp,change)


def test_explicit_standing_fixture_confirmation_keeps_original_time(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    standing_fixture(m,tmp_path)
    isolated.preflight(m)
    r=json.loads(Path(m['isolated_qualification']['physical_confirmation']['path']).read_text())
    assert r['observed_unix']==1.


@pytest.mark.parametrize('field,value',[
    ('validity','forever'),('continuity_quote',''),
    ('continuity_quote','invented operator instruction'),('observed_unix',1001.),
    ('observed_unix',float('nan')),('wiring_change_reported',True),
    ('wiring_change_requested',True),
])
def test_standing_fixture_is_not_generic_or_unrevokable_permission(tmp_path,monkeypatch,field,value):
    m=admission(tmp_path,monkeypatch)
    standing_fixture(m,tmp_path)
    replace_record(m,'physical_confirmation',tmp_path,lambda r:r.update({field:value}))
    with pytest.raises(RuntimeError):isolated.preflight(m)


def test_standing_fixture_does_not_extend_image_scope_or_replay_authority(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    standing_fixture(m,tmp_path)
    isolated.preflight(m,consume=True,used_dir=tmp_path/'used')
    with pytest.raises(RuntimeError,match='already consumed'):
        isolated.preflight(m,consume=True,used_dir=tmp_path/'used')
    m['image']['sha256']='e'*64
    with pytest.raises(RuntimeError,match='scope'):isolated.preflight(m)


@pytest.mark.parametrize('key,field,value',[
    ('physical_confirmation','actor','agent'),
    ('physical_confirmation','origin','manifest'),
    ('physical_confirmation','physical_basis','emit-off'),
    ('physical_confirmation','measurement_point','post-shifter5V'),
    ('physical_confirmation','observed_unix',700),
    ('physical_confirmation','observed_unix',1001),
    ('physical_confirmation','exact_quote','not in original statement'),
    ('physical_confirmation','message_reference',''),
    ('bootstrap_authority','decision','general-approval'),
    ('bootstrap_authority','exception',True),
    ('bootstrap_authority','decision_id','../unsafe'),
    ('bootstrap_authority','fixture_id','another-fixture'),
])
def test_attestation_stale_scope_and_generic_approval_cannot_admit(tmp_path,monkeypatch,key,field,value):
    m=admission(tmp_path,monkeypatch)
    replace_record(m,key,tmp_path,lambda r:r.update({field:value}))
    with pytest.raises(RuntimeError):isolated.preflight(m)


@pytest.mark.parametrize('field,value',[
    ('image_sha256','e'*64),('identity','wrong'),('recovery_sha256','a'*64),
    ('jumpers',[]),('electrically_excluded',['P601-product-DIN']),('maximum_interruption_seconds',121)])
def test_confirmation_must_bind_every_exact_scope_field(tmp_path,monkeypatch,field,value):
    m=admission(tmp_path,monkeypatch)
    replace_record(m,'physical_confirmation',tmp_path,lambda r:r['scope'].update({field:value}))
    with pytest.raises(RuntimeError,match='scope'):isolated.preflight(m)


def test_naked_booleans_never_replace_original_records(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    m['isolated_qualification'].update(physical_confirmation={'isolated':True},bootstrap_authority=True)
    with pytest.raises((RuntimeError,KeyError,TypeError)):isolated.preflight(m)


def rfp_log(image, *, verify=True):
    return (f'Renesas Flash Programmer CLI V1.17\nLoad: "{image}" (Size=123, CRC=12345678)\n'
      'Interface: SWD\nSpeed: 1,000,000 Hz\nTool: E2 emulator Lite (5AS079228B)\nEmulator power supply: OFF\nConnected to R7KA8P1KFLCAC\n'
      'Writing data to the target device\n [Code MRAM 1] 02000000 - 02000FFF\n100%\n'+
      ('Verifying data on the target device\n [Code MRAM 1] 02000000 - 02000FFF\n100%\n' if verify else '')+
      'Disconnecting the tool\nOperation successful\n').encode()


def test_programmer_exit_zero_is_not_readback(tmp_path):
    image=tmp_path/'candidate.hex';argv=['rfp','-run','-pv',str(image)]
    good=isolated.verify_program_log(rfp_log(image),returncode=0,argv=argv,image=image,spans=[(0x2000000,0x2000010)])
    assert good['readback_verified'] and not good['raw_memory_dump_exported']
    with pytest.raises(RuntimeError,match='verify'):
        isolated.verify_program_log(rfp_log(image,verify=False),returncode=0,argv=argv,image=image,spans=[(0x2000000,0x2000010)])


@pytest.mark.parametrize('fault',['returncode','image','power','probe','target','partial','range','error','version'])
def test_program_verify_failures(tmp_path,fault):
    image=tmp_path/'candidate.hex';raw=rfp_log(image);code=0;spans=[(0x2000000,0x2000010)]
    if fault=='returncode':code=1
    if fault=='image':raw=raw.replace(str(image).encode(),b'wrong.hex')
    if fault=='power':raw=raw.replace(b'supply: OFF',b'supply: ON')
    if fault=='probe':raw=raw.replace(b'5AS079228B',b'wrongprobe')
    if fault=='target':raw=raw.replace(b'R7KA8P1KFLCAC',b'unknown')
    if fault=='partial':raw=raw.split(b'Verifying data on the target device')[0]+b'Verifying data on the target device\nOperation successful\n'
    if fault=='range':spans=[(0x2000000,0x2002000)]
    if fault=='error':raw+=b'ERROR\n'
    if fault=='version':raw=raw.replace(b'V1.17',b'V2.0')
    with pytest.raises(RuntimeError):
        isolated.verify_program_log(raw,returncode=code,argv=['rfp','-run','-pv',str(image)],image=image,spans=spans)


def add_completion(m, tmp, kind='measure'):
    if kind == 'golden':
        from test_prism_completion import golden
        spec = golden(tmp)
    else:
        spec = dict(kind=kind, seconds=20, live_source='D', observer_enabled=False)
    m['isolated_qualification']['completion_request'] = bind(tmp, 'completion.json', spec)
    scope = isolated._scope(m)
    reviewed = bind(tmp, 'completion-reviewed.json', {'scope': scope})
    for key in ('physical_confirmation', 'bootstrap_authority'):
        replace_record(m, key, tmp, lambda r:r.update(scope=scope, reviewed_request=reviewed))
    return spec


@pytest.mark.parametrize('kind',[None,'golden','measure'])
@pytest.mark.parametrize('failure',[None,'program','capture','recovery','launch_ambiguous','usb_missing','usb_owned','cancel','collector_unconfirmed'])
def test_actual_transaction_runs_one_attempt_and_recovers_on_failure(tmp_path,monkeypatch,failure,kind):
    from ael import prism_native
    m=admission(tmp_path,monkeypatch)
    spec = add_completion(m, tmp_path, kind) if kind else None
    real_preflight=isolated.preflight
    monkeypatch.setattr(isolated,'preflight',lambda m,consume=False:real_preflight(m,consume=consume,used_dir=tmp_path/'used'))
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    monkeypatch.setattr(bench,'deployment_argv',fake_deployment_with_settings)
    monkeypatch.setattr(bench,'hex_spans',lambda p:[(0x2000000,0x2000010)])
    monkeypatch.setattr(isolated,'usb_anchor',lambda port,**kw:{'location':'TEST'})
    def resolve(anchor,deadline):
        if failure=='usb_missing':raise TimeoutError('native identity absent')
        return {'device':'/dev/cu.NEW'}
    def owner(port,deadline):
        if failure=='usb_owned':raise RuntimeError('interface owned')
    monkeypatch.setattr(isolated,'wait_for_native_interface',resolve)
    monkeypatch.setattr(isolated,'require_interface_unowned',owner)
    events=[]
    def run(argv,stdout,**kwargs):
        programme=Path(argv[-1])
        is_recovery=programme.name.startswith('donor-recovery')
        events.append('recovery' if is_recovery else 'program')
        if failure=='launch_ambiguous' and not is_recovery:raise TimeoutError('launch outcome unknown')
        image=tmp_path/('donor.hex' if is_recovery else 'candidate.hex')
        stdout.write(b'gateway\n')
        bad=(failure=='program' and not is_recovery) or (failure=='recovery' and is_recovery)
        rc=int(bad)
        if rc==0:
            programme.mkdir()
            inner=['/opt/rfp-cli','-run','-pv',str(image)]
            (programme/'receipt.json').write_text(json.dumps({'pass':True,'execute':True,'returncode':0,'command':inner}))
            Path(str(programme)+'.stdout').write_bytes(rfp_log(image))
        return SimpleNamespace(returncode=rc)
    def session(*args,**kwargs):
        # Recovery-only historical fixture: current route availability is tested separately.
        if failure=='usb_missing': raise TimeoutError('broker identity absent')
        if failure=='usb_owned': raise RuntimeError('broker owner identity mismatch')
        events.append('capture')
        assert args[0]['broker_socket'].endswith('/titan-control.sock')
        assert args[0]['broker_manifest']['sha256'] == digest(Path(args[0]['broker_manifest']['path']).read_bytes())
        assert 'deadline' in kwargs
        assert kwargs['operation_sha256'] == digest(Path(args[3]).read_bytes())
        operation = json.loads(Path(args[3]).read_text())
        assert set(operation) == ({'completion'} if kind else {'isolated_capture'})
        if kind: assert operation['completion'] == spec
        if failure=='collector_unconfirmed':
            exc=RuntimeError('capture cancellation unconfirmed')
            exc.collector_quiesced=False
            raise exc
        if failure=='capture':raise RuntimeError('injected capture failure')
        if failure=='cancel':raise KeyboardInterrupt('injected cancellation')
        return {'raw':'TEST ONLY','physical_qualification':False}
    mock_deployment(monkeypatch, run)
    monkeypatch.setattr(prism_native,'run_session',session)
    facts={}
    if failure:
        with pytest.raises((RuntimeError,TimeoutError,KeyboardInterrupt)):isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    else:
        isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    assert events==(['program','capture'] if failure=='collector_unconfirmed' else ['program','recovery'] if failure in ('program','launch_ambiguous','usb_missing','usb_owned') else ['program','capture','recovery'])
    if failure=='collector_unconfirmed':
        assert facts['collector_quiesced'] is False
        assert 'donor recovery forbidden' in facts['recovery_error']
    assert facts['known_donor_program_and_verify_completed'] is (failure not in ('recovery','collector_unconfirmed'))
    assert facts['hardware_access'] is True and facts['candidate_program_attempted'] is True
    assert facts['programmed'] is (failure not in ('program','launch_ambiguous'))
    assert facts['candidate_readback_verified'] == facts['programmed']
    if facts['programmed']:assert facts['candidate_readback_method']=='RFP1.17 -pv target-memory comparison'
    assert (tmp_path/'isolated-transaction.json').is_file()
    if not failure:
        assert ('isolated_completion' in facts) is bool(kind)


@pytest.mark.parametrize('fault',['hash','altered_scope','mixed','save','endurance','unknown','expired','replay'])
def test_completion_admission_refuses_before_hardware(tmp_path, monkeypatch, fault):
    m = admission(tmp_path, monkeypatch)
    add_completion(m, tmp_path)
    q = m['isolated_qualification']
    if fault == 'hash': Path(q['completion_request']['path']).write_text('{}')
    if fault == 'altered_scope':
        q['completion_request'] = bind(tmp_path, 'changed-request.json', dict(kind='measure',seconds=1,live_source='A',observer_enabled=True))
    if fault == 'mixed': q['pattern'] = 2
    if fault in ('save','endurance','unknown'):
        spec = json.loads(Path(q['completion_request']['path']).read_text())
        if fault == 'save': spec['save'] = True
        else: spec['kind'] = fault
        q['completion_request'] = bind(tmp_path, 'invalid-request.json', spec)
    if fault == 'expired':
        replace_record(m, 'physical_confirmation', tmp_path, lambda r:r.update(observed_unix=700))
    if fault == 'replay':
        isolated.preflight(m, consume=True, used_dir=tmp_path/'used')
        with pytest.raises(RuntimeError, match='already consumed'):
            isolated.preflight(m, consume=True, used_dir=tmp_path/'used')
        return
    monkeypatch.setattr(bench,'validate_manifest',lambda cfg,facts:(m,tmp_path,Path(m['image']['path']),'titan'))
    forbidden = Mock(side_effect=AssertionError('hardware reached'))
    monkeypatch.setattr(bench, 'authorise', forbidden)
    monkeypatch.setattr(bench.subprocess, 'run', forbidden)
    with pytest.raises((RuntimeError,ValueError)):
        bench.execute({'action':'bench-trial-qualify-isolated'},SimpleNamespace(logs_dir=tmp_path),{})
    forbidden.assert_not_called()


def test_completion_standing_fixture_preserves_time_and_request_identity(tmp_path, monkeypatch):
    m = admission(tmp_path, monkeypatch)
    add_completion(m, tmp_path)
    standing_fixture(m, tmp_path)
    assert isolated.preflight(m)['scope']['completion'] == {
        'kind':'measure', 'request_sha256':m['isolated_qualification']['completion_request']['sha256']}
    assert json.loads(Path(m['isolated_qualification']['physical_confirmation']['path']).read_text())['observed_unix'] == 1.


@pytest.mark.parametrize('key', ['save', 'endurance', 'evaluation_drive', 'disconnect_check', 'other_request'])
def test_isolated_sibling_request_cannot_be_ignored(tmp_path, monkeypatch, key):
    m=admission(tmp_path,monkeypatch)
    m['isolated_qualification'][key]={}
    with pytest.raises(RuntimeError,match='Unknown isolated'):
        isolated.preflight(m)


@pytest.mark.parametrize('fault', ['late_candidate', 'late_recovery', 'primary_and_overrun',
                                 'primary_and_recovery_fail', 'anchor_expired'])
def test_absolute_programmer_bounds_and_failure_receipts(tmp_path, monkeypatch, fault):
    from ael import prism_native
    m=admission(tmp_path,monkeypatch); now=[0.]; events=[]; timeouts=[]
    real_preflight=isolated.preflight
    monkeypatch.setattr(isolated,'preflight',lambda m,consume=False:
        real_preflight(m,consume=consume,used_dir=tmp_path/'used'))
    monkeypatch.setattr(isolated.time,'monotonic',lambda:now[0])
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    monkeypatch.setattr(bench,'deployment_argv',fake_deployment_with_settings)
    monkeypatch.setattr(bench,'hex_spans',lambda p:[(0x2000000,0x2000010)])
    donor=usb_port(m['port'],'0000000000001')
    def inventory():
        now[0]=81. if fault=='anchor_expired' else 79.
        return [donor]
    anchor=isolated.usb_anchor
    monkeypatch.setattr(isolated,'usb_anchor',lambda port,**kw:anchor(port,inventory=inventory,**kw))
    monkeypatch.setattr(isolated,'wait_for_native_interface',lambda *a:{'device':'/dev/cu.NEW'})
    monkeypatch.setattr(isolated,'require_interface_unowned',lambda *a:None)
    def run(argv,stdout,timeout,**kw):
        programme=Path(argv[-1])
        recovery=programme.name.startswith('donor-recovery');events.append('recovery' if recovery else 'candidate');timeouts.append(timeout)
        image=tmp_path/('donor.hex' if recovery else 'candidate.hex')
        stdout.write(b'gateway\n')
        if not recovery:now[0]=81. if fault=='late_candidate' else 79.
        else:now[0]=121. if fault in ('late_recovery','primary_and_overrun') else 90.
        rc=int(recovery and fault=='primary_and_recovery_fail')
        if rc==0:
            programme.mkdir()
            inner=['/opt/rfp-cli','-run','-pv',str(image)]
            (programme/'receipt.json').write_text(json.dumps({'pass':True,'execute':True,'returncode':0,'command':inner}))
            Path(str(programme)+'.stdout').write_bytes(rfp_log(image))
        return SimpleNamespace(returncode=rc)
    def session(*a,**kw):
        events.append('capture')
        if fault.startswith('primary'):raise KeyboardInterrupt('original cancellation retained')
        return {'TEST_ONLY':True}
    mock_deployment(monkeypatch, run)
    monkeypatch.setattr(prism_native,'run_session',session)
    facts={}
    with pytest.raises((RuntimeError,TimeoutError,KeyboardInterrupt)) as caught:
        isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    if fault=='anchor_expired':
        assert events==[] and not facts['candidate_program_attempted']
        return
    assert timeouts[0]==1. and timeouts[1] <= 90.
    assert events==(['candidate','recovery'] if fault=='late_candidate' else ['candidate','capture','recovery'])
    retained=json.loads((tmp_path/'isolated-transaction.json').read_text())
    assert retained['candidate_deadline_monotonic']==80. and retained['recovery_deadline_monotonic']==120.
    assert retained['interruption_boundary_exceeded'] is (fault in ('late_recovery','primary_and_overrun'))
    if fault.startswith('primary'):assert retained['primary_error']=='original cancellation retained'
    if fault=='primary_and_overrun':assert isinstance(caught.value,KeyboardInterrupt)
    if fault=='primary_and_recovery_fail':assert retained['recovery_error'] and not retained['known_donor_program_and_verify_completed']


def test_preflight_refusal_precedes_programmer_and_serial(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    replace_record(m,'bootstrap_authority',tmp_path,lambda r:r.update(decision='general-approval'))
    monkeypatch.setattr(bench,'validate_manifest',lambda cfg,facts:(m,tmp_path,Path(m['image']['path']),'titan'))
    forbidden=Mock(side_effect=AssertionError('hardware reached'))
    monkeypatch.setattr(bench,'authorise',forbidden)
    monkeypatch.setattr(bench.subprocess,'run',forbidden)
    with pytest.raises(RuntimeError,match='PREPROGRAM'):
        bench.execute({'action':'bench-trial-qualify-isolated'},SimpleNamespace(logs_dir=tmp_path),{})
    forbidden.assert_not_called()


def test_exact_interface_wait_is_bounded_and_does_not_scan():
    t=[10.]; polls=[]
    def present():polls.append(t[0]);return len(polls)==3
    isolated.wait_for_interface('/dev/cu.EXACT',11,clock=lambda:t[0],sleep=lambda x:t.__setitem__(0,t[0]+x),present=present)
    assert len(polls)==3
    with pytest.raises(TimeoutError):
        isolated.wait_for_interface('/dev/cu.EXACT',10.4,clock=lambda:t[0],sleep=lambda x:t.__setitem__(0,t[0]+x),present=lambda:False)
    with pytest.raises(RuntimeError):isolated.wait_for_interface('/dev/cu.*',11)


def usb_port(device, serial=None, location='0-1.2.4', vid=0x045b, pid=0x5310):
    return SimpleNamespace(device=device, serial_number=serial, location=location, vid=vid, pid=pid)


def test_native_port_changes_but_usb_identity_and_socket_remain_bound():
    donor=usb_port('/dev/cu.usbmodem00000000000011', '0000000000001')
    anchor=isolated.usb_anchor(donor.device, inventory=lambda:[donor])
    native=usb_port('/dev/cu.usbmodem12401', bytes.fromhex(UID)[::-1].hex())
    resolved=isolated.wait_for_native_interface(anchor, 11, clock=lambda:10,
        inventory=lambda:[native, usb_port('/dev/cu.UNRELATED', vid=0x303a)])
    assert resolved['device']==native.device
    assert resolved['location']==anchor['location']


@pytest.mark.parametrize('change', ['serial','location','vid','pid'])
def test_native_port_rejects_other_device_and_expires(change):
    anchor={'device':'/dev/cu.DONOR','location':'0-1.2.4'}
    native=usb_port('/dev/cu.NEW', bytes.fromhex(UID)[::-1].hex())
    setattr(native, {'serial':'serial_number'}.get(change,change), 'wrong' if change in ('serial','location') else 1)
    now=[10.]
    with pytest.raises(TimeoutError):
        isolated.wait_for_native_interface(anchor,10.3,clock=lambda:now[0],
            sleep=lambda dt:now.__setitem__(0,now[0]+dt),inventory=lambda:[native])


def test_native_port_rejects_ambiguous_matches_and_missing_donor_location():
    n=usb_port('/dev/cu.NEW',bytes.fromhex(UID)[::-1].hex())
    with pytest.raises(RuntimeError,match='Ambiguous'):
        isolated.wait_for_native_interface({'location':n.location},11,clock=lambda:10,inventory=lambda:[n,n])
    with pytest.raises(RuntimeError,match='location'):
        isolated.usb_anchor('/dev/cu.DONOR',inventory=lambda:[usb_port('/dev/cu.DONOR',location=None)])


@pytest.mark.parametrize('rc,stdout,stderr',[(0,'123\n',''),(1,'','error'),(2,'','')])
def test_resolved_interface_ownership_failures_are_not_clear(monkeypatch,rc,stdout,stderr):
    monkeypatch.setattr(isolated.time,'monotonic',lambda:10.)
    monkeypatch.setattr(isolated.subprocess,'run',lambda *a,**kw:SimpleNamespace(
        returncode=rc,stdout=stdout,stderr=stderr))
    with pytest.raises(RuntimeError,match='owned'):
        isolated.require_interface_unowned('/dev/cu.NEW',11.)


def test_actual_cli_template_is_useful_but_cannot_create_authority(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    original=tmp_path/'manifest.json';original.write_text(json.dumps(m))
    output=tmp_path/'isolated.json'
    run=subprocess.run([sys.executable,'-m','ael.titan_capture','isolated-template',
                        '--manifest',str(original),'--output',str(output)],capture_output=True,text=True)
    assert run.returncode==2 and output.exists()
    result=json.loads(run.stdout)
    assert result['scope']['image_sha256']==m['image']['sha256']
    prepared=json.loads(output.read_text())
    assert prepared['isolated_qualification']['physical_confirmation'] is None
    assert prepared['isolated_qualification']['bootstrap_authority'] is None
    run=subprocess.run([sys.executable,'-m','ael.titan_capture','isolated-preflight',
                        '--manifest',str(output)],capture_output=True,text=True)
    assert run.returncode==2
    assert json.loads(run.stdout)['hardware_mutated'] is False
    assert 'Missing bound original record' in json.loads(run.stdout)['error']


@pytest.mark.parametrize('failure',['image_changed','invocation_log_exists','raw_log_exists'])
def test_preinvocation_failure_never_programs_or_recovers(tmp_path,monkeypatch,failure):
    m=admission(tmp_path,monkeypatch)
    real_preflight=isolated.preflight
    def preflight(m,consume=False):
        result=real_preflight(m,consume=consume,used_dir=tmp_path/'used')
        if failure=='image_changed':Path(m['image']['path']).write_bytes(b'changed after admission')
        elif failure=='invocation_log_exists':(tmp_path/'candidate-invocation.json').write_text('retained')
        else:(tmp_path/'candidate.log').write_bytes(b'retained')
        return result
    monkeypatch.setattr(isolated,'preflight',preflight)
    monkeypatch.setattr(isolated,'usb_anchor',lambda port,**kw:{'location':'TEST'})
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    monkeypatch.setattr(bench,'deployment_argv',fake_deployment_with_settings)
    run=Mock(side_effect=AssertionError('Pre-invocation refusal must not program even donor'))
    mock_deployment(monkeypatch, run)
    facts={}
    with pytest.raises((RuntimeError,FileExistsError)):
        isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    run.assert_not_called()
    assert facts['hardware_access'] is False and facts['programmed'] is False
    assert facts['candidate_program_attempted'] is False and facts['candidate_readback_verified'] is False
    assert 'donor_recovery_event' not in facts


def test_constant_diagnostic_changes_bound_operation_scope(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    m['isolated_qualification']['constant_timer_diagnostic']=1
    assert isolated._scope(m)['constant_timer_diagnostic']==1
    with pytest.raises(RuntimeError,match='exact isolated scope'):
        isolated.preflight(m)


def test_split_pattern_preflight_binds_exact_scoped_pattern(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    m['isolated_qualification'].update(backend=isolated.SPLIT_BACKEND,pattern=2)
    assert isolated._scope(m)['pattern']==2
    with pytest.raises(RuntimeError,match='exact isolated scope'):
        isolated.preflight(m)


@pytest.mark.parametrize('pattern',[-1,120,True,'2'])
def test_invalid_split_pattern_refused_before_authority(tmp_path,monkeypatch,pattern):
    m=admission(tmp_path,monkeypatch)
    m['isolated_qualification'].update(backend=isolated.SPLIT_BACKEND,pattern=pattern)
    with pytest.raises(RuntimeError,match='Invalid scoped pattern'):
        isolated.preflight(m)


@pytest.mark.parametrize('backend',[isolated.BACKEND,isolated.SPLIT_BACKEND])
def test_capture_gateway_routes_both_loopback_backends_through_admission(tmp_path,monkeypatch,backend):
    from ael.titan_capture import isolated_preflight
    m=admission(tmp_path,monkeypatch)
    m['isolated_qualification']['backend']=backend
    assert isolated_preflight(m)['preprogram_readiness']=='first-isolated-bootstrap-readiness-exception'
    replace_record(m,'physical_confirmation',tmp_path,lambda r:r.update(actor='agent'))
    with pytest.raises(RuntimeError,match='Actual operator message required'):
        isolated_preflight(m)


def test_direct_backend_requires_actual_new_endpoint_scope(tmp_path,monkeypatch):
    m=admission(tmp_path,monkeypatch)
    old_scope=isolated._scope(m)
    m['isolated_qualification']['backend']=isolated.DIRECT_BACKEND
    scope=isolated._scope(m)
    assert scope['jumpers']==[['U18.7/P601','U18.33/P603'],['U18.12/P604','U18.36/P714']]
    assert scope['backend']==isolated.DIRECT_BACKEND and scope['capture_schema']==3
    assert old_scope['jumpers']==isolated.JUMPERS
    from ael.titan_capture import isolated_preflight
    with pytest.raises(RuntimeError,match='exact isolated scope'):isolated_preflight(m)

import os
import tempfile
import unittest
from unittest import mock

def recovery_test_fixture():
    """AEL_TITAN_RECOVERY_FIXTURE selects immutable rows; mutations use per-test temp."""
    config = os.environ.get('AEL_TITAN_RECOVERY_FIXTURE')
    required = os.environ.get('AEL_TITAN_RECOVERY_FIXTURE_REQUIRED') == '1'
    if not config:
        if required:
            raise RuntimeError('Supplied recovery fixture is required')
        raise unittest.SkipTest('Optional immutable recovery fixture not configured')
    path = Path(config).resolve()
    if not path.is_file():
        raise RuntimeError('Configured recovery fixture is missing')
    data = json.loads(path.read_text())
    if data.get('schema') != 'titan.recovery.test-fixture.v1':
        raise RuntimeError('Wrong recovery test fixture schema')
    result = {}
    for branch in ['current', 'legacy']:
        result[branch] = {'identity':bench.TITAN_RECOVERY_UID, 'recovery':{}}
        for name, row in data[branch].items():
            f = (path.parent / row['path']).resolve()
            if not f.is_file() or bench.sha(f) != row['sha256']:
                raise RuntimeError('Missing/changed immutable recovery fixture: '+branch+'/'+name)
            result[branch]['recovery'][name] = {'path':str(f),'sha256':row['sha256']}
    return result

class TestCurrentRangeCoverage(unittest.TestCase):
    def setUp(self):
        self.fixture=recovery_test_fixture()['current']
        self.image=Path(self.fixture['recovery']['image']['path'])
        # Synthetic future-programmer fixture, never historical device evidence.
        self.raw=(f'Renesas Flash Programmer CLI V1.17\nLoad: "{self.image}" (Size=TEST, CRC=TEST)\n'
          'Interface: SWD\nSpeed: 1,000,000 Hz\nTool: E2 emulator Lite (5AS079228B)\nEmulator power supply: OFF\nConnected to R7KA8P1KFLCAC\n'
          'Writing data to the target device\n [Code MRAM 1] 02000000 - 0208271F\n100%\n'
          'Verifying data on the target device\n [Code MRAM 1] 02000000 - 0208271F\n100%\n'
          'Disconnecting the tool\nOperation successful\n').encode()

    def test_future_verifier_covers_every_derived_span(self):
        result=isolated.verify_program_log(self.raw,returncode=0,
            argv=['rfp-cli','-run','-pv',str(self.image)],image=self.image,
            spans=bench.hex_spans(self.image))
        self.assertTrue(result['readback_verified'])
        self.assertEqual(result['verified_ranges'],[(0x02000000,0x02082720)])

    def test_root_rejection_full_image_span_not_covered(self):
        with self.assertRaisesRegex(RuntimeError,'cover exact image'):
            isolated.verify_program_log(self.raw,returncode=0,
                argv=['rfp-cli','-run','-pv',str(self.image)],image=self.image,
                spans=bench.hex_spans(Path(self.fixture['recovery']['source_image']['path'])))

    def test_partial_or_wrong_verified_ranges_refused(self):
        for value in [b'0208270F',b'02001000',b'0208271E']:
            with self.subTest(end=value):
                raw=self.raw.replace(b'0208271F',value)
                with self.assertRaisesRegex(RuntimeError,'cover exact image'):
                    isolated.verify_program_log(raw,returncode=0,
                        argv=['rfp-cli','-run','-pv',str(self.image)],image=self.image,
                        spans=bench.hex_spans(self.image))

    def test_scope_binds_actual_derived_recovery_identity(self):
        m={'identity':bench.TITAN_RECOVERY_UID,'image':{'sha256':'candidate'},
           'source_binding_hash':'source','source_commit':'commit','build_receipt':{'sha256':'build'},
           'recovery':{'image':{'sha256':bench.sha(self.image)}},
           'isolated_qualification':{'frames':100}}
        self.assertEqual(isolated._scope(m)['recovery_sha256'],bench.sha(self.image))


@pytest.mark.parametrize('branch', ['legacy', 'current'])
def test_actual_execute_recovery_event_uses_validated_identity(tmp_path, monkeypatch, branch):
    """Execute real preflight/transaction; all hardware boundaries are mocked."""
    from ael import prism_native
    fixture = recovery_test_fixture()[branch]
    validator = bench.require_titan_recovery
    m = admission(tmp_path, monkeypatch)
    m['recovery'] = copy.deepcopy(fixture['recovery'])
    m['image'] = bind(tmp_path, 'candidate.hex', Path(m['recovery']['image']['path']).read_bytes())
    m['source_binding_hash'] = 'CANDIDATE-TEST-BINDING'
    monkeypatch.setattr(bench, 'require_titan_recovery', validator)
    scope=isolated._scope(m)
    reviewed=bind(tmp_path, 'r3-reviewed.json', {'scope':scope})
    for key in ['physical_confirmation','bootstrap_authority']:
        replace_record(m,key,tmp_path,lambda r:r.update(scope=scope,reviewed_request=reviewed))
    admitted=validator(m)
    real_preflight=isolated.preflight
    monkeypatch.setattr(isolated,'preflight',lambda m,consume=False:real_preflight(
        m,consume=consume,used_dir=tmp_path/'used'))
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    monkeypatch.setattr(bench,'deployment_argv',fake_deployment_with_settings)
    monkeypatch.setattr(isolated,'usb_anchor',lambda port,**kw:{'location':'TEST ONLY'})
    monkeypatch.setattr(isolated,'wait_for_native_interface',lambda *args:{'device':'/dev/cu.TEST_ONLY'})
    monkeypatch.setattr(isolated,'require_interface_unowned',lambda *args:None)
    calls=[]
    def programmer(argv,stdout,**kwargs):
        programme=Path(argv[-1])
        image=Path(m['recovery']['image']['path'] if programme.name.startswith('donor-recovery') else m['image']['path'])
        calls.append(str(image))
        programme.mkdir()
        spans=bench.recovery_merged_spans(bench.recovery_hex_bytes(image)[0])
        ranges=''.join(f' [Code MRAM 1] {a:08X} - {b-1:08X}\n' for a,b in spans)
        # Synthetic response from mock; never a historical receipt or device claim.
        raw=(f'Renesas Flash Programmer CLI V1.17\nLoad: "{image}" (Size=TEST, CRC=TEST)\n'
          'Interface: SWD\nSpeed: 1,000,000 Hz\nTool: E2 emulator Lite (5AS079228B)\nEmulator power supply: OFF\nConnected to R7KA8P1KFLCAC\n'
          'Writing data to the target device\n'+ranges+'100%\n'
          'Verifying data on the target device\n'+ranges+'100%\n'
          'Disconnecting the tool\nOperation successful\n').encode()
        inner=['/opt/rfp-cli','-run','-pv',str(image)]
        (programme/'receipt.json').write_text(json.dumps({'pass':True,'execute':True,'returncode':0,'command':inner}))
        Path(str(programme)+'.stdout').write_bytes(raw)
        stdout.write(b'gateway\n')
        return SimpleNamespace(returncode=0)
    mock_deployment(monkeypatch, programmer)
    monkeypatch.setattr(prism_native,'run_session',lambda *args,**kwargs:{'TEST_ONLY':True})
    facts={}
    isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    recovery=json.loads((tmp_path/'donor-recovery-programming-event.json').read_text())
    candidate=json.loads((tmp_path/'candidate-programming-event.json').read_text())
    assert recovery['image_sha256']==admitted['image_sha256']
    assert recovery['source_binding_hash']==admitted['build_source_sha256']
    assert recovery['image_file']==m['recovery']['image']
    assert candidate['source_binding_hash']=='CANDIDATE-TEST-BINDING'
    assert candidate['image_sha256']==m['image']['sha256']
    assert len(calls)==2


def test_transaction_uses_recovery_spans_only_on_return_leg(tmp_path, monkeypatch):
    calls = []
    original = bench.recovery_programmed_spans
    def recovery_spans(manifest, image):
        calls.append(image.name)
        return original(manifest, image)
    monkeypatch.setattr(bench, 'recovery_programmed_spans', recovery_spans)
    test_actual_transaction_runs_one_attempt_and_recovers_on_failure(tmp_path, monkeypatch, None, None)
    assert calls == ['donor.hex']


# Scope geometry (21 Oct 2026). Status v7 sources declare 80 px lanes: 3840 bits, 480 bytes.
# Golden hashes were computed from the pre-change _scope (HEAD a manifest without bits_each),
# so an absent field must still produce those exact scope bytes and retained grants stay valid.
SCOPE_GOLDEN = {
    isolated.REPLACEMENT_BACKEND: ("5d9f13d6128affa3d3f2d1d718753303283d9fb9db32fd822ea411cb74f0411d",
                                   "3cab17f76c78cd0c7a58d0f3418769dc85d89a69f4c8aa05ce1ff849ff4f92a0"),
    isolated.PAIRED_BACKEND: ("1016055660f678b630fdd2005f3bfeb9a0c6bce561e861e2cadf2b015aa400c1",
                              "d16ce61adfdbfeeb3ce1056b5756511cfe6c3021cbb7a82ce6583e18e2d7c01d"),
}


def scope_manifest(backend, **qualification):
    return {'target':'titan-replacement','identity':UID,'source_binding_hash':'b'*64,'source_commit':'c'*40,
            'image':{'path':'/nonexistent/candidate.hex','sha256':'a'*64},'build_receipt':{'sha256':'d'*64},
            'recovery':{'image':{'path':'/nonexistent/donor.hex','sha256':'e'*64}},
            'isolated_qualification':dict({'operation':isolated.OPERATION,'backend':backend,'frames':100,
                                           'maximum_interruption_seconds':120}, **qualification)}


@pytest.mark.parametrize('backend', sorted(SCOPE_GOLDEN))
def test_scope_without_bits_each_is_byte_identical_to_the_retained_scope(backend):
    import hashlib
    scope = isolated._scope(scope_manifest(backend))
    insertion, canonical = SCOPE_GOLDEN[backend]
    assert hashlib.sha256(json.dumps(scope).encode()).hexdigest() == insertion
    assert hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == canonical
    assert (scope['bits_each'], scope['bytes_each']) == (7680, 960)


@pytest.mark.parametrize('backend', sorted(SCOPE_GOLDEN))
def test_v7_scope_declares_3840_bit_480_byte_lanes(backend):
    old = isolated._scope(scope_manifest(backend))
    new = isolated._scope(scope_manifest(backend, bits_each=3840))
    assert (new['bits_each'], new['bytes_each']) == (3840, 480)
    assert list(new) == list(old)  # same keys, same order; only the geometry values move
    assert {k: v for k, v in new.items() if k not in ('bits_each', 'bytes_each')} == \
           {k: v for k, v in old.items() if k not in ('bits_each', 'bytes_each')}
    # An explicit 7680 is the same scope as an absent field.
    assert isolated._scope(scope_manifest(backend, bits_each=7680)) == old


@pytest.mark.parametrize('bits', [1920, 3841, 960, 0, -3840, '3840', 3840.0, True, None])
def test_scope_refuses_unknown_lane_geometry(bits):
    with pytest.raises(RuntimeError, match='bits_each must be 3840 or 7680'):
        isolated._scope(scope_manifest(isolated.PAIRED_BACKEND, bits_each=bits))


def test_scope_bits_each_is_refused_outside_the_replacement_backends():
    with pytest.raises(RuntimeError, match='only to the replacement capture backends'):
        isolated._scope(scope_manifest(isolated.BACKEND, bits_each=3840))
