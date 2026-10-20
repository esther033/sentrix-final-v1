"""Fault manifest rendering (method A edge filters, cpu params) and the
filter targets that run-attended.py records in fault-record.json."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import evaluation_v2 as ev  # noqa: E402
import fault_manifest as fm  # noqa: E402
from test_campaign_schedule import gen, load, PLAN, PARAMS  # noqa: E402

incident = load('generate_incident_record', 'generate-incident-record.py')
IPS = {'productcatalogservice': '10.43.82.246', 'currencyservice': '10.43.54.89', 'paymentservice': '10.43.165.9',
       'recommendationservice': '10.43.128.35'}


def generated_profiles():
    plan = yaml.safe_load(PLAN.read_text())
    params = yaml.safe_load(PARAMS.read_text())
    profiles, _, _ = gen.build(plan, params, 1, 6)
    return [p for p in profiles.values() if p.get('fault')]


class EdgeTemplateTests(unittest.TestCase):
    def edge_faults(self):
        return [p for p in generated_profiles() if p['fault']['type'] in ('network_delay', 'packet_loss')]

    def test_every_generated_edge_fault_filters_on_destination_clusterip(self):
        calls = []
        lookup = lambda svc: calls.append(svc) or IPS.get(svc, '10.43.0.1')
        faults = self.edge_faults()
        self.assertEqual(len(faults), 30)
        for p in faults:
            f = p['fault']
            manifest, subs = fm.render((ROOT / f['template']).read_text(), f, p['profile_name'] + '-fault', 300, lookup)
            doc = yaml.safe_load(manifest)
            ft = fm.filter_targets(manifest)
            # recorded filter == what the rendered manifest actually filters on
            self.assertEqual(ft['direction'], 'to')
            self.assertEqual(ft['injected_selector'], {'app': f['source_service']})
            self.assertEqual(ft['target_selector'], {'app': f['destination_service']})
            self.assertEqual(ft['external_targets'], [subs[fm.CLUSTER_IP_KEY]])
            self.assertEqual(subs[fm.CLUSTER_IP_KEY], lookup(f['destination_service']))
            self.assertEqual(doc['spec']['duration'], '300s')
            self.assertNotIn('{{', manifest)
        self.assertNotIn('frontend', calls)  # lookup is for destinations only

    def test_params_reach_manifest(self):
        f = next(p['fault'] for p in self.edge_faults() if p['fault']['type'] == 'network_delay')
        doc = yaml.safe_load(fm.render((ROOT / f['template']).read_text(), f, 'n', 300, IPS.get)[0])
        self.assertEqual(doc['spec']['delay']['latency'], f['params']['LATENCY'])
        f = next(p['fault'] for p in self.edge_faults() if p['fault']['type'] == 'packet_loss')
        doc = yaml.safe_load(fm.render((ROOT / f['template']).read_text(), f, 'n', 300, IPS.get)[0])
        self.assertEqual(doc['spec']['loss']['loss'], f['params']['LOSS_PERCENT'])

    def test_missing_clusterip_refuses(self):
        f = self.edge_faults()[0]['fault']
        t = (ROOT / f['template']).read_text()
        for bad in ('', 'None', '<none>'):
            with self.assertRaises(ValueError):
                fm.render(t, f, 'n', 300, lambda svc: bad)
        with self.assertRaises(ValueError):
            fm.render(t, f, 'n', 300)

    def test_unsubstituted_placeholder_refuses(self):
        f = {'type': 'cpu_saturation', 'target_kind': 'service_node', 'root_cause_service': 'checkoutservice', 'params': {}}
        with self.assertRaises(ValueError):
            fm.render((ROOT / 'deploy/chaos-mesh/faults/cpu-saturation.yaml').read_text(), f, 'n', 300)

    def test_observed_targets_join_and_consistency(self):
        pod = lambda name, uid, ip: {'metadata': {'name': name, 'uid': uid}, 'status': {'podIP': ip}}
        src = [pod('frontend-a', 'u1', '10.42.0.10')]
        dst = [pod('productcatalogservice-b', 'u2', '10.42.0.20')]
        records = [{'id': 'sentrix/productcatalogservice-b', 'selectorKey': '.Target'},
                   {'id': 'sentrix/frontend-a', 'selectorKey': '.'}]
        o = fm.observed_targets(records, src, dst)
        self.assertEqual(o['injected_source_pods'], [{'name': 'frontend-a', 'uid': 'u1', 'ip': '10.42.0.10'}])
        self.assertEqual(o['destination_pod_ips'], ['10.42.0.20'])
        self.assertTrue(o['selection_consistent'])
        # injected pod that is not a source pod -> inconsistent
        o = fm.observed_targets([{'id': 'sentrix/other-x', 'selectorKey': '.'}], src, dst)
        self.assertFalse(o['selection_consistent'])


class CpuTemplateTests(unittest.TestCase):
    def test_workers_and_load_from_params(self):
        params = yaml.safe_load(PARAMS.read_text())['faults']['cpu_saturation']['params']
        self.assertEqual(params, {'WORKERS': 4, 'LOAD': 100})
        p = next(p for p in generated_profiles() if p['fault']['type'] == 'cpu_saturation')
        manifest, _ = fm.render((ROOT / p['fault']['template']).read_text(), p['fault'], 'n', 300)
        cpu = yaml.safe_load(manifest)['spec']['stressors']['cpu']
        self.assertEqual((cpu['workers'], cpu['load']), (4, 100))
        self.assertIsNone(fm.filter_targets(manifest))


class IncidentControlMatchTests(unittest.TestCase):
    """Regression (SETUP-REVIEW 7.14): fault_then_control incident records
    matched the control against the fault run's start as a preceding control."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name)
        self.start = datetime(2026, 10, 19, 8, 45, tzinfo=timezone.utc)
        self.fault_end = self.start + timedelta(minutes=45)
        (self.run_dir / 'runtime.json').write_text(json.dumps(
            {'started_at': self.start.isoformat(), 'finished_at': self.fault_end.isoformat()}))
        self.summaries = [{'event_time': (self.start + timedelta(seconds=s)).isoformat()} for s in (1, 60, 600)]
        self.profile = {'target_rps': 2.4, 'duration': '25m'}

    def tearDown(self):
        self.tmp.cleanup()

    def control(self, started):
        return {'valid': True, 'errors': [], 'profile': self.profile, 'fingerprint': 'fp',
                'started_at': started.isoformat(), 'ended_at': (started + timedelta(minutes=25)).isoformat()}

    def test_fault_then_control_matches_following_control(self):
        prof = {**self.profile, 'pair_order': 'fault_then_control'}
        with patch.object(ev, 'assess_run', return_value=self.control(self.fault_end + timedelta(seconds=1))):
            m = incident.select_control_match(self.run_dir, 'c', prof, 'fp', self.summaries, 'v2')
        self.assertTrue(m['valid'], m)

    def test_fault_then_control_rejects_preceding_control(self):
        prof = {**self.profile, 'pair_order': 'fault_then_control'}
        with patch.object(ev, 'assess_run', return_value=self.control(self.start - timedelta(minutes=30))):
            m = incident.select_control_match(self.run_dir, 'c', prof, 'fp', self.summaries, 'v2')
        self.assertFalse(m['valid'])

    def test_control_then_fault_unchanged(self):
        with patch.object(ev, 'assess_run', return_value=self.control(self.start - timedelta(minutes=30))):
            m = incident.select_control_match(self.run_dir, 'c', self.profile, 'fp', self.summaries, 'v2')
        self.assertTrue(m['valid'], m)
        with patch.object(ev, 'assess_run', return_value=self.control(self.fault_end + timedelta(seconds=1))):
            m = incident.select_control_match(self.run_dir, 'c', self.profile, 'fp', self.summaries, 'v2')
        self.assertFalse(m['valid'])


if __name__ == '__main__':
    unittest.main()
