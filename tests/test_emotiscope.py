"""Fault-focused tests for the Emotiscope bench boundary; no live serial opens."""
import io
import multiprocessing
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ael.adapters.emotiscope import identified_port, ownership, metrics, runtime, EmotiscopeAdapter, Link, native_status, boot_diagnostics, set_control
from ael.runner import RunContext, run_plan
from ael.adapter_registry import AdapterRegistry


def port(serial='DC:54:75:EA:36:14', vid=0x303A):
    return SimpleNamespace(device='/dev/cu.usbmodem12201', vid=vid, pid=0x1001, serial_number=serial)


class Replies:
    def __init__(self, git='b05cbd2c', crc='62851093'):
        self.git, self.crc = git, crc
    def command(self, cmd):
        if cmd == 'build':
            return [f'BUILD: version=40103 git={self.git} epoch=1790997451 env=k1_emotiscope_live']
        return [f'KLV image bytes=3351 crc={self.crc}', 'KLV vm=up origin=saved saved=1 err=0 px=128 frames=123',
                'KLV renderer=live mode=0', 'KLV heap free=18476 big=7156']


class EmotiscopeTests(unittest.TestCase):
    def test_usb_alias_and_identity(self):
        self.assertEqual(identified_port('/dev/tty.usbmodem12201', [port()]), '/dev/cu.usbmodem12201')
        for devices in ([], [port('wrong')], [port(vid=0x045b)], [port(), port()]):
            with self.assertRaises(RuntimeError): identified_port('/dev/tty.usbmodem12201', devices)

    def test_wrong_source_and_saved_crc_refuse(self):
        saved = {'bytes': 3351, 'crc': '62851093'}
        self.assertEqual(runtime(Replies(), 'b05cbd2c123', saved)['heap_free'], 18476)
        for reply in (Replies(git='deadbeef'), Replies(crc='ffffffff')):
            with self.assertRaises(RuntimeError): runtime(reply, 'b05cbd2c123', saved)

    def test_missing_status_refuses(self):
        with self.assertRaises(RuntimeError):
            runtime(SimpleNamespace(command=lambda _: []), 'b05cbd2c', {'bytes': 3351, 'crc': '62851093'})

    def test_metrics_missing_and_faults_refuse(self):
        with self.assertRaises(RuntimeError): metrics([])
        lines = ['KLV us=1900 fps=100 err=0 vu=0.5', 'KLVT show=100/200 frm=10000/12000', 'KLVA wt=10/20 act=5000/7000'] * 5
        self.assertEqual(metrics(lines)['fps_median'], 100)
        with self.assertRaises(RuntimeError): metrics([s.replace('err=0', 'err=1') for s in lines])

    def test_port_owner_refused(self):
        with tempfile.TemporaryDirectory() as d, patch('pathlib.Path.home', return_value=Path(d)), patch('subprocess.run', return_value=SimpleNamespace(returncode=0,stdout='123\n',stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'Serial port owned'):
                with ownership('/dev/tty.usbmodem12201'): self.fail('must not enter')

    def test_cross_process_lock(self):
        with tempfile.TemporaryDirectory() as d, patch('pathlib.Path.home', return_value=Path(d)), patch('subprocess.run', return_value=SimpleNamespace(returncode=1,stdout='',stderr='')):
            # fork creates an independent open file description in the child.
            ctx = multiprocessing.get_context('fork')
            parent, child = ctx.Pipe()
            def attempt():
                try:
                    with ownership('/dev/cu.usbmodem12201'): child.send('wrongly acquired')
                except RuntimeError as e: child.send(str(e))
            with ownership('/dev/tty.usbmodem12201'):
                proc = ctx.Process(target=attempt); proc.start()
                self.assertTrue(parent.poll(5)); self.assertIn('already owned', parent.recv())
                proc.join(5); self.assertFalse(proc.is_alive())

    def test_failure_evidence_no_retry(self):
        with tempfile.TemporaryDirectory() as d, patch('ael.adapters.emotiscope.source_identity', side_effect=RuntimeError('dirty')):
            plan = {'steps': [{'name':'guard','type':'load.emotiscope','retry_budget':5,'inputs':{'source':d,'action':'flash','usb_serial':'DC:54:75:EA:36:14','environment':'k1_emotiscope_live'}}]}
            result = run_plan(plan, Path(d), AdapterRegistry())
            self.assertFalse(result['ok']); self.assertEqual(len(result['steps']), 1)
            self.assertTrue((Path(d)/'artifacts/emotiscope-flash.json').exists())

    def test_missing_write_ack_reconciles_without_repeating_write(self):
        commands = []
        def cmd(value):
            commands.append(value)
            return [] if value.startswith('klv_set') else ['KLV value=mirror n=1']
        set_control(SimpleNamespace(command=cmd), 'mirror', 1)
        self.assertEqual(commands, ['klv_set=mirror,1', 'klv_get=mirror'])
        with self.assertRaisesRegex(RuntimeError, 'postcondition'):
            set_control(SimpleNamespace(command=lambda value: [] if value.startswith('klv_set') else ['KLV value=mirror n=0']), 'mirror', 1)
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            set_control(SimpleNamespace(command=lambda _: ['KLV err=value']), 'mirror', 1)

    def test_torn_status_retry_and_real_fault_not_retried(self):
        good = ['KLV native frames=12 avg=100 max=200 invalid=0', 'KLV native ap=8 pcm=96 history=1']
        replies = iter([['KLV native frameKLV native ap=8 pcm=96 history=1'], good])
        result = native_status(SimpleNamespace(command=lambda *_: next(replies)))
        self.assertEqual(len(result['attempts']), 2)
        calls = []
        def fault(*_):
            calls.append(1)
            return [x.replace('invalid=0', 'invalid=1') for x in good]
        with self.assertRaisesRegex(RuntimeError, 'invalid audio'):
            native_status(SimpleNamespace(command=fault))
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(RuntimeError, 'three'):
            native_status(SimpleNamespace(command=lambda *_: []))

    def test_boot_errors_are_retained_and_unknown_errors_fail(self):
        lines = ['ESP-ROM:esp32s3', 'E (198) quad_psram: PSRAM ID read error: 0x00ffffff, PSRAM chip not found or not supported, or wrong PSRAM line mode', '[    15][E][esp32-hal-psram.c:92] psramAddToHeap(): PSRAM not initialized!', '[    75][E][vfs_api.cpp:99] open(): /littlefs/SHOW_STATE_V1.BIN does not exist, no permits for creation', 'KLV boot=saved']
        result = boot_diagnostics(lines, '/dev/example', 'raw.log')
        self.assertFalse(result['ok'])  # Never disguise the upstream diagnostic FAIL.
        self.assertGreater(result['known_absent_psram_probe_errors'], 0)
        for changed in (lines+['E (3) DMA failure'], lines+['[    75][E][dma.cpp:9] missing descriptor'], lines+['ESP-ROM:esp32s3'], lines[:-1]):
            with self.assertRaises(RuntimeError): boot_diagnostics(changed, '/dev/example', 'raw.log')

    def test_fatal_serial_and_unexpected_reset(self):
        for data in (b'Guru Meditation\n', b'ESP-ROM:esp32s3\n', b'E (3) DMA failure\n', b'[    75][E][dma.cpp:9] missing descriptor\n'):
            link = object.__new__(Link)
            link.ser = SimpleNamespace(in_waiting=len(data),read=lambda _: data)
            link.raw=io.BytesIO();link.pending=b'';link.allow_boot=False
            with self.assertRaises(RuntimeError): link.read(.1)


if __name__ == '__main__': unittest.main()
