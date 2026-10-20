"""Offline exact June19 normal-return compatibility; no programmer is invoked."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import pytest
from ael.adapters import prism_bench_trial as bench

EVIDENCE = Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/_scratch/titan-owner-20261020/exec-current-recovery-artifacts.json')
HELPER = Path('/Users/spectrasynq/Workspace_Management/Software/agent-skills/skills/smc-titan-mixer/scripts/deploy_admission.py')

def binding(path): return {'path':str(path),'sha256':bench.sha(path)}

@pytest.fixture
def current(tmp_path):
    evidence=json.loads(EVIDENCE.read_text())
    build=tmp_path/'build';build.mkdir()
    for key,name in [('rtthread.hex','rtthread.hex'),('rtthread.elf','rtthread.elf'),('build_receipt','receipt.json')]:
        source=Path(evidence[key]['path'])
        assert bench.sha(source)==evidence[key]['sha256']
        shutil.copyfile(source,build/name)
    admission=tmp_path/'admission.json';shutil.copyfile(evidence['admission']['path'],admission)
    programmed=tmp_path/'programmed.json';shutil.copyfile(evidence['programming_receipt']['path'],programmed)
    return {'identity':bench.TITAN_RECOVERY_UID,'recovery':{
        'image':binding(build/'rtthread.hex'), 'build_receipt':binding(build/'receipt.json'),
        'qualification_receipt':binding(programmed),
        'deployment':{'build_dir':str(build),'admission':str(admission)}}}

def test_actual_installed_receipts_reach_normal_gateway_return(current,tmp_path,monkeypatch):
    monkeypatch.setattr(bench.subprocess,'run',lambda *a,**k:pytest.fail('no external process permitted'))
    result=bench.require_titan_recovery(current)
    assert result['build_source_sha256']=='aadd38b2f452393a3105b3307c345487cc54b8f7dabd6dc1cacbdf5ab2fd2030'
    assert result['programmed_spans']==[[0x02000000,0x020A6300]]
    image=Path(current['recovery']['image']['path'])
    original=bench.sha(image)
    capture=tmp_path/'prior-settings.json';capture.write_text('{"test":"only"}')
    argv=bench.deployment_argv(current,image,'donor-recovery',tmp_path/'fresh-programme',restore_settings=binding(capture))
    assert argv[1].endswith('/deploy_titan_image.sh')
    assert '--recover-known-image' not in argv and '--restore-settings' in argv
    spec=importlib.util.spec_from_file_location('normal_gateway',HELPER)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    prepared=helper.prepare(Path(argv[2]),Path(argv[3]),tmp_path/'unused-writer-view')
    assert prepared['build_id']==result['build_source_sha256']
    assert tuple(prepared[k] for k in ('build_id','hex_sha256','elf_sha256','source','schema')) not in helper.KNOWN_RECOVERY
    assert bench.sha(image)==original
    assert bench.recovery_programmed_spans(current,image)==[[0x02000000,0x020A6300]]
    assert any(a>=0x02C9F020 for a,b in bench.hex_spans(image)) # Candidate rule still sees outside record.

@pytest.mark.parametrize('field',['identity','image','elf','build_receipt','qualification_receipt','admission','deployment'])
def test_changed_exact_recovery_refused(current,tmp_path,field):
    if field=='identity':current['identity']='wrong'
    elif field=='deployment':current['recovery']['deployment']['build_dir']=str(tmp_path)
    else:
        if field=='elf':path=Path(current['recovery']['deployment']['build_dir'])/'rtthread.elf'
        elif field=='admission':path=Path(current['recovery']['deployment']['admission'])
        else:path=Path(current['recovery'][field]['path'])
        path.write_bytes(path.read_bytes()+b' ')
        if field in current['recovery']: current['recovery'][field]=binding(path)
    with pytest.raises(Exception):bench.require_titan_recovery(current)

@pytest.mark.parametrize('field,value',[('uid','wrong'),('source_pin','wrong'),('range','02000000,FFFFFFFF'),('pass',False),('execute',False),('speed_hz',2000000)])
def test_receipt_semantics_refuse_even_with_test_hash_pin(current,monkeypatch,field,value):
    path=Path(current['recovery']['qualification_receipt']['path'])
    row=json.loads(path.read_text());row[field]=value;path.write_text(json.dumps(row))
    current['recovery']['qualification_receipt']=binding(path)
    # Isolate semantic validation, without changing production pins.
    pins=dict(bench.TITAN_INSTALLED_SHOW_RECOVERY,qualification_receipt=bench.sha(path))
    monkeypatch.setattr(bench,'TITAN_INSTALLED_SHOW_RECOVERY',pins)
    with pytest.raises(RuntimeError):bench.require_titan_recovery(current)

def test_unexpected_outside_bytes_fail_before_span_exclusion(current,monkeypatch):
    real=bench.recovery_hex_bytes
    def changed(path):
        data,records=real(path);data[0x02C9F040]=0
        return data,records
    monkeypatch.setattr(bench,'recovery_hex_bytes',changed)
    with pytest.raises(RuntimeError,match='verified programming range'):
        bench.recovery_programmed_spans(current,Path(current['recovery']['image']['path']))

def test_unknown_image_keeps_every_span(tmp_path):
    image=tmp_path/'unknown.hex'
    # Exact valid Intel HEX records: no blanket filtering for the option address.
    image.write_text(':0200000402C92F\n:04F04000FFFFFFFFD0\n:00000001FF\n')
    assert bench.recovery_programmed_spans({},image)==bench.hex_spans(image)
    assert bench.hex_spans(image)==[(0x02C9F040,0x02C9F044)]
