"""File-only actual sealed-writer replay; never launches a deployment."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ael import titan_isolated as isolated
from ael.adapters import prism_bench_trial as bench
from test_titan_isolated import admission, fake_deployment_with_settings, mock_deployment
FIXTURE=Path(__file__).parent/'fixtures/titan-sealed-writer-real-run-01.json'
def receipt_for(image,programme):
 r=json.loads(FIXTURE.read_text()); projected=Path(str(programme)+'.writer-view')/'rtthread.hex'
 projected.parent.mkdir();projected.write_bytes(image.read_bytes())
 r['stdout']=r['stdout'].replace(r['command'][-1],str(projected));r['command'][-1]=str(projected)
 r['hex_sha256']=bench.sha(image)
 return r
@pytest.mark.parametrize('fault',[None,'projection','path','uid','hash','partial','stderr','speed'])
def test_actual_channels(tmp_path,fault):
 image=tmp_path/'image.hex';image.write_bytes(b'admitted bytes');programme=tmp_path/'candidate-programme'
 r=receipt_for(image,programme)
 if fault=='projection':Path(r['command'][-1]).write_bytes(b'changed')
 if fault=='path':r['command'][-1]=str(tmp_path/'alternate.hex')
 if fault=='uid':r['uid']='wrong'
 if fault=='hash':r['hex_sha256']='wrong'
 if fault=='partial':r['stdout']=r['stdout'].replace('Operation successful','Interrupted')
 if fault=='stderr':r['stderr']+='error: verify failed'
 if fault=='speed':r['command'][8]='2000000'
 def check():return isolated.verify_sealed_program(r,image=image,programme_dir=programme,spans=[(0x2000000,0x201a120)])
 if fault:
  with pytest.raises(RuntimeError):check()
 else:
  assert check()['readback_verified'];assert '100%' not in r['stdout'] and '100%' in r['stderr']
@pytest.mark.parametrize('partial',[False,True])
@pytest.mark.parametrize('interrupted',[False,True])
def test_caller_retains_actual_write_and_stops_capture(tmp_path,monkeypatch,partial,interrupted):
 from ael import prism_native
 m=admission(tmp_path,monkeypatch);real=isolated.preflight
 monkeypatch.setattr(isolated,'preflight',lambda m,consume=False:real(m,consume=consume,used_dir=tmp_path/'used'))
 monkeypatch.setenv('K1_RFP_SWD_EXECUTE_OK','1')
 monkeypatch.setattr(bench,'deployment_argv',fake_deployment_with_settings)
 monkeypatch.setattr(bench,'hex_spans',lambda p:[(0x2000000,0x2000010)])
 monkeypatch.setattr(isolated,'usb_anchor',lambda *a,**kw:{'location':'TEST'})
 capture=Mock(side_effect=AssertionError('capture forbidden'));monkeypatch.setattr(prism_native,'run_session',capture)
 calls=[]
 def run(argv,stdout,**kwargs):
  programme=Path(argv[-1]);programme.mkdir();candidate=programme.name=='candidate-programme'
  calls.append('candidate' if candidate else 'recovery')
  r=receipt_for(tmp_path/('candidate.hex' if candidate else 'donor.hex'),programme)
  if candidate and partial:r['pass']=False;r['returncode']=1
  (programme/'receipt.json').write_text(json.dumps(r));Path(str(programme)+'.stdout').write_text(json.dumps(r))
  stdout.write(b'broker attachment failed: legacy INFO on native\n' if candidate else b'restored\n')
  if candidate and interrupted:raise subprocess.TimeoutExpired(argv,70)
  return SimpleNamespace(returncode=2 if candidate else 0)
 mock_deployment(monkeypatch,run);facts={}
 with pytest.raises((RuntimeError,subprocess.TimeoutExpired)):isolated.execute(m,tmp_path,Path(m['image']['path']),SimpleNamespace(logs_dir=tmp_path),facts)
 assert calls==['candidate','recovery'];capture.assert_not_called()
 assert facts['programmed'] is (not partial);assert facts['candidate_readback_verified'] is (not partial)
 assert facts['candidate_gateway_returncode']==(None if interrupted else 2) and 'legacy INFO' in facts['candidate_gateway_error']
 assert facts['known_donor_program_and_verify_completed']
 if not partial and not interrupted:assert 'gateway failed after verified program/readback' in facts['primary_error']
