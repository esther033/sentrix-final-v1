"""206-40 operation: clock/boot gate, run-manifest host block, daily campaign blocks."""
from datetime import datetime, timedelta, timezone
import gc
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

from test_data_views import module
import host_state

attended = module("run-attended")
manifest = module("generate-run-manifest")
campaign = module("run-campaign")

KST = timezone(timedelta(hours=9))


def completed(stdout, rc=0):
    return lambda *a, **k: SimpleNamespace(returncode=rc, stdout=stdout, stderr="")


class HostStateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "boot_id").write_text("1111-aaaa\n")
        (self.dir / "stat").write_text("cpu  1 2 3\nbtime 1792141800\nprocesses 5\n")

    def clock(self, stdout, rc=0):
        return host_state.host_clock(self.dir / "boot_id", self.dir / "stat", runner=completed(stdout, rc))

    def test_reads_boot_id_boot_time_and_ntp(self):
        c = self.clock("yes\n")
        self.assertEqual(c["boot_id"], "1111-aaaa")
        self.assertEqual(c["booted_at"], datetime.fromtimestamp(1792141800, timezone.utc).isoformat())
        self.assertEqual(c["ntp_synchronized"], "yes")

    def test_ntp_unknown_when_timedatectl_missing_or_fails(self):
        def missing(*a, **k):
            raise FileNotFoundError("timedatectl")
        self.assertEqual(host_state.ntp_synchronized(missing), "unknown")
        self.assertEqual(host_state.ntp_synchronized(completed("", rc=1)), "unknown")
        self.assertEqual(host_state.ntp_synchronized(completed("garbage\n")), "unknown")
        def hang(*a, **k):
            raise subprocess.TimeoutExpired("timedatectl", 10)
        self.assertEqual(host_state.ntp_synchronized(hang), "unknown")

    def test_require_ntp_accepts_only_yes(self):
        host_state.require_ntp(self.clock("yes\n"))
        for value in ("no\n", ""):
            with self.assertRaisesRegex(ValueError, "NTP not synchronized"):
                host_state.require_ntp(self.clock(value))

    def test_reboot_detected_only_when_boot_id_changes(self):
        start = {"boot_id": "a", "booted_at": "t0"}
        self.assertEqual(host_state.reboot_errors(start, {"boot_id": "a"}), [])
        errors = host_state.reboot_errors(start, {"boot_id": "b", "booted_at": "t1"})
        self.assertEqual(len(errors), 1)
        self.assertIn("host rebooted during run", errors[0])
        self.assertIn("a -> b", errors[0])
        # A missing observation is not evidence of a reboot.
        self.assertEqual(host_state.reboot_errors(start, {"boot_id": None}), [])
        self.assertEqual(host_state.reboot_errors(None, {"boot_id": "b"}), [])


class AttendedClockGateTests(unittest.TestCase):
    def test_run_refuses_before_any_cluster_access_when_ntp_not_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "control.json"
            profile.write_text(json.dumps({"duration": "25m", "warmup_seconds": 180, "baseline_seconds": 300,
                                           "fault_seconds": 300, "recovery_seconds": 600, "cooldown_seconds": 120}))
            args = SimpleNamespace(run_id="test-school-pc-ntp-gate-never-created", profile=str(profile),
                                   control_run_id=None, defer_control_match=False)
            run_dir = attended.ROOT / "runs" / args.run_id
            self.assertFalse(run_dir.exists())
            unsynced = {"boot_id": "x", "booted_at": None, "ntp_synchronized": "no"}
            with patch.object(attended, "host_clock", return_value=unsynced), \
                 patch.object(attended, "no_active_chaos", side_effect=AssertionError("cluster touched")), \
                 patch.object(attended, "snapshot", side_effect=AssertionError("cluster touched")):
                with self.assertRaisesRegex(ValueError, "NTP not synchronized"):
                    attended.run(args)
            self.assertFalse(run_dir.exists())


class ManifestHostBlockTests(unittest.TestCase):
    def test_host_block_joins_runtime_start_end_and_manifest_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = {"boot_id": "a", "booted_at": "t0", "ntp_synchronized": "yes"}
            end = {"boot_id": "a", "booted_at": "t0", "ntp_synchronized": "yes"}
            Path(tmp, "runtime.json").write_text(json.dumps({"host_at_start": start, "host_at_end": end}))
            now = {"boot_id": "a", "ntp_synchronized": "yes"}
            block = manifest.host_block(tmp, current=now)
            self.assertEqual(block, {"at_start": start, "at_end": end, "at_manifest": now})

    def test_host_block_without_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = manifest.host_block(tmp, current={"boot_id": "a"})
            self.assertIsNone(block["at_start"])
            self.assertIsNone(block["at_end"])


def pair(i, fault_type):
    return {"schedule_index": i, "pair_id": f"p{i}-{fault_type}", "fault_type": fault_type,
            "fault_run_id": f"f{i}", "control_run_id": f"c{i}", "fault_profile": "x.json",
            "control_profile": "y.json", "pair_order": "control_then_fault", "onset_offset_seconds": 480}


class CampaignBlockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.pairs = [pair(1, "pod_failure"), pair(2, "packet_loss"), pair(3, "cpu_saturation"),
                      pair(4, "traffic_surge"), pair(5, "network_delay"), pair(6, "cpu_saturation")]
        self.schedule = self.root / "schedule.json"
        self.schedule.write_text(json.dumps({"campaign_id": "t", "draft": False, "pairs": self.pairs}))
        patcher = patch.object(campaign, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def main(self, *argv):
        out = io.StringIO()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with redirect_stdout(out):
                rc = campaign.main(["--schedule", str(self.schedule), *argv])
            gc.collect()
        leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual(leaked, [], "queue.log left open")
        return rc, out.getvalue()

    def test_fault_type_filter_keeps_schedule_order(self):
        tier1 = ["cpu_saturation", "network_delay", "packet_loss"]
        rc, out = self.main("--dry-run", *sum((["--fault-type", t] for t in tier1), []))
        self.assertEqual(rc, 0)
        ids = [json.loads(line)["pair_id"] for line in out.splitlines() if line.startswith("{")]
        self.assertEqual(ids, ["p2-packet_loss", "p3-cpu_saturation", "p5-network_delay", "p6-cpu_saturation"])
        self.assertEqual(campaign.select_pairs(self.pairs, only=["p3-cpu_saturation", "p1-pod_failure"],
                                               fault_types=["cpu_saturation"]), [self.pairs[2]])

    def test_unknown_fault_type_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "unknown --fault-type"):
            campaign.main(["--schedule", str(self.schedule), "--dry-run", "--fault-type", "cpu"])

    def test_stop_before_deadline_rolls_to_next_day(self):
        start = datetime(2026, 10, 16, 20, 0, tzinfo=KST)
        self.assertEqual(campaign.next_deadline((7, 0), start), datetime(2026, 10, 17, 7, 0, tzinfo=KST))
        self.assertEqual(campaign.next_deadline((21, 30), start), datetime(2026, 10, 16, 21, 30, tzinfo=KST))
        with self.assertRaises(Exception):
            campaign.parse_hhmm("25:00")
        self.assertEqual(campaign.parse_hhmm("09:05"), (9, 5))

    def test_fits_before_counts_settle_and_pair_estimate(self):
        deadline = datetime(2026, 10, 16, 18, 0, tzinfo=KST)
        # 16:20 + 5 min settle + 95 min = 18:00 -> still allowed; one minute later is not.
        self.assertTrue(campaign.fits_before(datetime(2026, 10, 16, 16, 20, tzinfo=KST), deadline, 300, 95))
        self.assertFalse(campaign.fits_before(datetime(2026, 10, 16, 16, 21, tzinfo=KST), deadline, 300, 95))
        self.assertTrue(campaign.fits_before(datetime(2026, 10, 16, 23, 0, tzinfo=KST), None, 300, 95))

    def test_stop_before_does_not_start_pair(self):
        with patch.object(campaign, "fits_before", return_value=False), \
             patch.object(campaign, "gate", side_effect=AssertionError("gate reached")), \
             patch.object(campaign.subprocess, "run", side_effect=AssertionError("pair started")):
            rc, out = self.main("--stop-before", "23:59")
        self.assertEqual(rc, 0)
        self.assertIn("would not finish in time", out)
        self.assertIn("would not finish in time", (self.root / "runs/_campaign/t/queue.log").read_text())

    def test_low_disk_stops_before_pair(self):
        usage = lambda path: SimpleNamespace(free=5 * 2**30)
        self.assertEqual(len(campaign.low_disk([self.root], 20, usage)), 1)
        self.assertEqual(campaign.low_disk([self.root], 4, usage), [])
        self.assertEqual(campaign.low_disk([self.root / "missing"], 20, usage), [])
        with patch.object(campaign, "gate", side_effect=AssertionError("gate reached")), \
             patch.object(campaign.subprocess, "run", side_effect=AssertionError("pair started")):
            rc, out = self.main("--min-free-gib", "1000000000")
        self.assertEqual(rc, 4)
        self.assertIn("STOP: low disk", out)

    def test_gate_requires_ntp(self):
        empty = {"items": []}
        with patch.object(campaign, "kubectl_json", return_value=empty), \
             patch.object(campaign, "ntp_synchronized", return_value="no"):
            self.assertEqual(campaign.gate(), ["NTP not synchronized (no)"])
        with patch.object(campaign, "kubectl_json", return_value=empty), \
             patch.object(campaign, "ntp_synchronized", return_value="yes"):
            self.assertEqual(campaign.gate(), [])

    def test_log_closed_on_stop_file_exit(self):
        state = self.root / "runs/_campaign/t"
        state.mkdir(parents=True)
        (state / "STOP").write_text("x")
        rc, out = self.main()
        self.assertEqual(rc, 0)
        self.assertIn("STOP file present", out)


if __name__ == "__main__":
    unittest.main()
