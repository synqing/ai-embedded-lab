"""Machine entry point for PRISM lane checks, using the existing AEL runner."""
import argparse
import json
from pathlib import Path
from ael.adapter_registry import AdapterRegistry
from ael.pack_loader import load_pack
from ael.runner import run_plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lane', required=True, choices=('dualmcu', 'titan'))
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--core-source', type=Path)
    p.add_argument('--action', required=True, choices=('discover', 'core-test', 'donor-build', 'donor-recover', 'observe', 'bench-build', 'product-build', 'product-test', 'regression', 'diagnose', 'build', 'flash', 'recover', 'bench-trial-plan', 'bench-trial-qualify-isolated', 'bench-trial-flash', 'bench-trial-recover', 'bench-trial-observe', 'bench-trial-control'))
    p.add_argument('--target', choices=('rt1062_production', 'rt1062_k1_migration_t40_ws2812_128', 's3_radio_bridge_ble', 'prism_rt1062_t40_bench128_diag', 'prism_s3_ble_bench16_diag', 'titan-native', 'titan-replacement'))
    p.add_argument('--deployment-manifest', type=Path)
    p.add_argument('--native-request', type=Path, help='Explicit Titan atomic control/save request; not Dual injection')
    p.add_argument('--donor-source', type=Path)
    p.add_argument('--build-receipt', type=Path)
    p.add_argument('--owner-dir', type=Path, default=Path('/tmp/titan-emotiscope-control'))
    p.add_argument('--seconds', type=int, default=30)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    if a.out.exists(): p.error('out must be new to preserve evidence')
    if not 10 <= a.seconds <= 120: p.error('seconds must be 10..120')
    if a.action == 'core-test' and not a.core_source: p.error('core-test requires --core-source')
    if a.action == 'donor-build' and not a.donor_source: p.error('donor-build requires --donor-source')
    if a.action == 'donor-build' and a.lane == 'dualmcu' and not a.target: p.error('DualMCU donor build requires --target')
    if a.action == 'bench-build' and a.lane == 'dualmcu' and not a.target: p.error('DualMCU bench build requires --target')
    if a.action in ('observe', 'donor-recover') and a.lane == 'titan' and not (a.donor_source and a.build_receipt):
        p.error('Titan requires --donor-source and --build-receipt')
    if a.action.startswith('bench-trial-') and not (a.deployment_manifest and a.target):
        p.error('bench-trial requires --deployment-manifest and --target')
    plan = load_pack(Path(__file__).resolve().parents[1] / 'packs/prism_lanes.json')
    cfg = {k: str(v.resolve()) if isinstance(v, Path) else v for k, v in vars(a).items() if k != 'out'}
    plan['steps'] = [{'name': a.lane + '-' + a.action, 'type': 'check.prism_lane', 'retry_budget': 0, 'inputs': cfg}]
    result = run_plan(plan, a.out, AdapterRegistry())
    (a.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PRISM:', a.lane, a.action, 'PASS' if result['ok'] else 'FAIL', result.get('error_summary', ''))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
