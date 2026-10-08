"""Titan evaluation-drive trial: paces per-hop drive records from the actual
audio-device playback clock (tools/media_clock_player) and streams them to the
native experimental capability titan.evaluation-drive.v1-experimental.

Development bench trial only. No reset, no retry, no owner takeover; the caller
holds AEL's hardware lock and has validated sole ownership of the CDC port.
"""
import json
import math
import struct
import subprocess
import threading
import time
from pathlib import Path

HOP, RATE = 64, 12800
PLAYER = Path(__file__).resolve().parents[1] / 'tools/media_clock_player/media_clock_player'


def uptime_ns():
    return time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)


class MediaClock:
    """Speaker-position estimate from the player's render reports.

    sample(T) = render_sample + (T - render_uptime_ns)*file_rate/1e9 - (latency_s + extra_s)*file_rate
    `extra_s` is a separately measured acoustic/route offset; it is never guessed.
    """

    def __init__(self, file_rate, extra_s=0.0):
        self.file_rate = float(file_rate); self.extra_s = float(extra_s)
        self.anchor = None; self.lock = threading.Lock(); self.reports = 0

    def update(self, row):
        if row.get('event') != 'clock' or row['render_sample'] < 0:
            return
        with self.lock:
            self.anchor = (row['render_uptime_ns'], row['render_sample'], row['latency_s']); self.reports += 1

    def speaker_sample(self, now_ns):
        with self.lock:
            if self.anchor is None:
                return None
            t, s, lat = self.anchor
        return s + (now_ns - t) * self.file_rate / 1e9 - (lat + self.extra_s) * self.file_rate


def due_hops(speaker_sample, file_rate, sent, total):
    """Hops whose 64-sample window (at 12800 Hz) has fully left the speaker: [sent, due)."""
    if speaker_sample is None or speaker_sample < 0:
        return range(sent, sent)
    completed = int(math.floor(speaker_sample * RATE / file_rate / HOP))
    return range(sent, min(max(sent, completed), total))


class Player:
    def __init__(self, wav, log_path, binary=PLAYER):
        self.proc = subprocess.Popen([str(binary), '--wav', str(wav)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.start = json.loads(self.proc.stdout.readline())
        if self.start.get('event') != 'start':
            raise RuntimeError('media clock player did not start')
        self.clock = MediaClock(self.start['file_rate']); self.done = False
        self.log = open(log_path, 'x'); self.log.write(json.dumps(self.start) + '\n')
        self.thread = threading.Thread(target=self._read, daemon=True); self.thread.start()

    def _read(self):
        for line in self.proc.stdout:
            row = json.loads(line); self.log.write(line)
            if row.get('event') == 'end':
                self.done = True
            self.clock.update(row)

    def close(self):
        self.proc.wait(timeout=30); self.thread.join(timeout=5); self.log.close()
        return self.proc.returncode
