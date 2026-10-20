"""Generated v5 raw pairs test the decoder; these are not device observations."""
import copy
import struct

import pytest
from ael import titan_replacement_observer as observer, titan_loopback as loop
from test_titan_replacement_observer import fixture as old_fixture, raw_streams, info, manifest


def fixture(pattern=13):
    s, streams, sof = old_fixture(pattern)
    s.update(version=5, split_capability=3, gtber=0x50000, gpt12_gtber=0x50000,
        dma_begin=0x22000000, dma_end=0x22080000, dma_rbar=0x22000000,
        dma_rlar=0x2207ffe1, dma_mair0=0x44,
        microphone_begin=0x22060000, microphone_end=0x22062000,
        led_begin=0x22064000, led_end=0x22066000,
        words_per_record=2, reserved_v5=0)
    for lane, prefix in (('a', ''), ('b', 'b_')):
        s[prefix+'leading_end'] = s[prefix+'stimulus_tick'] - 1
        s[prefix+'trailing_begin'] += 1
        s['prearm_counter_'+lane] = s[prefix+'leading_begin']
    pairs = []
    for index, name in enumerate(loop.SPLIT_NAMES):
        address = 0x22000000 + index * 0x10000
        s.update({'buffer_'+name:address, 'destination_'+name:address+7680*8,
            'dmamd_'+name:0x4080, 'dmofr_'+name:8,
            'dmcra_'+name:0x20002, 'dmcrb_'+name:32, 'dmtmd_'+name:0x9201,
            'seed_live_'+name:0xffffffff, 'seed_history_'+name:0xffffffff,
            'guard_'+name:1})
        previous = 0xffffffff
        row = []
        for tick in streams[index]:
            row.extend((tick, previous))
            previous = tick
        pairs.append(row)
    return s, pairs, sof, streams


def packed(s):
    words = ([s[k] for k in loop.STATUS_FIELDS]+[0]+[s[k] for k in loop.DIRECT_FIELDS]
        +[s[k] for k in observer.EXTENSION]+[0]+[s[k] for k in observer.V5_EXTENSION])
    assert len(words) == 192
    return struct.pack('<192I', *words)


def verify(s, pairs, sof):
    parsed = observer.status(packed(s), s['boot'], s['epoch'], layout=5)
    return observer.verify_epoch(parsed, raw_streams(pairs, sof), s['pattern'])


def test_full_pairs_and_raw_provenance():
    s, pairs, sof, streams = fixture()
    result = verify(s, pairs, sof)
    assert result['bits_each'] == 7680 and result['physical_qualification'] is False
    for index in range(4):
        assert [pairs[index][word] for word in result['canonical_raw_word_indices'][index]] == streams[index]


def test_late_live_read_recovers_only_the_timestamp_present_in_raw_history():
    s, pairs, sof, streams = fixture()
    index = 5122
    missing, later = streams[1][index:index+2]
    pairs[1][2*index:2*index+2] = [later, missing]
    result = verify(s, pairs, sof)
    assert result['canonical_raw_word_indices'][1][index] == 2*index+1
    assert missing not in pairs[1][::2]
    # No inferred timestamp may repair an actually absent observation.
    pairs[1] = [later if tick == missing else tick for tick in pairs[1]]
    with pytest.raises(RuntimeError, match='unique timestamp'):
        verify(s, pairs, sof)


@pytest.mark.parametrize('bad', ['two_overwrites', 'extra', 'wrong_width', 'seed_inside', 'outside', 'short'])
def test_genuine_raw_faults_fail(bad):
    s, pairs, sof, streams = fixture()
    if bad == 'two_overwrites':
        missing = set(streams[1][100:102])
        pairs[1] = [streams[1][102] if tick in missing else tick for tick in pairs[1]]
    elif bad == 'extra': pairs[0][201] = streams[0][100] + 1
    elif bad == 'wrong_width':
        old = streams[1][100]
        pairs[1] = [old+1 if tick == old else tick for tick in pairs[1]]
    elif bad == 'seed_inside': s['seed_history_a_rise'] = streams[0][0]
    elif bad == 'outside': pairs[0][1] = 0x70000000
    else: pairs[0].pop()
    with pytest.raises(RuntimeError): verify(s, pairs, sof)


@pytest.mark.parametrize('field,value', [
    ('dmofr_a_fall', 12), ('dmamd_a_rise', 0x80), ('dmtmd_a_rise', 0x2201),
    ('dmcra_a_rise', 0x20001), ('dmcrb_a_rise', 33), ('guard_b_fall', 0),
    ('destination_b_rise', 0x22020000+7680*4), ('buffer_b_rise', 0x22010000),
    ('dma_mair0', 0xff), ('dma_end', 0x22020000), ('gtber', 0),
    ('gpt12_gtber', 0), ('source_a_rise', 0x40322754),
    ('words_a_rise', 7679), ('edges_b', 15359), ('words_per_record', 1),
    ('split_capability', 2), ('reserved_v5', 1), ('cursor_a_rise', 15361)])
def test_configuration_corruption_fails(field, value):
    s, pairs, sof, _ = fixture()
    s[field] = value
    with pytest.raises(RuntimeError): verify(s, pairs, sof)


