"""Independent raw input-capture fixtures; none are physical observations."""
import copy
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

from ael import titan_loopback as loop
from ael.titan_waveform import diagnostic_payload


def fixture(pattern=0, epoch=1, boot=7):
    # Test oscillator is300MHz. These are generated test edges, explicitly
    # separate from the production parser and device register implementation.
    lanes = []
    begin = 38_400_000
    first = begin + 120_000
    for lane in (0,1):
        payload = diagnostic_payload(pattern,lane)
        edges = []
        for byte in payload:
            for mask in (128,64,32,16,8,4,2,1):
                rise = first + (len(edges)//2)*390
                edges += [rise, rise + (198 if byte & mask else 78)]
        lanes.append(edges)
    last = max(x[-1] for x in lanes)
    sof = [[(1000+i)%2048,1000+i*300000,1100+i*300000,(1000+i)%2048]
           for i in range(136)]
    status = dict.fromkeys(loop.STATUS_FIELDS,0)
    status.update(version=1,boot=boot,epoch=epoch,state=6,pattern=pattern,capacity=7744,
                  sof_rows=len(sof),words_a=7680,words_b=7680,edges_a=7680,edges_b=7680,
                  remaining_a=64,remaining_b=64,capture_arm_tick=begin,stimulus_tick=first,
                  capture_end_tick=last+120001,leading_begin=begin,leading_end=first,
                  trailing_begin=last,trailing_end=last+120000,initial_low=3,final_low=3,
                  nominal_gpt_hz=300000000,gticasr=0xf00,gticbsr=0xf000,
                  nominal_pclkd_hz=250000000,gpt7_gtcr=1,gpt2_gtcr=1,gpt3_gtcr=1,
                  dmtmd_a=0x2201,dmtmd_b=0x2201,configuration_low=3,recording=1,gpt7_gtst=0x8003,
                  gpt2_gtst=0x8000,gpt3_gtst=0x8000,gptckcr=6,gptckdivcr=1,
                  gpt2_gtupsr=1<<20,gpt3_gtupsr=1<<21,elc_e=0x1c0,elc_f=0x1c1,
                  event_a=0x1c0,event_b=0x1c1,first_frmnum=(sof[0][3]-1)%2048,last_frmnum=sof[-1][3],
                  usb_valid=1,required_sof_rows=128,calibration_timeout_us=500000,
                  fixture_timeout_us=20000)
    return status,lanes,sof


def packed(s,lanes,sof):
    pack = lambda values: struct.pack('<'+'I'*len(values),*values)
    return (pack([s[k] for k in loop.STATUS_FIELDS]+[0]),
            [pack(x) for x in lanes],pack([x for row in sof for x in row]))


def check(s, lanes, sof, allowance=16):
    a,b,c=packed(s,lanes,sof)
    return loop.verify_epoch(a,b,c,boot=7,epoch=s['epoch'],pattern=s['pattern'],
                             endpoint_allowance_ns=allowance)


def oracle(raw):
    # Independent byte and pair scanner. No struct.unpack or parser helper.
    values=[sum(raw[i+j] << (8*j) for j in range(4)) for i in range(0,len(raw),4)]
    bits=['1' if values[i+1]-values[i]>130 else '0' for i in range(0,len(values),2)]
    return bytes(int(''.join(bits[i:i+8]),2) for i in range(0,len(bits),8))


def test_one_hundred_distinct_segments_two_lanes_and_order_oracle():
    for pattern in range(100):
        s,lanes,sof=fixture(pattern,pattern+1)
        result=check(s,lanes,sof)
        assert result['bits_each']==3840 and result['raw_capture_consistent']
        assert result['measured_waveform_pass'] is False
        assert result['physical_qualification'] is False
        raw=packed(s,lanes,sof)[1]
        assert [oracle(x) for x in raw]==[diagnostic_payload(pattern,l) for l in (0,1)]


@pytest.mark.parametrize('field,value',[
    ('state',7),('fault',1),('first_fsp_error',1),('initial_low',1),('final_low',1),
    ('words_a',7679),('edges_b',7682),('remaining_a',63),('dmsts_b',1),
    ('gpt2_gtst',1),('gticasr',0),('gticbsr',0xf00),('event_a',0x1c1),
    ('elc_f',0x1c0),('gpt3_gtupsr',1<<20),('gtber',1),('usb_valid',0),
    ('required_sof_rows',2),('first_frmnum',1),('trailing_end',1),('leading_begin',38519999),
])
def test_status_faults_refuse(field,value):
    s,lanes,sof=fixture();s[field]=value
    with pytest.raises(RuntimeError):check(s,lanes,sof)


@pytest.mark.parametrize('fault',['missing','extra','reverse','duplicate','payload','high','low','period','late','early'])
def test_real_edge_array_faults(fault):
    s,lanes,sof=fixture()
    a=lanes[0]
    if fault=='missing':a.pop()
    if fault=='extra':a.append(a[-1]+1)
    if fault=='reverse':a.reverse()
    if fault=='duplicate':a[2]=a[1]
    if fault=='payload':a[1]=a[0]+198
    if fault=='high':a[1]=a[0]+20
    if fault=='low':a[2]=a[1]+100
    if fault=='period':a[2]=a[0]+360
    if fault=='late':a[-1]=s['capture_end_tick']+1
    if fault=='early':a[0]=s['leading_begin']
    with pytest.raises(RuntimeError):check(s,lanes,sof)


@pytest.mark.parametrize('fault',['skip','repeat','flags','reorder','wrap','wide','few','zero'])
def test_actual_sof_calibration_faults(fault):
    _,_,rows=fixture()
    if fault=='skip':rows[3][0]+=1;rows[3][3]+=1
    if fault=='repeat':rows[3][0]=rows[2][0];rows[3][3]=rows[2][3]
    if fault=='flags':rows[3][3]|=0x8000
    if fault=='reorder':rows[2],rows[3]=rows[3],rows[2]
    if fault=='wrap':rows[-1][1:3]=[1,2]
    if fault=='wide':rows[3][2]+=50000
    if fault=='few':rows=rows[:127]
    if fault=='zero':rows[3][2]=rows[3][1]
    with pytest.raises(RuntimeError):loop.calibrate(rows)


def test_calibration_does_not_assume_transmitter_nominal_and_scales_duration_uncertainty():
    _,_,rows=fixture()
    c=loop.calibrate(rows)
    assert c['frequency_hz'][0]<300000000<c['frequency_hz'][1]
    short=loop.interval_ns(390,c,16)
    long=loop.interval_ns(1500000,c,16)
    assert short[0]<1300<short[1] and long[0]<5000000<long[1]
    assert long[1]-long[0]>100*(short[1]-short[0])
    for row in rows:row[1]*=2;row[2]*=2
    c2=loop.calibrate(rows)
    assert c2['frequency_hz'][0]<600000000<c2['frequency_hz'][1]


@pytest.mark.parametrize('fault',['short','extra','boot','epoch','stream','offset','count'])
def test_raw_chunk_identity_boundaries(fault):
    head=[7,1,0,0,2];payload=struct.pack('<2I',123,456)
    if fault=='short':payload=payload[:-1]
    if fault=='extra':payload+=b'\0'
    if fault in ('boot','epoch','stream','offset','count'):
        head[('boot','epoch','stream','offset','count').index(fault)]+=1
    with pytest.raises(RuntimeError):loop.parse_chunk(struct.pack('<5I',*head)+payload,7,1,0,0,2)


def test_binary_parser_matches_independent_integer_reader():
    raw=struct.pack('<5I',0,1,0x12345678,0x80000000,0xffffffff)
    assert loop.parse_words(raw,5)==[sum(raw[i+j]<<(8*j) for j in range(4)) for i in range(0,len(raw),4)]


class Detector:
    def __init__(self,fault=False,cancel_fault=False):
        self.s,self.lanes,self.sof=fixture()
        self.s.update(epoch=0,state=0)
        self.fault=fault;self.cancel_fault=cancel_fault;self.calls=[];self.now=1000.
        self.info={'uid':loop.UID,'build_source_sha256':'b'*64,'boot_id':7,'schema_sha256':'c'*64,
                   'capabilities':{'isolated_raw_capture':loop.BACKEND}}
    def exchange(self,opcode,payload=b''):
        self.calls.append(opcode)
        if opcode==1:return json.dumps(self.info).encode()
        if opcode==loop.ARM:
            boot,epoch,pattern,excluded=struct.unpack('<4I',payload)
            assert boot==7 and excluded==1
            self.s,self.lanes,self.sof=fixture(pattern,epoch)
            if self.fault:
                self.s.update(state=7,fault=8,words_a=4,words_b=2,sof_rows=1)
                self.lanes=[self.lanes[0][:4],self.lanes[1][:2]];self.sof=self.sof[:1]
            self.now+=.2
            return b''
        if opcode==loop.STATUS:return packed(self.s,self.lanes,self.sof)[0]
        if opcode==loop.DRAIN:
            boot,epoch,stream,offset,count=struct.unpack('<5I',payload)
            data=self.lanes+[sum(self.sof,[])]
            self.s[('cursor_a','cursor_b','cursor_sof')[stream]]=offset+count
            return payload+struct.pack('<'+'I'*count,*data[stream][offset:offset+count])
        if opcode==loop.CANCEL:
            if self.cancel_fault:raise RuntimeError('cancel secondary error')
            return b''
        raise AssertionError(opcode)


@pytest.mark.parametrize('cancel_fault',[False,True])
def test_acquisition_retains_failed_raw_before_cancel(tmp_path,cancel_fault):
    detector=Detector(fault=True,cancel_fault=cancel_fault)
    with pytest.raises(RuntimeError,match='fault'):
        loop.acquire(detector.exchange,{'source_binding_hash':'b'*64},{'frames':100},tmp_path,detector.info)
    assert detector.calls==[loop.STATUS,loop.ARM,loop.STATUS,loop.DRAIN,loop.DRAIN,loop.DRAIN,loop.STATUS,loop.CANCEL]
    assert (tmp_path/'loopback/001-stream0.u32').stat().st_size==16
    assert (tmp_path/'loopback/001-stream1.u32').stat().st_size==8
    assert json.loads((tmp_path/'loopback/001-outcome.json').read_text())['result']['raw_capture_consistent'] is False
    assert (tmp_path/'loopback/failure.json').is_file()
    assert (tmp_path/'loopback/cancel-failure.json').exists() is cancel_fault


@pytest.mark.parametrize('malformed',[False,True])
def test_acquisition_retains_startup_transmitter_fault_before_arm(tmp_path,malformed):
    detector=Detector(fault=True)
    detector.info['capabilities']['transmitter_status_opcode']=0x50524c02
    raw=b'not-json' if malformed else json.dumps({
        'schema':'prism.titan.transmitter.v2','first_fault':1,
        'first_falls':[0,0],'first_remaining':[3837,3837]}).encode()
    def exchange(opcode,payload=b''):
        if opcode==0x50524c02:
            detector.calls.append(opcode)
            assert payload==struct.pack('<I',7)
            return raw
        return detector.exchange(opcode,payload)
    with pytest.raises((RuntimeError,json.JSONDecodeError)):
        loop.acquire(exchange,{'source_binding_hash':'b'*64},{'frames':100},tmp_path,detector.info)
    assert detector.calls[:2]==[loop.STATUS,0x50524c02]
    assert (loop.ARM not in detector.calls) is malformed
    assert (tmp_path/'loopback/initial-transmitter-status.json').read_bytes()==raw
    assert (tmp_path/'loopback/failure.json').exists()
    if not malformed:
        assert detector.calls.count(0x50524c02)==2 and detector.calls.count(loop.ARM)==1
        assert (tmp_path/'loopback/001-failed-transmitter-status.json').read_bytes()==raw
        assert json.loads((tmp_path/'loopback/001-failed-info.json').read_text())['boot_id']==7


def test_actual_acquisition_command_path_drains100_epochs_and_reconsumes_raw(tmp_path,monkeypatch):
    from test_titan_isolated import rfp_log
    detector=Detector()
    monkeypatch.setattr(loop.time,'time',lambda:detector.now)
    image=tmp_path/'candidate.hex';image.write_text(':020000040200F8\n:0100000001FE\n:00000001FF\n')
    image_row={'path':str(image),'sha256':loop.digest(image.read_bytes())}
    log=tmp_path/'rfp.log';log.write_bytes(rfp_log(image))
    program={'identity':loop.UID,'image_sha256':image_row['sha256'],'readback_sha256':image_row['sha256'],'readback_verified':True,
             'source_binding_hash':'b'*64,'completed_unix':999.,'returncode':0,'argv':['rfp','-run','-pv',str(image)],
             'image_file':image_row,'programmer_log':{'path':str(log),'sha256':loop.digest(log.read_bytes())}}
    event=tmp_path/'program.json';event.write_text(json.dumps(program))
    manifest={'source_binding_hash':'b'*64,'source_commit':'d'*40,'image':image_row,
              'build_receipt':{'sha256':'e'*64},'isolated_fixture_id':'SYNTHETIC-NOT-PHYSICAL',
              'isolated_programming_event':{'path':str(event),'sha256':loop.digest(event.read_bytes())},
              'isolated_qualification':{'physical_confirmation':{},'bootstrap_authority':{}}}
    result=loop.acquire(detector.exchange,manifest,{'frames':100},tmp_path,detector.info,
                        clock=lambda:detector.now,sleep=lambda x:None)
    assert detector.calls.count(loop.ARM)==100 and detector.calls.count(loop.CANCEL)==1
    assert result['frames_each']==100 and result['physical_qualification'] is False
    reread=json.loads((tmp_path/'loopback/acquisition.json').read_text())
    verdict=loop.verify_acquisition(reread,manifest)
    assert verdict['raw_capture_consistent'] and not verdict['measured_waveform_pass']
    assert verdict['timing_qualification']=='UNQUALIFIED_PIN_TO_CAPTURE_ERROR'
    # Replacing a saved verdict/origin with an assertion cannot create proof.
    from ael.titan_capture import consume_output_proof
    forged=copy.deepcopy(reread)
    forged.update(origin='physical-acquisition',physical_qualification=True)
    forged['epochs'][0]['result']={'physical_qualification':True,'measured_waveform_pass':True}
    f=tmp_path/'forged-summary.json';f.write_text(json.dumps(forged))
    proof={'schema':'prism.titan.output-qualification.v2',
           'capture_manifest':{'path':str(f),'sha256':loop.digest(f.read_bytes())}}
    with pytest.raises(RuntimeError,match='UNQUALIFIED_INPUT_CAPTURE_TIMING'):
        consume_output_proof(manifest,proof)
    reread['epochs'][1],reread['epochs'][2]=reread['epochs'][2],reread['epochs'][1]
    with pytest.raises(RuntimeError):loop.verify_acquisition(reread,manifest)


def test_actual_native_session_encoder_to_independent_host_parser(tmp_path):
    root=Path('/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan')
    source=root/'tests/fixture_capture_test.cpp'
    binary=tmp_path/'native-fixture-model'
    subprocess.run(['clang++','-std=c++17','-O1','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-I'+str(root),str(source),'-o',str(binary)],
                   check=True,capture_output=True)
    subprocess.run([str(binary)],check=True,capture_output=True,
                   env={**os.environ,'PRISM_FIXTURE_EXPORT':str(tmp_path)})
    lanes=[(tmp_path/f'{lane}.u32le.bin').read_bytes() for lane in ('a-rising','a-falling','b-rising','b-falling')]
    assert struct.unpack_from('<I',(tmp_path/'status.u32le.bin').read_bytes())[0]==3
    verdict=loop.verify_epoch((tmp_path/'status.u32le.bin').read_bytes(),lanes,
                             (tmp_path/'sof.u32le.bin').read_bytes(),boot=9,epoch=1,pattern=119)
    assert verdict['raw_capture_consistent'] and not verdict['physical_qualification']
    merged=[b''.join(rise[i:i+4]+fall[i:i+4] for i in range(0,len(rise),4)) for rise,fall in (lanes[:2],lanes[2:])]
    assert [oracle(raw) for raw in merged]==[diagnostic_payload(119,lane) for lane in (0,1)]


def test_constant_diagnostic_uses_distinct_opcode_and_cannot_pass_campaign(tmp_path):
    detector=Detector(fault=True)
    def exchange(opcode,payload=b''):
        if opcode==0x50524605:
            assert struct.unpack('<4I',payload)==(7,1,1,1)
            return detector.exchange(loop.ARM,struct.pack('<4I',7,1,0,1))
        return detector.exchange(opcode,payload)
    with pytest.raises(RuntimeError,match='not a pattern qualification'):
        loop.acquire(exchange,{'source_binding_hash':'b'*64},
                     {'frames':100,'constant_timer_diagnostic':1},tmp_path,detector.info)
    assert detector.calls.count(loop.ARM)==1
    assert (tmp_path/'loopback/001-stream0.u32').stat().st_size==16
    assert json.loads((tmp_path/'loopback/constant-diagnostic.json').read_text())['expected_edges_each']==256


def split_fixture(pattern=2,pulses=3840):
    s,lanes,sof=fixture(pattern)
    streams=[lane[polarity::2][:pulses] for lane in lanes for polarity in (0,1)]
    s.update(dict.fromkeys(loop.SPLIT_FIELDS,0))
    s.update(version=2,capacity=3872,words_a=2*pulses,words_b=2*pulses,
             edges_a=2*pulses,edges_b=2*pulses,remaining_a=2*(3872-pulses),remaining_b=2*(3872-pulses),
             gticasr=0xc00,gticbsr=0xc000,gpt4_gticasr=1<<20,gpt4_gticbsr=1<<21,
             gpt4_gtcr=1,gpt4_gtst=0x8003,gpt2_gtupsr=(1<<20)|(1<<22),
             gpt3_gtupsr=(1<<21)|(1<<23),elc_e=0x1c,elc_f=0x1d,elc_g=0x1c0,elc_h=0x1c1,
             irq27_cr=1,irq28_cr=1,p603_pfs=0x03014000,p602_pfs=0x03014000,
             split_capability=1,start_mask=0x90)
    for index,(name,event) in enumerate(zip(loop.SPLIT_NAMES,(0x1a5,0x1c0,0x1a6,0x1c1))):
        s.update({"words_"+name:pulses,"remaining_"+name:3872-pulses,"dmtmd_"+name:0x2201,
                  "event_"+name:event,"source_"+name:(0x4032244c,0x4032274c,0x40322450,0x40322750)[index],
                  "expected_source_"+name:(0x4032244c,0x4032274c,0x40322450,0x40322750)[index],"buffer_"+name:0x22000000+index*16000,
                  "destination_"+name:0x22000000+index*16000+pulses*4})
    return s,streams,sof


def split_packed(s,streams,sof):
    pack=lambda words:struct.pack('<'+'I'*len(words),*words)
    return (pack([s[k] for k in loop.STATUS_FIELDS]+[0]+[s[k] for k in loop.SPLIT_FIELDS]),
            [pack(x) for x in streams],pack(sum(sof,[])))


def split_check(s,streams,sof):
    raw,lanes,clock=split_packed(s,streams,sof)
    return loop.verify_epoch(raw,lanes,clock,boot=7,epoch=1,pattern=s['pattern'])


def test_split_four_streams_preserve_order_and_270_tick_falling_transition():
    s,streams,sof=split_fixture()
    assert min(b-a for a,b in zip(streams[1],streams[1][1:]))==270
    result=split_check(s,streams,sof)
    assert result['raw_capture_consistent'] and not result['physical_qualification']
    # Second byte reader is independent of parse_words and emitted order is retained.
    raw=split_packed(s,streams,sof)[1]
    decoded=[]
    for lane in (0,1):
        rise=[int.from_bytes(raw[lane*2][i:i+4],'little') for i in range(0,len(raw[lane*2]),4)]
        fall=[int.from_bytes(raw[lane*2+1][i:i+4],'little') for i in range(0,len(raw[lane*2+1]),4)]
        bits=['1' if f-r>138 else '0' for r,f in zip(rise,fall)]
        decoded.append(bytes(int(''.join(bits[i:i+8]),2) for i in range(0,len(bits),8)))
    assert decoded==[diagnostic_payload(2,lane) for lane in (0,1)]


@pytest.mark.parametrize('fault',['duplicate','wrap','missing','extra','swap','last','first','period','payload'])
def test_split_first_error_is_reported_without_repair(fault):
    s,streams,sof=split_fixture()
    if fault=='duplicate':streams[3][5]=streams[3][4]
    if fault=='wrap':streams[0][5]=0
    if fault=='missing':streams[1].pop()
    if fault=='extra':streams[1].append(streams[1][-1]+390)
    if fault=='swap':streams[0],streams[1]=streams[1],streams[0]
    if fault=='last':streams[1][-1]=s['trailing_begin']+1
    if fault=='first':streams[0][0]=s['leading_begin']
    if fault=='period':streams[0][6]+=1
    if fault=='payload':streams[1][0]=streams[0][0]+78
    with pytest.raises(RuntimeError):split_check(s,streams,sof)


@pytest.mark.parametrize('field,value',[
    ('words_b_fall',3839),('remaining_a_rise',31),('event_b_rise',0x1c1),
    ('source_a_fall',0),('destination_b_fall',0),('gpt4_initial',1),('start_mask',0),
    ('irq27_cr',0),('p602_pfs',0),('ccr',1<<16),('mpu',1),('gpt4_gticasr',0),
    ('gpt2_gtupsr',1<<20),('dmint_a_rise',1),('dmsts_b_rise',1),('split_capability',0)])
def test_split_actual_configuration_faults(field,value):
    s,streams,sof=split_fixture();s[field]=value
    with pytest.raises(RuntimeError):split_check(s,streams,sof)


def test_split_calibration_failure_does_not_become_timing_pass_or_destroy_raw_result():
    s,streams,sof=split_fixture()
    for row in sof:row[2]=row[1]+75000
    result=split_check(s,streams,sof)
    assert result['raw_capture_consistent']
    assert 'Unbounded USB observation bracket' in result['timing']['calibration_error']
    assert result['measured_waveform_pass'] is False


def test_microphone_progress_requires_both_channels_and_no_new_errors():
    before={'capture_errors':[0,0],'capture_restart_attempts':0,'capture_restart_failures':0,'capture_stale':False}
    tx={'microphone_dma':[{'callbacks':10,'threshold_register':1},{'callbacks':20,'threshold_register':1}]}
    after={'microphone_dma':[{'callbacks':11,'threshold_register':1},{'callbacks':21,'threshold_register':1}]}
    loop.verify_audio_progress(before,before,tx,after)
    for field in ('capture_errors','capture_restart_attempts','capture_restart_failures','capture_stale'):
        bad=copy.deepcopy(before);bad[field]=[0,1] if field=='capture_errors' else 1
        with pytest.raises(RuntimeError):loop.verify_audio_progress(before,bad,tx,after)
    with pytest.raises(RuntimeError):loop.verify_audio_progress(before,before,tx,tx)


class SplitDetector(Detector):
    make_fixture=staticmethod(split_fixture)
    pack_fixture=staticmethod(split_packed)
    def __init__(self,fault=False):
        super().__init__(fault=fault)
        self.s,self.lanes,self.sof=self.make_fixture()
        self.s.update(epoch=0,state=0)
        for name in loop.SPLIT_NAMES:
            self.s['words_'+name]=0;self.s['remaining_'+name]=3872
            self.s['destination_'+name]=self.s['buffer_'+name]
        self.info['capabilities'].update(isolated_raw_capture=loop.SPLIT_BACKEND,transmitter_status_opcode=0x50524c02)
        self.info.update(capture_errors=[0,0],capture_restart_attempts=0,capture_restart_failures=0,capture_stale=False)
        self.callbacks=10
    def exchange(self,opcode,payload=b''):
        self.calls.append(opcode)
        if opcode==1:return json.dumps(self.info).encode()
        if opcode==0x50524c02:
            self.callbacks+=1
            return json.dumps({'schema':'prism.titan.transmitter.v2','microphone_dma':[
                {'callbacks':self.callbacks,'threshold_register':1} for _ in (0,1)]}).encode()
        if opcode in (loop.ARM,0x50524605):
            boot,epoch,pattern,excluded=struct.unpack('<4I',payload)
            self.s,self.lanes,self.sof=self.make_fixture(pattern if opcode==loop.ARM else 0,
                                                  3840 if opcode==loop.ARM else 128)
            self.s['epoch']=epoch
            if self.fault:self.lanes[3][5]=self.lanes[3][4]
            self.now+=.2
            return b''
        if opcode==loop.STATUS:return self.pack_fixture(self.s,self.lanes,self.sof)[0]
        if opcode==loop.DRAIN:
            boot,epoch,stream,offset,count=struct.unpack('<5I',payload)
            data=self.lanes+[sum(self.sof,[])]
            key=(tuple('cursor_'+n for n in loop.SPLIT_NAMES)+('cursor_split_sof',))[stream]
            self.s[key]=offset+count
            return payload+struct.pack('<'+'I'*count,*data[stream][offset:offset+count])
        if opcode==loop.CANCEL:return b''
        raise AssertionError(opcode)


def split_manifest():
    return {'source_binding_hash':'b'*64,'source_commit':'d'*40,'image':{'sha256':'a'*64},
            'build_receipt':{'sha256':'e'*64},'isolated_fixture_id':'SYNTHETIC-NOT-PHYSICAL',
            'isolated_programming_event':{},'isolated_qualification':{'physical_confirmation':{},'bootstrap_authority':{}}}


@pytest.mark.parametrize('spec',[{'constant_timer_diagnostic':2},{'pattern':2}])
def test_split_collector_short_and_single_pattern_are_explicit_noncampaign(tmp_path,spec):
    detector=SplitDetector()
    result=loop.acquire(detector.exchange,split_manifest(),spec,tmp_path,detector.info)
    assert result['frames_each']==1 and result['scope']!='frozen-campaign'
    assert result['epochs'][0]['result']['raw_capture_consistent']
    assert len(result['epochs'][0]['streams'])==5
    assert result['audio_observations']['final-info.json']
    assert result['physical_qualification'] is False


def test_split_duplicate_preserves_all_streams_and_terminal_microphone_evidence(tmp_path):
    detector=SplitDetector(fault=True)
    with pytest.raises(RuntimeError,match='duplicate'):
        loop.acquire(detector.exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    for stream in range(4):assert (tmp_path/f'loopback/001-stream{stream}.u32').stat().st_size==3840*4
    assert (tmp_path/'loopback/001-terminal-info.json').exists()
    assert (tmp_path/'loopback/001-terminal-transmitter-status.json').exists()
    assert detector.calls.count(loop.ARM)==1


def test_split_counter_wrap_is_checked_relative_to_observed_frame_start():
    s,streams,sof=split_fixture()
    shift=0xffffffff-streams[0][100]
    for stream in streams:
        stream[:]=[(x+shift)&0xffffffff for x in stream]
    for field in ('leading_begin','leading_end','trailing_begin','trailing_end'):
        s[field]=(s[field]+shift)&0xffffffff
    assert split_check(s,streams,sof)['raw_capture_consistent']


def direct_fixture(pattern=2,pulses=3840):
    s,streams,sof=split_fixture(pattern,pulses)
    for old,new in zip(loop.SPLIT_FIELDS,loop.DIRECT_FIELDS):
        if old!=new:s[new]=s.pop(old)
    s.update(version=3,split_capability=2,gticasr=0x300,gticbsr=0xc00,
             gpt12_gticasr=0x3000,gpt12_gticbsr=0xc000,p603_pfs=0x03010000,p714_pfs=0x03010000,
             gpt7_gtpr=0xffffffff,gpt12_gtpr=0xffffffff,start_mask=0x1080,
             elc_e=0x1c0,elc_f=0x1c1,elc_g=0x1ed,elc_h=0x1ee,
             gpt2_gtupsr=0x300000,gpt3_gtupsr=0xc00000,b_initial_low=3,b_final_low=3)
    for name,event,source in zip(loop.SPLIT_NAMES,(0x1c0,0x1c1,0x1ed,0x1ee),
                                 (0x4032274c,0x40322750,0x40322c4c,0x40322c50)):
        s['event_'+name]=event;s['source_'+name]=source;s['expected_source_'+name]=source
    # Deliberately unrelated B origin: cross-lane timestamp comparisons are invalid.
    shift=0xfedcba98
    for field in ('capture_arm_tick','stimulus_tick','capture_end_tick','leading_begin','leading_end','trailing_begin','trailing_end'):
        s['b_'+field]=(s[field]+shift)&0xffffffff
    for stream in streams[2:]:stream[:]=[(x+shift)&0xffffffff for x in stream]
    for i in range(137,144):s[f'reserved_{i}']=0
    return s,streams,sof


def direct_packed(s,streams,sof):
    pack=lambda words:struct.pack('<'+'I'*len(words),*words)
    return (pack([s[k] for k in loop.STATUS_FIELDS]+[0]+[s[k] for k in loop.DIRECT_FIELDS]),
            [pack(x) for x in streams],pack(sum(sof,[])))


def direct_check(s,streams,sof):
    raw,lanes,clock=direct_packed(s,streams,sof)
    return loop.verify_epoch(raw,lanes,clock,boot=7,epoch=1,pattern=s['pattern'])


def test_direct_timers_decode_independently_with_wrap_and_exact_widths():
    s,streams,sof=direct_fixture()
    result=direct_check(s,streams,sof)
    assert result['raw_capture_consistent'] and not result['physical_qualification']
    assert result['payload_sha256']==[loop.digest(diagnostic_payload(2,lane)) for lane in (0,1)]
    assert result['observed_high_ticks']==[{'minimum':78,'maximum':198,'first':198,'last':78},
                                           {'minimum':78,'maximum':198,'first':78,'last':198}]


@pytest.mark.parametrize('field,value',[
    ('gpt7_gtpr',0xfffffffe),('gpt12_gtpr',0xfffffffe),('gpt12_gticasr',0x100000),
    ('gticbsr',0xf000),('p714_pfs',0x03014000),('event_b_fall',0x1c1),
    ('source_b_rise',0x4032244c),('expected_source_b_rise',0x4032244c),('start_mask',0x90),
    ('gpt3_gtupsr',0xa00000),('elc_h',0x1c1),('gpt12_initial',1),('b_initial_low',0),
    ('b_final_low',0),('b_trailing_begin',1),('reserved_143',1),('words_b_fall',3839),
    ('remaining_a_rise',1),('dmsts_b_rise',1),('dmint_a_fall',1),('fault',5),('state',7)])
def test_direct_rejects_config_lifecycle_and_partial_faults(field,value):
    s,streams,sof=direct_fixture();s[field]=value
    with pytest.raises(RuntimeError):direct_check(s,streams,sof)


@pytest.mark.parametrize('fault',['high_one_tick','period_one_tick','duplicate','missing','extra','swap'])
def test_direct_interval_contract_is_not_widened(fault):
    s,streams,sof=direct_fixture()
    if fault=='high_one_tick':streams[1][0]+=1
    if fault=='period_one_tick':streams[0][1]+=1
    if fault=='duplicate':streams[2][1]=streams[2][0]
    if fault=='missing':streams[3].pop()
    if fault=='extra':streams[1].append(streams[1][-1]+390)
    if fault=='swap':streams[0],streams[1]=streams[1],streams[0]
    with pytest.raises(RuntimeError):direct_check(s,streams,sof)


def test_direct_prearm_requires_fsp_open_modulus_and_resources():
    s,streams,sof=direct_fixture()
    s['gpt7_gtpr']=s['gpt12_gtpr']=0xfffffffe
    loop.verify_direct_configuration(s,readiness=True)
    s['gpt12_gtpr']=0xffffffff
    with pytest.raises(RuntimeError,match='modulus'):loop.verify_direct_configuration(s,readiness=True)


class DirectDetector(SplitDetector):
    make_fixture=staticmethod(direct_fixture)
    pack_fixture=staticmethod(direct_packed)
    def __init__(self,fault=False):
        super().__init__(fault=fault)
        self.info['capabilities']['isolated_raw_capture']=loop.DIRECT_BACKEND
        self.s['gpt7_gtpr']=self.s['gpt12_gtpr']=0xfffffffe


@pytest.mark.parametrize('spec',[{'constant_timer_diagnostic':2},{'pattern':2}])
def test_direct_collector_retains_independent_streams_and_audio(tmp_path,spec):
    detector=DirectDetector()
    result=loop.acquire(detector.exchange,split_manifest(),spec,tmp_path,detector.info)
    assert result['backend']==loop.DIRECT_BACKEND
    assert result['epochs'][0]['result']['raw_capture_consistent']
    assert len(result['epochs'][0]['streams'])==5
    assert result['physical_qualification'] is False


def test_direct_partial_native_failure_drains_all_raw_without_replay(tmp_path):
    detector=DirectDetector()
    base=detector.exchange
    def exchange(opcode,payload=b''):
        raw=base(opcode,payload)
        if opcode==loop.ARM:
            detector.s.update(state=7,fault=5)
            for i,(name,count) in enumerate(zip(loop.SPLIT_NAMES,(4,3,2,1))):
                detector.s['words_'+name]=count
                detector.lanes[i]=detector.lanes[i][:count]
        return raw
    with pytest.raises(RuntimeError,match='fault/cancel'):
        loop.acquire(exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    for i,count in enumerate((4,3,2,1)):
        assert (tmp_path/f'loopback/001-stream{i}.u32').stat().st_size==4*count
    assert (tmp_path/'loopback/001-terminal-info.json').exists()
    assert detector.calls.count(loop.ARM)==1 and detector.calls.count(loop.CANCEL)==1


def test_direct_readiness_failure_cannot_stimulate(tmp_path):
    detector=DirectDetector();detector.s['source_b_fall']=0x40322750
    with pytest.raises(RuntimeError,match='address mismatch'):
        loop.acquire(detector.exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    assert loop.ARM not in detector.calls and 0x50524605 not in detector.calls



@pytest.mark.parametrize('lane',[0,1])
def test_direct_otherwise_valid_frame_cannot_precede_its_own_stimulus(lane):
    s,streams,sof=direct_fixture()
    prefix='b_' if lane else ''
    s[prefix+'stimulus_tick']=(streams[2*lane][0]+1)&0xffffffff
    with pytest.raises(RuntimeError,match=f'Lane {lane} first edge precedes its stimulus'):
        direct_check(s,streams,sof)


def timing_words(epoch=1):
    # Independent protocol fixture, not a firmware-produced oracle.
    w=[0]*64
    w[:8]=[1,1,7,epoch,1_000_000_000,6,0,5]
    w[8:12]=[0xffffffff,2,10,3]
    w[12:20]=[400,1,800,1,100,200,3,4]
    w[20:35]=list(range(15))
    w[35:46]=[150,149,0,0,500,510,42,1,1,900,910]
    return w


@pytest.mark.parametrize('bad',['size','version','boot','epoch','extension'])
def test_timing_witness_rejects_unknown_or_stale(bad):
    w=timing_words()
    if bad=='size':w.pop()
    if bad=='version':w[0]=2
    if bad=='boot':w[2]=8
    if bad=='epoch':w[3]=2
    if bad=='extension':w[63]=1
    with pytest.raises(RuntimeError):loop.parse_timing_witness(struct.pack('<'+'I'*len(w),*w),7,1)


def test_timing_witness_units_and_64bit_fields():
    p=loop.parse_timing_witness(struct.pack('<64I',*timing_words()),7,1)
    assert p['window_us']==3*2**32-1 and p['terminal_now_us']==3*2**32+10
    assert p['stages']['usb']=={'max_cycles':3,'latest_begin_cycle':8,'latest_end_cycle':13}
    assert p['initial_freeze_gpt7_tick']==400 and p['queue']['consumed']==149


@pytest.mark.parametrize('fault',[False,True])
@pytest.mark.parametrize('witness_error',[None,'transport','parse'])
def test_timing_witness_retained_on_success_and_failure_without_changing_outcome(tmp_path,fault,witness_error):
    detector=DirectDetector(fault=fault)
    detector.info['capabilities']['fixture_timing_witness_opcode']=loop.TIMING_WITNESS
    base=detector.exchange
    def exchange(opcode,payload=b''):
        if opcode==loop.TIMING_WITNESS:
            detector.calls.append(opcode)
            assert payload==struct.pack('<I',7)
            if witness_error=='transport':raise TimeoutError('timing read timeout')
            return b'bad' if witness_error=='parse' else struct.pack('<64I',*timing_words())
        return base(opcode,payload)
    if fault:
        with pytest.raises(RuntimeError,match='duplicate'):
            loop.acquire(exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    else:
        result=loop.acquire(exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
        assert result['epochs'][0]['result']['raw_capture_consistent']
    assert detector.calls.count(loop.TIMING_WITNESS)==1
    assert detector.calls.index(loop.TIMING_WITNESS)<detector.calls.index(loop.DRAIN)
    assert detector.calls.count(loop.CANCEL)==1
    prefix=tmp_path/'loopback/001-timing-witness'
    assert prefix.with_suffix('.bin').exists() is (witness_error!='transport')
    assert prefix.with_suffix('.json').exists() is (witness_error is None)
    assert Path(str(prefix)+'-error.json').exists() is (witness_error is not None)


def test_timing_witness_partial_status_failure_saved_before_cancel(tmp_path):
    detector=DirectDetector()
    detector.info['capabilities']['fixture_timing_witness_opcode']=loop.TIMING_WITNESS
    base=detector.exchange
    def exchange(opcode,payload=b''):
        if opcode==loop.TIMING_WITNESS:
            detector.calls.append(opcode)
            return struct.pack('<64I',*timing_words())
        if opcode==loop.STATUS and detector.s['epoch']:
            raise RuntimeError('primary status failure')
        return base(opcode,payload)
    with pytest.raises(RuntimeError,match='primary status failure'):
        loop.acquire(exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    assert (tmp_path/'loopback/001-timing-witness.bin').exists()
    assert detector.calls[-1]==loop.CANCEL
    assert json.loads((tmp_path/'loopback/failure.json').read_text())['timing_witnesses']['1']['raw']


@pytest.mark.parametrize('count',[1,256,1000])
def test_negotiated_chunk_boundaries(count):
    raw=struct.pack('<5I',7,1,0,0,count)+struct.pack('<'+'I'*count,*range(count))
    assert loop.parse_chunk(raw,7,1,0,0,count,max_words=1000)==list(range(count))
    if count>256:
        with pytest.raises(RuntimeError):loop.parse_chunk(raw,7,1,0,0,count)
    with pytest.raises(RuntimeError):loop.parse_chunk(raw[:-1],7,1,0,0,count,max_words=1000)
    with pytest.raises(RuntimeError):loop.parse_chunk(raw,7,1,0,1,count,max_words=1000)


@pytest.mark.parametrize('value',[0,257,999,1001,True])
def test_unrecognised_drain_capability_cannot_stimulate(tmp_path,value):
    detector=DirectDetector();detector.info['capabilities']['fixture_drain_max_words']=value
    with pytest.raises(RuntimeError,match='capability'):
        loop.acquire(detector.exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    assert loop.ARM not in detector.calls


@pytest.mark.parametrize('capacity',[256,1000])
def test_negotiated_drain_retains_exact_full_streams_and_tail(tmp_path,capacity):
    detector=DirectDetector()
    if capacity==1000:detector.info['capabilities']['fixture_drain_max_words']=capacity
    base=detector.exchange;requests=[]
    def exchange(opcode,payload=b''):
        if opcode==loop.DRAIN:requests.append(struct.unpack('<5I',payload))
        return base(opcode,payload)
    result=loop.acquire(exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    assert result['epochs'][0]['result']['raw_capture_consistent']
    lane0=[r for r in requests if r[2]==0]
    assert [r[3] for r in lane0]==list(range(0,3840,capacity))
    assert [r[4] for r in lane0]==([1000,1000,1000,840] if capacity==1000 else [256]*15)
    for i in range(4):
        raw=(tmp_path/f'loopback/001-stream{i}.u32').read_bytes()
        assert raw==struct.pack('<3840I',*detector.lanes[i])


def test_large_drain_partial_reply_preserved_with_original_failure(tmp_path):
    detector=DirectDetector();detector.info['capabilities']['fixture_drain_max_words']=1000
    base=detector.exchange
    def exchange(opcode,payload=b''):
        raw=base(opcode,payload)
        if opcode==loop.DRAIN and struct.unpack('<5I',payload)[3]==1000:return raw[:-3]
        return raw
    with pytest.raises(RuntimeError,match='Truncated/oversized'):
        loop.acquire(exchange,split_manifest(),{'pattern':2},tmp_path,detector.info)
    assert (tmp_path/'loopback/001-stream0-00000.bin').stat().st_size==4020
    assert (tmp_path/'loopback/001-stream0-01000.bin').stat().st_size==4017
    assert detector.calls.count(loop.ARM)==1 and detector.calls.count(loop.CANCEL)==1
