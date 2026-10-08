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


def bind(tmp,name,data):
    p=tmp/name
    p.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode())
    return {'path':str(p),'sha256':digest(p.read_bytes())}


def admission(tmp,monkeypatch):
    monkeypatch.setattr(isolated.time,'time',lambda:1000.)
    monkeypatch.setattr(bench,'require_titan_recovery',lambda m:{'exact_donor':'TEST ONLY'})
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
      'Tool: E2 emulator Lite (5AS079228B)\nEmulator power supply: OFF\nConnected to R7KA8P1KFLCAC\n'
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
    if fault=='partial':raw=raw.rsplit(b'100%',1)[0]+b'Operation successful\n'
    if fault=='range':spans=[(0x2000000,0x2002000)]
    if fault=='error':raw+=b'ERROR\n'
    if fault=='version':raw=raw.replace(b'V1.17',b'V2.0')
    with pytest.raises(RuntimeError):
        isolated.verify_program_log(raw,returncode=code,argv=['rfp','-run','-pv',str(image)],image=image,spans=spans)


@pytest.mark.parametrize('failure',[None,'program','capture','recovery'])
def test_actual_transaction_runs_one_attempt_and_recovers_on_failure(tmp_path,monkeypatch,failure):
    from ael import prism_native
    m=admission(tmp_path,monkeypatch)
    real_preflight=isolated.preflight
    monkeypatch.setattr(isolated,'preflight',lambda m,consume=False:real_preflight(m,consume=consume,used_dir=tmp_path/'used'))
    monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
    monkeypatch.setattr(bench,'programmer_argv',lambda m,p,b,recover=False:['rfp','-run','-pv',str(p)])
    monkeypatch.setattr(bench,'hex_spans',lambda p:[(0x2000000,0x2000010)])
    monkeypatch.setattr(isolated,'wait_for_interface',lambda port,deadline:None)
    events=[]
    def run(argv,stdout,**kwargs):
        is_recovery=argv[-1].endswith('donor.hex')
        events.append('recovery' if is_recovery else 'program')
        stdout.write(rfp_log(Path(argv[-1])))
        bad=(failure=='program' and not is_recovery) or (failure=='recovery' and is_recovery)
        return SimpleNamespace(returncode=int(bad))
    def session(*args,**kwargs):
        events.append('capture')
        assert 'deadline' in kwargs
        if failure=='capture':raise RuntimeError('injected capture failure')
        return {'raw':'TEST ONLY','physical_qualification':False}
    monkeypatch.setattr(isolated.subprocess,'run',run)
    monkeypatch.setattr(prism_native,'run_session',session)
    facts={}
    if failure:
        with pytest.raises(RuntimeError):isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    else:
        isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
    assert events==(['program','recovery'] if failure=='program' else ['program','capture','recovery'])
    assert facts['known_donor_program_and_verify_completed'] is (failure!='recovery')
    assert (tmp_path/'isolated-transaction.json').is_file()


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
