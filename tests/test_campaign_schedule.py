from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import evaluation_v2 as ev  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load('generate_campaign', 'generate-campaign.py')
pair = load('run_matched_pair', 'run-matched-pair.py')
PLAN = ROOT / 'campaigns/linux-v1/campaign-plan.yaml'
PARAMS = ROOT / 'campaigns/linux-v1/fault-params.yaml'


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.schedule_json, cls.csv = gen.render(PLAN, PARAMS, 20261016, 'workload/profiles/linux-v1', 5)
        cls.doc = json.loads(cls.schedule_json)
        cls.profiles = {Path(k).stem: json.loads(v) for k, v in cls.files.items()}

    def test_counts_and_unique_ids(self):
        pairs = self.doc['pairs']
        self.assertEqual(len(pairs), 69)
        self.assertEqual(len(self.profiles), 138)
        ids = [p['fault_run_id'] for p in pairs] + [p['control_run_id'] for p in pairs]
        self.assertEqual(len(set(ids)), 138)
        self.assertEqual(len({p['pair_id'] for p in pairs}), 69)
        self.assertEqual(Counter(p['fault_type'] for p in pairs),
                         {'cpu_saturation': 15, 'pod_failure': 15, 'network_delay': 15, 'packet_loss': 15, 'traffic_surge': 9})
        for p in pairs:
            self.assertLessEqual(len(p['fault_run_id'] + '-fault'), 63)

    def test_pair_order_balance(self):
        totals = Counter(p['pair_order'] for p in self.doc['pairs'])
        self.assertEqual(sorted(totals.values()), [34, 35])
        cells = {}
        for p in self.doc['pairs']:
            cells.setdefault((p['fault_type'], p['target_id']), []).append(p['pair_order'])
        self.assertEqual(len(cells), 23)
        for orders in cells.values():
            self.assertEqual(len(orders), 3)
            self.assertIn(orders.count('control_then_fault'), (1, 2))

    def test_onsets_and_phase_sums(self):
        counts = Counter()
        for p in self.doc['pairs']:
            counts[p['onset_offset_seconds']] += 1
            for run_id in (p['fault_run_id'], p['control_run_id']):
                prof = self.profiles[run_id]
                total = sum(prof[k] for k in ('warmup_seconds', 'baseline_seconds', 'fault_seconds', 'recovery_seconds', 'cooldown_seconds'))
                self.assertEqual(total, 1500)
                self.assertEqual(ev.seconds(prof['duration']), 1500)
                self.assertEqual(prof['warmup_seconds'] + prof['baseline_seconds'], p['onset_offset_seconds'])
                self.assertIn(p['onset_offset_seconds'], range(420, 721, 60))
                self.assertGreaterEqual(prof['baseline_seconds'], 240)
                self.assertGreaterEqual(prof['recovery_seconds'], 360)
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        cells = {}
        for p in self.doc['pairs']:
            cells.setdefault((p['fault_type'], p['target_id']), set()).add(p['onset_offset_seconds'])
        self.assertTrue(all(len(v) == 3 for v in cells.values()))

    def test_control_matches_fault_profile(self):
        for p in self.doc['pairs']:
            f, c = self.profiles[p['fault_run_id']], self.profiles[p['control_run_id']]
            self.assertNotIn('fault', c)
            for k in gen.MATCH_KEYS + ('pair_id', 'pair_order', 'workload_seed', 'onset_offset_seconds', 'repetition'):
                self.assertEqual(f[k], c[k], k)
            expected = f.get('control_phase_rps', f['traffic_phase_rps'])
            self.assertEqual(c['traffic_phase_rps'], expected)

    def test_match_control_accepts_generated_pair(self):
        p = next(p for p in self.doc['pairs'] if p['fault_type'] == 'traffic_surge')
        f, c = self.profiles[p['fault_run_id']], self.profiles[p['control_run_id']]
        start = datetime(2026, 10, 16, tzinfo=timezone.utc)
        assessment = {'valid': True, 'errors': [], 'profile': c, 'fingerprint': 'fp',
                      'started_at': start.isoformat(), 'ended_at': (start + timedelta(minutes=25)).isoformat()}
        with patch.object(ev, 'assess_run', return_value=assessment):
            self.assertTrue(ev.match_control('x', f, 'fp', start + timedelta(minutes=30))['valid'])

    def test_edge_faults_name_both_endpoints(self):
        for p in self.doc['pairs']:
            fault = self.profiles[p['fault_run_id']]['fault']
            if p['target_kind'] == 'dependency_edge':
                self.assertTrue(fault['source_service'] and fault['destination_service'])
                self.assertNotEqual(fault['source_service'], fault['destination_service'])
                self.assertIn(fault['type'], ('network_delay', 'packet_loss'))

    def test_repetitions_interleaved_over_time(self):
        pairs = sorted(self.doc['pairs'], key=lambda p: p['schedule_index'])
        n = len(pairs)
        for i in range(3):
            part = pairs[i * n // 3:(i + 1) * n // 3]
            reps = Counter(p['repetition'] for p in part)
            self.assertTrue(all(reps[r] >= 5 for r in (1, 2, 3)), reps)
        for a, b in zip(pairs, pairs[1:]):
            self.assertNotEqual((a['fault_type'], a['target_id']), (b['fault_type'], b['target_id']))

    def test_seed_reproducible_and_sensitive(self):
        again = gen.render(PLAN, PARAMS, 20261016, 'workload/profiles/linux-v1', 5)
        self.assertEqual(again[1], self.schedule_json)
        self.assertEqual(again[0], self.files)
        other = gen.render(PLAN, PARAMS, 7, 'workload/profiles/linux-v1', 5)
        self.assertNotEqual(json.loads(other[1])['pairs'], self.doc['pairs'])

    def test_draft_and_missing_capacity(self):
        # a --capacity-tps override always makes a draft, even from frozen params
        self.assertTrue(self.doc['draft'])
        self.assertTrue(all(p['calibration_status'] == 'draft' for p in self.profiles.values()))
        import yaml
        params = {**yaml.safe_load(PARAMS.read_text()), 'status': 'draft', 'capacity_tps': None}
        with self.assertRaises(ValueError):
            gen.build(yaml.safe_load(PLAN.read_text()), params, 1, None)


class FrozenParamsTests(unittest.TestCase):
    """campaigns/linux-v1/fault-params.yaml as approved 2026-10-22/23 (SETUP-REVIEW 7.18)."""

    @classmethod
    def setUpClass(cls):
        import yaml
        cls.params = yaml.safe_load(PARAMS.read_text())

    def test_frozen_values(self):
        p = self.params
        self.assertEqual((p['status'], p['capacity_tps'], p['load_fractions']['baseline']), ('frozen', 6, 0.4))
        self.assertTrue(p['frozen_at'])
        self.assertEqual(p['load_fractions']['surge_levels'], {'l1': 0.8, 'l2': 1.0, 'l3': 1.3333})
        f = p['faults']
        self.assertEqual(f['cpu_saturation']['params'], {'WORKERS': 4, 'LOAD': 100})
        self.assertEqual(f['network_delay']['params'], {'LATENCY': '100ms', 'JITTER': '10ms'})
        self.assertEqual(f['packet_loss']['params'], {'LOSS_PERCENT': '2'})
        self.assertEqual(f['pod_failure']['params'], {})

    def test_template_fixed_values_match_templates(self):
        import yaml
        for ft in ('network_delay', 'packet_loss'):
            fp = self.params['faults'][ft]
            spec = yaml.safe_load((ROOT / fp['template']).read_text())['spec']
            block = spec['delay' if ft == 'network_delay' else 'loss']
            self.assertEqual(block['correlation'], fp['template_fixed']['correlation'], ft)
            self.assertEqual(block['correlation'], '0', ft)

    def test_evidence_runs_and_files_exist_locally(self):
        ev = self.params['calibration_evidence']
        self.assertEqual(set(ev), {'capacity', 'capability', 'cpu_saturation', 'pod_failure', 'network_delay',
                                   'packet_loss', 'traffic_surge'})
        self.assertIn('calib3-linux-v1-loss-front-product-r02', ev['packet_loss'])
        if (ROOT / 'runs' / 'calib3-linux-v1-loss-front-product-r02').exists():   # only on 206-40
            for key, items in ev.items():
                for item in (items.values() if isinstance(items, dict) else items):
                    path = ROOT / item if '/' in item else ROOT / 'runs' / item
                    self.assertTrue(path.exists(), item)

    def test_frozen_render_is_not_draft(self):
        import yaml
        profiles, _, meta = gen.build(yaml.safe_load(PLAN.read_text()), self.params, 1, None)
        self.assertFalse(meta['draft'])
        self.assertEqual(meta['baseline_tps'], 2.4)
        self.assertTrue(all(p['calibration_status'] == 'frozen' for p in profiles.values()))


class PinnedImageTests(unittest.TestCase):
    def test_mutable_tags_pinned_to_digests(self):
        k = (ROOT / 'deploy/linux/online-boutique/kustomization.yaml').read_text()
        self.assertIn('newTag: alpine@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0', k)
        import yaml
        loki = yaml.safe_load((ROOT / 'linux/values/loki-linux.yaml').read_text())
        self.assertRegex(loki['gateway']['image']['digest'], r'^sha256:[0-9a-f]{64}$')


class SurgeLevelTests(unittest.TestCase):
    def test_surge_levels_at_c6(self):
        """0.8C / 1.0C / 4/3 C (SETUP-REVIEW 7.15) -> 4.8 / 6 / 8 tx/s at C = 6."""
        import yaml
        profiles, _, meta = gen.build(yaml.safe_load(PLAN.read_text()), yaml.safe_load(PARAMS.read_text()), 1, 6)
        rates = {}
        for p in profiles.values():
            f = p.get('fault') or {}
            if f.get('type') == 'traffic_surge':
                rates.setdefault(f['load_level'], set()).add(p['traffic_phase_rps']['fault'])
                self.assertEqual(p['control_phase_rps']['fault'], 2.4)
                self.assertEqual({k: v for k, v in p['traffic_phase_rps'].items() if k != 'fault'},
                                 {k: 2.4 for k in ('warmup', 'baseline', 'recovery', 'cooldown')})
        self.assertEqual(rates, {'l1': {4.8}, 'l2': {6}, 'l3': {8}})
        self.assertEqual(meta['baseline_tps'], 2.4)


class PairOrderTests(unittest.TestCase):
    def args(self, order):
        return type('A', (), dict(control_id='c', fault_id='f', control_profile='cp', fault_profile='fp',
                                  k6_bin='k6', pair_order=order))()

    def test_control_first_matches_before_injection(self):
        steps = pair.plan(self.args('control_then_fault'))
        self.assertEqual([n for n, _ in steps], ['run:c', 'run:f'])
        self.assertIn('--control-run-id', steps[1][1])
        self.assertNotIn('--defer-control-match', steps[1][1])

    def test_fault_first_defers_but_still_matches(self):
        steps = pair.plan(self.args('fault_then_control'))
        self.assertEqual([n for n, _ in steps], ['run:f', 'run:c', 'evaluate-pair', 'incident-record'])
        self.assertIn('--defer-control-match', steps[0][1])
        self.assertIn('fault_then_control', steps[2][1])

    def test_fault_first_time_direction(self):
        start = datetime(2026, 10, 16, tzinfo=timezone.utc)
        profile = {'target_rps': 2, 'duration': '25m'}
        a = {'valid': True, 'errors': [], 'profile': profile, 'fingerprint': 'fp',
             'started_at': (start + timedelta(minutes=10)).isoformat(), 'ended_at': (start + timedelta(minutes=35)).isoformat()}
        with patch.object(ev, 'assess_run', return_value=a):
            ok = ev.match_control('x', profile, 'fp', start, pair_order='fault_then_control')
            self.assertTrue(ok['valid'], ok)
            late = ev.match_control('x', profile, 'fp', start - timedelta(hours=3), pair_order='fault_then_control')
            self.assertFalse(late['valid'])
            before = ev.match_control('x', profile, 'fp', start + timedelta(hours=1), pair_order='fault_then_control')
            self.assertFalse(before['valid'])
            self.assertFalse(ev.match_control('x', profile, 'other', start, pair_order='fault_then_control')['valid'])
            self.assertFalse(ev.match_control('x', profile, 'fp', start, pair_order='bogus')['valid'])


if __name__ == '__main__':
    unittest.main()
