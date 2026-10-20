"""Native update admission uses real sealed-proof validators; no device access."""
import json
from pathlib import Path
import plistlib
import struct

import pytest
from test_deploy_gateway import admission
from test_deploy_restore_integration import settings_fixture
from test_titan_repair_session import _scope_manifest, _run, Framing
from test_titan_isolated import bind
from ael.titan_waveform import digest, bound
from ael import prism_native


@pytest.fixture
def case(tmp_path, monkeypatch):
    m = _scope_manifest(tmp_path, monkeypatch)
    facts = _run(m, tmp_path, Framing(corrupt=True), [], monkeypatch)
    checkpoint = Path(facts['repair_session_path'])
    session = json.loads(checkpoint.read_text())
    image = Path(m['image']['path'])
    source, core = m['source_binding_hash'], 'c'*40
    elf = tmp_path/'titan-native.elf'
    elf.write_bytes(source.encode()+core.encode())
    receipt = dict(schema='prism-product-build.v1', exit_code=0, build_profile='titan-replacement',
        development_core=False, source_profile_sha256=source, core_commit=core,
        artefacts={'titan-native.hex':digest(image.read_bytes()), 'titan-native.elf':digest(elf.read_bytes())})
    (tmp_path/'receipt.json').write_text(json.dumps(receipt))
    record = dict(uid=admission.UID, build=source, protocol='titan-native',
        hex_sha256=digest(image.read_bytes()), elf_sha256=digest(elf.read_bytes()),
        schema_sha256=admission.HEALTH_SCHEMA, health_schema=admission.HEALTH_SCHEMA,
        identity_opcode=admission.IDENTITY_OPCODE, health_opcode=admission.HEALTH_OPCODE,
        ops=list(admission.NATIVE_OPS))
    admitted = tmp_path/'admitted.json'
    admitted.write_text(json.dumps(record))
    plist = tmp_path/'broker.plist'
    plist.write_bytes(plistlib.dumps({'EnvironmentVariables':dict(TITAN_ADMISSION_SOURCE=str(admitted),
        TITAN_ADMISSION_SHA256=digest(admitted.read_bytes()))}))
    recovery = tmp_path/'original';recovery.mkdir()
    (recovery/'rtthread.hex').write_bytes(Path(m['recovery']['image']['path']).read_bytes())
    (recovery/'rtthread.elf').write_bytes(b'exact legacy elf')
    states, identity, _, _ = settings_fixture(recovery, 'legacy')
    legacy = {'pass':True, 'build_id':identity['build'], 'source_pin':identity['source'],
        'live_schema':{'sha256':identity['schema']}, 'artifacts':{
        'rtthread.hex':digest((recovery/'rtthread.hex').read_bytes()),
        'rtthread.elf':digest((recovery/'rtthread.elf').read_bytes())}}
    (recovery/'receipt.json').write_text(json.dumps(legacy))
    saved = dict(schema='titan.deployment.settings/1', identity=identity, raw=states,
        composition=admission.user_composition('legacy', states), codec_sha256=admission.legacy_codec()[1])
    original = bind(tmp_path, 'full-original-settings.json', saved)
    session.update(prior_settings=original, recovery_image=dict(path=str(recovery/'rtthread.hex'),
        sha256=digest((recovery/'rtthread.hex').read_bytes())))
    checkpoint.write_text(json.dumps(session))
    proof = json.loads(bound(session['leave_proof']))
    identity = json.loads(bound(proof['identity_raw']))
    fresh = dict(ok=True, identity=identity, raw_hex=bound(proof['cancel_raw']).hex(),
        cached=False, replayed=False, opcode=0x50524602)
    calls = []
    class Channel:
        def __init__(self, socket, expected, timeout):
            assert socket == 'TEST ONLY' and expected['build'] == source
            self.boot = fresh.get('_test_boot', session['boot'])
        def call(self, op, **fields):
            calls.append((op, fields));assert op == 'native_fixture_status'
            assert fields == dict(boot=self.boot, epoch=session['fixture_epoch'] if self.boot == session['boot'] else 0)
            return fresh
        def fresh_identity(self): return None
        def close(self): calls.append(('close', {}))
    monkeypatch.setattr(admission, 'SettingsConnection', Channel)
    monkeypatch.setattr(admission, 'OWNER_LEASE_PATH', prism_native.OWNER_LEASE_PATH)
    return checkpoint, session, plist, fresh, calls, original


def validate(case, *, consume=False):
    checkpoint, session, plist, fresh, calls, original = case
    return admission.validate_repair_update(checkpoint, digest(checkpoint.read_bytes()), plist,
        'TEST ONLY', checkpoint.parent/'next-programme', consume=consume)


def test_native_update_requires_fresh_fixture_and_preserves_original_once(case):
    result = validate(case)
    assert result['old_source'] == 'b'*64 and result['boot'] == 7
    assert case[4][0][0] == 'native_fixture_status'
    assert not Path(str(case[0])+'.update-claim').exists()
    validate(case, consume=True)
    saved = case[0].parent/'next-programme.repair-original-settings.json'
    assert saved.read_bytes() == bound(case[5])
    with pytest.raises(admission.Refusal, match='already used'): validate(case)


@pytest.mark.parametrize('fault', ['cached','replayed','wrong_opcode','identity','boot','epoch','active',
    'act0','act1','act2','act3','image','settings','recovery','owner','sealed_probe','sealed_range'])