def test_wrap_uses_modular_order_and_still_refuses_a_hole():
    s, pairs, sof, streams = fixture()
    shift = (0xffffff9b - streams[0][0]) & 0xffffffff
    for prefix in ('', 'b_'):
        for field in ('capture_arm_tick', 'stimulus_tick', 'capture_end_tick', 'leading_begin',
                      'leading_end', 'trailing_begin', 'trailing_end'):
            s[prefix+field] = (s[prefix+field]+shift) & 0xffffffff
    for lane in ('a', 'b'): s['prearm_counter_'+lane] = (s['prearm_counter_'+lane]+shift) & 0xffffffff
    for index, name in enumerate(loop.SPLIT_NAMES):
        pairs[index] = [0x70000000 if tick == 0xffffffff else (tick+shift)&0xffffffff for tick in pairs[index]]
        s['seed_live_'+name] = s['seed_history_'+name] = 0x70000000
    result = verify(s, pairs, sof)
    assert result['bits_each'] == 7680
    missing = (streams[0][1] + shift) & 0xffffffff
    pairs[0] = [pairs[0][4] if tick == missing else tick for tick in pairs[0]]
    with pytest.raises(RuntimeError, match='unique timestamp'): verify(s, pairs, sof)


def test_wire_versions_require_the_selected_backend():
    s, pairs, sof, _ = fixture()
    with pytest.raises(RuntimeError): observer.status(packed(s), 7, 1, layout=4)
    i, m = info(), manifest()
    i['capabilities']['isolated_raw_capture'] = observer.PAIRED_BACKEND
    with pytest.raises(RuntimeError): observer.identity(i, m)
    m['isolated_qualification']['backend'] = observer.PAIRED_BACKEND
    assert observer.identity(i, m) == observer.PAIRED_BACKEND


class PairedDetector:
    def __init__(self):
        self.s, self.pairs, self.sof, _ = fixture()
        self.calls = []
        self.drained = False
    def exchange(self, opcode, payload=b'', *, absolute_deadline=None):
        import json
        self.calls.append(opcode)
        if opcode == observer.IDENTITY:
            identity = info()
            identity['capabilities']['isolated_raw_capture'] = observer.PAIRED_BACKEND
            return json.dumps(identity).encode()
        if opcode in (observer.CONTROL_STATUS, 0x50524202):
            return struct.pack('<4I', 1, 7, int(opcode == 0x50524202), 1) + loop.UID.encode() + bytes(64)
        if opcode == observer.HEALTH: return b'{"host_mock":true}'
        if opcode == loop.ARM:
            boot, epoch, pattern, exclusion = struct.unpack('<4I', payload)
            self.s, self.pairs, self.sof, _ = fixture(pattern)
            self.s['epoch'] = epoch
            self.drained = False
            return packed(self.s)
        if opcode == loop.STATUS:
            boot, epoch = struct.unpack('<2I', payload)
            s = copy.deepcopy(self.s)
            if epoch == 0:
                s.update(epoch=0, state=0, fault=0, words_a=0, words_b=0,
                    gpt7_gtpr=0xfffffffe, gpt12_gtpr=0xfffffffe)
                for name in loop.SPLIT_NAMES:
                    s.update({'words_'+name:0, 'remaining_'+name:7712,
                        'dmcrb_'+name:7712, 'destination_'+name:s['buffer_'+name]})
            if self.drained:
                for name in loop.SPLIT_NAMES: s['cursor_'+name] = 15360
                s['cursor_split_sof'] = len(self.sof)*4
            return packed(s)
        if opcode == loop.DRAIN:
            boot, epoch, stream, offset, count = struct.unpack('<5I', payload)
            words = (self.pairs+[sum(self.sof, [])])[stream][offset:offset+count]
            if stream == 4: self.drained = True
            return payload+struct.pack('<'+'I'*len(words), *words)
        if opcode == loop.CANCEL:
            s = copy.deepcopy(self.s)
            for name in loop.SPLIT_NAMES: s['cursor_'+name] = 15360
            s['cursor_split_sof'] = len(self.sof)*4
            return packed(s)
        raise AssertionError(hex(opcode))


def test_actual_collector_drains_raw_pairs_and_revalidates_v5_leave_proof(tmp_path):
    import time
    import json
    d = PairedDetector()
    i, m = info(), manifest()
    i['capabilities']['isolated_raw_capture'] = observer.PAIRED_BACKEND
    m['isolated_qualification']['backend'] = observer.PAIRED_BACKEND
    result = observer.acquire(d.exchange, m, dict(frames=100, pattern=13, budget_seconds=60),
        tmp_path, i, absolute_deadline=time.monotonic()+60)
    assert d.calls.count(loop.ARM) == 1 and d.calls[-1] == loop.CANCEL
    assert result['backend'] == observer.PAIRED_BACKEND
    assert all(__import__('pathlib').Path(r['path']).stat().st_size == 15360*4
        for r in result['epochs'][0]['streams'][:4])
    proof = observer.revalidate_leave_proof(result['leave_proof'])
    assert proof['boot'] == 7 and proof['terminal_epoch'] == 1
    assert proof['classification'] == 'complete'


def test_history_register_stuck_at_seed_is_not_a_paired_capture():
    s, pairs, sof, _ = fixture()
    pairs[1][1::2] = [s['seed_history_a_fall']] * 7680
    with pytest.raises(RuntimeError, match='history never captured'):
        verify(s, pairs, sof)
