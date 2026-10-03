"""Deterministic Emotiscope entry point using the native AEL runner."""
import argparse
import json
from pathlib import Path
from ael.adapter_registry import AdapterRegistry
from ael.pack_loader import load_pack
from ael.runner import run_plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--expect-git', help='Committed deployed revision; defaults to lane deployment record')
    p.add_argument('--port', default='/dev/tty.usbmodem12201')
    p.add_argument('--action', required=True, choices=('build', 'flash', 'observe', 'test'))
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--build-dir', type=Path, default=Path('_scratch/emotiscope-fresh-build'))
    p.add_argument('--seconds', type=int, default=60)
    p.add_argument('--resets', type=int, default=3)
    p.add_argument('--real-music-confirmed', action='store_true')
    a = p.parse_args()
    if not 10 <= a.seconds <= 1800 or not 1 <= a.resets <= 10:
        p.error('seconds must be 10..1800 and resets 1..10')
    if a.action == 'test' and not a.real_music_confirmed:
        p.error('test requires confirmed audible real music')
    if a.out.exists():
        p.error('out must be a new directory to preserve prior evidence')
    plan = load_pack(Path(__file__).resolve().parents[1] / 'packs/emotiscope_bench.json')
    cfg = dict(plan.pop('target'), source=str(a.source.resolve()), port=a.port, action=a.action,
               build_dir=str(a.build_dir.resolve()), seconds=a.seconds, resets=a.resets,
               real_music_confirmed=a.real_music_confirmed, expected_git=a.expect_git)
    kind = {'build': 'build', 'flash': 'load', 'observe': 'check', 'test': 'check'}[a.action]
    plan['steps'] = [{'name': 'emotiscope-' + a.action, 'type': kind + '.emotiscope',
                      'retry_budget': 0, 'inputs': cfg}]
    result = run_plan(plan, a.out, AdapterRegistry())
    (a.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Emotiscope:', 'PASS' if result['ok'] else 'FAIL', result.get('error_summary', ''))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