def test_native_update_rejects_before_any_programmer_entry(case, fault):
    checkpoint, session, plist, fresh, calls, original = case
    if fault in ('cached','replayed'): fresh[fault] = True
    elif fault == 'wrong_opcode': fresh['opcode'] = 0x50524601
    elif fault == 'identity': fresh['identity'] = dict(fresh['identity'], source_id='wrong')
    elif fault in ('boot','epoch','active') or fault.startswith('act'):
        raw = bytearray.fromhex(fresh['raw_hex'])
        word, value = {'boot':(1,8), 'epoch':(2,2), 'active':(3,4)}.get(fault,(72+int(fault[-1]) if fault in ('act0','act1','act2','act3') else 0,0x80))
        struct.pack_into('<I', raw, word*4, value);fresh['raw_hex'] = raw.hex()
    elif fault == 'image': Path(json.loads(bound(session['programming_event']))['image_file']['path']).write_bytes(b'changed')
    elif fault == 'settings': Path(original['path']).write_text('{}')
    elif fault == 'recovery': Path(session['recovery_image']['path']).write_bytes(b'changed')
    elif fault == 'owner': admission.OWNER_LEASE_PATH.unlink()
    else:
        sealed = json.loads(bound(session['sealed_writer_receipt']))
        if fault == 'sealed_probe': sealed['stdout'] = sealed['stdout'].replace('5AS079228B','WRONG')
        else: sealed['stdout'] = sealed['stdout'].replace('02000FFF','02000001')
        session['sealed_writer_receipt'] = bind(checkpoint.parent, 'bad-seal.json', sealed)
        event = json.loads(bound(session['programming_event']))
        event['sealed_writer_receipt'] = session['sealed_writer_receipt']
        session['programming_event'] = bind(checkpoint.parent, 'bad-event.json', event)
        checkpoint.write_text(json.dumps(session))
    with pytest.raises((admission.Refusal, RuntimeError)): validate(case)
    assert not Path(str(checkpoint)+'.update-claim').exists()


@pytest.mark.parametrize('fault', [None, 'missing', 'hash', 'different_original'])
def test_ael_keeps_exact_original_settings_across_native_candidates(case, fault):
    from ael import titan_isolated as isolated
    checkpoint, session, plist, fresh, calls, original = case
    logs = checkpoint.parent/'next-logs';logs.mkdir()
    captured = logs/'candidate-programme.repair-original-settings.json'
    captured.write_bytes(bound(original))
    stored_hash = logs/'candidate-programme.repair-original-settings.sha256'
    stored_hash.write_text(digest(captured.read_bytes()))
    if fault == 'missing': captured.unlink()
    elif fault == 'hash': stored_hash.write_text('0'*64)
    elif fault == 'different_original':
        captured.write_text('{"different":"settings"}')
        stored_hash.write_text(digest(captured.read_bytes()))
    m = {'isolated_qualification':{'repair_checkpoint':{'path':str(checkpoint),
        'sha256':digest(checkpoint.read_bytes())}}}
    if fault:
        with pytest.raises(RuntimeError): isolated.original_programme_settings(logs, m)
    else:
        result = isolated.original_programme_settings(logs, m)
        assert bound(result) == bound(original)


@pytest.mark.parametrize('fault', [None, 'missing_session', 'wrong_target', 'wrong_hash', 'closed'])
def test_native_update_checkpoint_is_an_explicit_bound_request(case, fault):
    from ael import titan_isolated as isolated
    checkpoint = case[0]
    if fault == 'closed':
        body = json.loads(checkpoint.read_text());body['closed'] = True
        checkpoint.write_text(json.dumps(body))
    m = {'target':'titan-replacement','isolated_qualification':{
        'repair_session':isolated.REPAIR_SESSION, 'repair_checkpoint':dict(path=str(checkpoint),
        sha256=digest(checkpoint.read_bytes()))}}
    if fault == 'missing_session': m['isolated_qualification'].pop('repair_session')
    elif fault == 'wrong_target': m['target'] = 'titan-native'
    elif fault == 'wrong_hash': m['isolated_qualification']['repair_checkpoint']['sha256'] = '0'*64
    if fault:
        with pytest.raises(RuntimeError): isolated.completion_request(m)
    else: assert isolated.completion_request(m) is None


@pytest.mark.parametrize('fault', [None, 'state', 'epoch', 'count', 'dma', 'source', 'memory'])
def test_restarted_source_requires_fresh_unused_bootstrap(case, fault):
    from test_titan_replacement_observer import fixture, packed
    from ael import titan_loopback as loop
    checkpoint, session, plist, fresh, calls, original = case
    s, _, _ = fixture()
    s.update(boot=8, epoch=0, state=0, fault=0, recording=0,
        words_a=0, words_b=0, gpt7_gtpr=0xfffffffe, gpt12_gtpr=0xfffffffe)
    for name in loop.SPLIT_NAMES:
        s.update({'words_'+name:0,'remaining_'+name:7712,
            'destination_'+name:s['buffer_'+name]})
    if fault == 'state': s['state'] = 4
    elif fault == 'epoch': s['epoch'] = 1
    elif fault == 'count': s['words_a_rise'] = 1
    elif fault == 'dma': s['dmsts_a_rise'] = 0x80
    elif fault == 'source': s['source_a_rise'] = 0x40322754
    elif fault == 'memory': s['dma_mair0'] = 0xff
    fresh['_test_boot'] = 8
    fresh['raw_hex'] = packed(s).hex()
    if fault:
        with pytest.raises((admission.Refusal,RuntimeError)): validate(case)
    else:
        result = validate(case)
        assert result['boot'] == 8 and result['epoch'] == 0
        assert result['previous_boot'] == 7 and result['previous_epoch'] == 1
        assert result['boot_lineage'] == 'fresh-unused-bootstrap-same-sealed-source'
