"""Sequential attended pair in either saved order.

control_then_fault: never inject when the fresh control failed; the control is
matched before injection (run-attended --control-run-id).
fault_then_control: the fault runs first with --defer-control-match; the
control follows, then scripts/evaluate-pair.py applies the same matching rules
and only then is the incident record generated. A failed fault run stops the
pair before the control is collected.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from telemetry_export import save_json, exclusive_export
from view_integrity import safe_name

ROOT = Path(__file__).resolve().parents[1]
ORDERS = ("control_then_fault", "fault_then_control")


def profile_order(path):
    return json.loads(Path(path).read_text(encoding="utf-8")).get("pair_order")


def plan(args):
    """Return the ordered (label, argv) steps of one pair."""
    attended = [sys.executable, '-B', str(ROOT / 'scripts/run-attended.py')]
    common = ['--k6-bin', args.k6_bin, '--policy-version', 'v3']
    control = ('run:' + args.control_id, attended + ['--run-id', args.control_id, '--profile', args.control_profile, *common])
    if args.pair_order == 'control_then_fault':
        fault = ('run:' + args.fault_id, attended + ['--run-id', args.fault_id, '--profile', args.fault_profile, *common,
                                                     '--control-run-id', args.control_id])
        return [control, fault]
    fault = ('run:' + args.fault_id, attended + ['--run-id', args.fault_id, '--profile', args.fault_profile, *common,
                                                 '--defer-control-match'])
    evaluate = ('evaluate-pair', [sys.executable, '-B', str(ROOT / 'scripts/evaluate-pair.py'), '--fault-id', args.fault_id,
                                  '--control-id', args.control_id, '--pair-order', args.pair_order])
    incident = ('incident-record', [sys.executable, '-B', str(ROOT / 'scripts/generate-incident-record.py'),
                                    '--run-id', args.fault_id, '--incident-id', 'inc-' + args.fault_id,
                                    '--experiment-id', 'exp-' + args.fault_id, '--control-run-id', args.control_id])
    return [fault, control, evaluate, incident]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--control-id', required=True); ap.add_argument('--fault-id', required=True)
    ap.add_argument('--control-profile', required=True); ap.add_argument('--fault-profile', required=True)
    ap.add_argument('--pair-order', choices=ORDERS, help='defaults to the pair_order saved in both profiles')
    ap.add_argument('--k6-bin', default='k6')
    ap.add_argument('--dry-run', action='store_true', help='print the planned commands and exit')
    args = ap.parse_args(argv)
    saved = {profile_order(args.control_profile), profile_order(args.fault_profile)}
    if args.pair_order is None:
        if len(saved) != 1 or None in saved:
            ap.error('profiles do not carry one shared pair_order; pass --pair-order')
        args.pair_order = saved.pop()
    elif saved - {None, args.pair_order}:
        ap.error('--pair-order conflicts with the pair_order saved in the profiles')
    steps = plan(args)
    if args.dry_run:
        print(json.dumps({'pair_order': args.pair_order, 'steps': [{'step': n, 'argv': c} for n, c in steps]}, indent=2))
        return 0
    for name in (args.control_id, args.fault_id):
        safe_name(name)
        if (ROOT / 'runs' / name).exists(): raise ValueError('Refusing existing run: ' + name)
    audit = ROOT / 'audits' / ('pair-' + args.fault_id)
    audit.mkdir(parents=True, exist_ok=False)
    state = {'complete': False, 'control_id': args.control_id, 'fault_id': args.fault_id,
             'pair_order': args.pair_order, 'steps': {}}
    with exclusive_export(ROOT / 'runs' / '.matched-pair-lock'):
        for name, command in steps:
            state['phase'] = name; state['updated_at'] = datetime.now(timezone.utc).isoformat()
            save_json(audit / 'status.json', state)
            with (audit / (name.replace(':', '-') + '.log')).open('w', encoding='utf8') as log:
                rc = subprocess.run(command, cwd=ROOT, stdout=log, stderr=log).returncode
            state['steps'][name] = rc
            if rc:
                state['phase'] = 'failed'; state['failed_step'] = name
                save_json(audit / 'status.json', state); return 1
        state['phase'] = 'finished'; state['complete'] = True
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        save_json(audit / 'status.json', state)
    return 0


if __name__ == '__main__': raise SystemExit(main())
