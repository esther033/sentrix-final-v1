from collections import Counter
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import campaign_shard  # noqa: E402
import host_state  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load('generate_campaign', 'generate-campaign.py')
campaign = load('run_campaign', 'run-campaign.py')
PLAN = ROOT / 'campaigns/linux-v1/campaign-plan.yaml'
PARAMS = ROOT / 'campaigns/linux-v1/fault-params.yaml'
PCS = ['206-40', 'pc-b', 'pc-c']


class ShardTests(unittest.TestCase):
    """69-pair schedule from one seed, dealt to 3 PCs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.docs = {}
        for seed in (1, 7, 20261016):
            _, schedule_json, _ = gen.render(PLAN, PARAMS, seed, 'workload/profiles/linux-v1', 6)
            path = Path(cls.tmp.name, str(seed), 'schedule.json')
            path.parent.mkdir()
            path.write_text(schedule_json, encoding='utf-8')
            files = campaign_shard.render(path, PCS)
            cls.docs[seed] = (path, json.loads(schedule_json),
                              {Path(p).stem: json.loads(t) for p, t in files.items()})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_pair_in_exactly_one_shard(self):
        for seed, (_, schedule, shards) in self.docs.items():
            self.assertEqual(sorted(shards), sorted(PCS))
            ids = Counter(p['pair_id'] for doc in shards.values() for p in doc['pairs'])
            self.assertEqual(set(ids), {p['pair_id'] for p in schedule['pairs']}, seed)
            self.assertEqual(set(ids.values()), {1}, seed)
            self.assertEqual(sum(len(d['pairs']) for d in shards.values()), 69)

    def test_both_runs_of_a_pair_in_the_same_shard(self):
        for seed, (_, schedule, shards) in self.docs.items():
            owner = {}
            for name, doc in shards.items():
                for p in doc['pairs']:
                    for run in (p['fault_run_id'], p['control_run_id']):
                        self.assertNotIn(run, owner, seed)
                        owner[run] = name
            for p in schedule['pairs']:
                self.assertEqual(owner[p['fault_run_id']], owner[p['control_run_id']])
            self.assertEqual(len(owner), 138)

    def test_fault_type_spread_per_pc_at_most_2(self):
        for seed, (_, schedule, shards) in self.docs.items():
            for t in {p['fault_type'] for p in schedule['pairs']}:
                counts = [Counter(p['fault_type'] for p in d['pairs'])[t] for d in shards.values()]
                self.assertLessEqual(max(counts) - min(counts), 2, (seed, t, counts))
            totals = [len(d['pairs']) for d in shards.values()]
            self.assertEqual(totals, [23, 23, 23])

    def test_each_pc_gets_every_cell_once_with_mixed_repetitions(self):
        # 3 PCs x 3 repetitions: a cell's repetitions go to different PCs, so
        # PC never coincides with a cell or with a repetition (CV fold)
        for seed, (_, schedule, shards) in self.docs.items():
            cells = {(p['fault_type'], p['target_id']) for p in schedule['pairs']}
            for doc in shards.values():
                mine = Counter((p['fault_type'], p['target_id']) for p in doc['pairs'])
                self.assertEqual(set(mine), cells, seed)
                self.assertEqual(set(mine.values()), {1}, seed)
                self.assertEqual(doc['summary']['targets'], len(cells))
                reps = doc['summary']['repetition']
                self.assertEqual(set(reps), {'1', '2', '3'})
                self.assertLess(max(reps.values()), len(doc['pairs']) * 0.6, (seed, reps))

    def test_two_pcs_also_balanced(self):
        for seed in self.docs:
            _, schedule, _ = self.docs[seed]
            shards = campaign_shard.assign(schedule['pairs'], ['206-40', '206-39'])
            self.assertEqual(sorted(len(v) for v in shards.values()), [34, 35])
            for t in {p['fault_type'] for p in schedule['pairs']}:
                counts = [sum(p['fault_type'] == t for p in v) for v in shards.values()]
                self.assertLessEqual(max(counts) - min(counts), 2)
                self.assertGreater(min(counts), 0)          # both PCs get every fault type
            for v in shards.values():                       # PC not confounded with pair order
                orders = Counter(p['pair_order'] for p in v)
                self.assertLessEqual(abs(orders['control_then_fault'] - orders['fault_then_control']), 3, seed)
            cells = Counter((p['fault_type'], p['target_id'], n) for n, v in shards.items() for p in v)
            self.assertEqual(set(cells.values()), {1, 2})     # every cell's 3 repetitions split 2/1

    def test_schedule_order_kept_and_schedule_pinned(self):
        path, schedule, shards = self.docs[1]
        for name, doc in shards.items():
            idx = [p['schedule_index'] for p in doc['pairs']]
            self.assertEqual(idx, sorted(idx))
            self.assertEqual(doc['shard'], name)
            self.assertEqual(doc['shards'], PCS)
            self.assertEqual(doc['seed'], 1)
            shard_name, ids = campaign_shard.load_shard(self._write(doc), path, schedule)
            self.assertEqual((shard_name, ids), (name, {p['pair_id'] for p in doc['pairs']}))
            selected = campaign.select_pairs(schedule['pairs'], shard=ids)
            self.assertEqual([p['pair_id'] for p in selected], [p['pair_id'] for p in doc['pairs']])

    def test_load_shard_refuses_other_schedule_or_campaign(self):
        path, schedule, shards = self.docs[1]
        other_path, _, _ = self.docs[7]
        shard = self._write(shards['pc-b'])
        with self.assertRaisesRegex(ValueError, 'sha256'):
            campaign_shard.load_shard(shard, other_path, schedule)
        with self.assertRaisesRegex(ValueError, 'campaign'):
            campaign_shard.load_shard(shard, path, {**schedule, 'campaign_id': 'calib2-linux-v1'})

    def test_run_campaign_refuses_shard_of_another_host(self):
        path, _, shards = self.docs[1]
        shard = self._write(shards['pc-b'])
        with patch.object(campaign, 'environment_id', return_value='206-40'):
            with self.assertRaisesRegex(SystemExit, "for PC 'pc-b'"):
                campaign.main(['--schedule', str(path), '--shard', str(shard), '--allow-draft'])

    def test_names_must_be_distinct(self):
        with self.assertRaises(ValueError):
            campaign_shard.assign([], ['a', 'a'])
        with self.assertRaises(ValueError):
            campaign_shard.assign([], ['bad/name'])
        with self.assertRaises(ValueError):   # shard names follow the environment ID rule
            campaign_shard.assign([], ['D'])

    def _write(self, doc):
        p = Path(self.tmp.name, f"shard-{doc['shard']}-{doc['seed']}.json")
        p.write_text(json.dumps(doc), encoding='utf-8')
        return p


class EnvironmentIdTests(unittest.TestCase):
    """SENTRIX_ENVIRONMENT_ID > linux/config/local.env > hostname; [a-z0-9-] only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name, 'local.env')

    def tearDown(self):
        self.tmp.cleanup()

    def env_id(self, environ=None, hostname='206-40'):
        return host_state.environment_id(environ or {}, self.local, lambda: hostname)

    def test_hostname_when_nothing_set(self):
        self.assertEqual(self.env_id(), '206-40')
        self.assertEqual(host_state.environment_id({}, self.local), socket.gethostname())

    def test_local_env_over_hostname_and_variable_over_both(self):
        self.local.write_text('# comment\nOTHER=x\nexport SENTRIX_ENVIRONMENT_ID="206-39"\n', encoding='utf-8')
        self.assertEqual(self.env_id(hostname='D'), '206-39')
        self.assertEqual(self.env_id({'SENTRIX_ENVIRONMENT_ID': '206-38'}, hostname='D'), '206-38')

    def test_invalid_ids_refused(self):
        with self.assertRaisesRegex(ValueError, "'D' from hostname"):
            self.env_id(hostname='D')            # 206-39 without local.env
        for bad in ('206_39', '206-39 ', 'pc.b', '-a', 'a--b', 'PC-B'):
            with self.assertRaises(ValueError, msg=bad):
                self.env_id({'SENTRIX_ENVIRONMENT_ID': bad})
        self.local.write_text('SENTRIX_ENVIRONMENT_ID=Bad\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'local.env'):
            self.env_id()

    def test_example_file_valid_format(self):
        example = host_state.local_env(ROOT / 'linux/config/local.env.example')
        self.assertIn('SENTRIX_ENVIRONMENT_ID', example)
        self.assertIn('linux/config/local.env', (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines())

    def test_run_attended_records_the_id(self):
        text = (ROOT / 'scripts/run-attended.py').read_text(encoding='utf-8')
        self.assertIn('"environment_id":env_id', text)
        self.assertLess(text.index('env_id = environment_id()'), text.index('run_dir.mkdir()'))


if __name__ == '__main__':
    unittest.main()
