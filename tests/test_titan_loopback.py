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
    lanes=[(tmp_path/f'lane-{lane}.u32le.bin').read_bytes() for lane in ('a','b')]
    verdict=loop.verify_epoch((tmp_path/'status.u32le.bin').read_bytes(),lanes,
                             (tmp_path/'sof.u32le.bin').read_bytes(),boot=9,epoch=1,pattern=119)
    assert verdict['raw_capture_consistent'] and not verdict['physical_qualification']
    assert [oracle(raw) for raw in lanes]==[diagnostic_payload(119,lane) for lane in (0,1)]
