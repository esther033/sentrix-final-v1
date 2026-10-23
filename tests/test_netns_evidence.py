import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fault_manifest  # noqa: E402
import netns_evidence  # noqa: E402

spec = importlib.util.spec_from_file_location('judge', ROOT / 'linux/capability/judge.py')
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)

# `tc -s qdisc show` in frontend's netns during the 2026-10-22 diagnosis
# (linux/out/diag-edge-*-loss): "loss 2% 25%" injected, netem dropped nothing.
QDISC_CORR25 = """qdisc noqueue 0: dev lo root refcnt 2
 Sent 0 bytes 0 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
qdisc prio 1: dev eth0 root refcnt 25 bands 4 priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1
 Sent 5487907 bytes 16539 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
qdisc sfq 2: dev eth0 parent 1:1 limit 127p quantum 1464b depth 127 divisor 1024
 Sent 0 bytes 0 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
qdisc netem 5: dev eth0 parent 1:4 limit 1000 loss 2% 25%
 Sent 503208 bytes 4873 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
qdisc sfq 3: dev eth0 parent 1:2 limit 127p quantum 1464b depth 127 divisor 1024
 Sent 4984567 bytes 11664 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
"""
QDISC_CORR0 = QDISC_CORR25.replace("loss 2% 25%", "loss 2%").replace(
    "Sent 503208 bytes 4873 pkt (dropped 0,", "Sent 491885 bytes 4765 pkt (dropped 87,")
NSTAT = "#kernel\nTcpOutSegs                      16531              0.0\nTcpRetransSegs                  64                 0.0\n"
QDISC_DELAY = QDISC_CORR25.replace("loss 2% 25%", "delay 100ms  10ms 25%")


def fake_kube(qdisc, fail=None):
    def kube(*args, input=None):
        if fail and fail in args:
            raise RuntimeError("boom")
        if args[:2] == ("get", "pods"):
            return "chaos-daemon-x"
        script = args[-1]
        if "/proc/[0-9]*" in script:
            return "10210 pause\n11564 server\n"
        out = []
        for key in netns_evidence.COMMANDS:
            out.append("@@@SENTRIX@@@" + key)
            out.append(qdisc if key == "tc_qdisc" else NSTAT if key == "nstat" else f"{key} output")
        assert "/proc/11564/ns/net" in script
        return "\n".join(out) + "\n"
    return kube


class NetnsEvidenceTests(unittest.TestCase):
    def test_parse_netem_counters(self):
        (n,) = netns_evidence.parse_netem(QDISC_CORR25)
        self.assertEqual((n["params"], n["sent_pkts"], n["dropped_pkts"], n["drop_pct"]), ("loss 2% 25%", 4873, 0, 0.0))
        (n,) = netns_evidence.parse_netem(QDISC_CORR0)
        self.assertEqual((n["params"], n["dropped_pkts"], n["drop_pct"]), ("loss 2%", 87, 1.79))
        self.assertEqual(netns_evidence.parse_netem("qdisc noqueue 0: dev eth0 root refcnt 2\n"), [])

    def test_capture_reads_source_pod_netns(self):
        ev = netns_evidence.capture(fake_kube(QDISC_CORR0), "frontend-x", "e2e4f7ec-fb7f")
        self.assertNotIn("error", ev)
        self.assertEqual((ev["pod"], ev["pod_uid"], ev["pid"], ev["daemon"]), ("frontend-x", "e2e4f7ec-fb7f", "11564", "chaos-daemon-x"))
        self.assertEqual(set(netns_evidence.COMMANDS) - set(ev), set())
        self.assertEqual(ev["ipset"].strip(), "ipset output")
        self.assertEqual(ev["netem"][0]["dropped_pkts"], 87)
        self.assertEqual(ev["tcp"], {"TcpOutSegs": 16531, "TcpRetransSegs": 64})

    def test_capture_never_raises(self):
        ev = netns_evidence.capture(fake_kube(QDISC_CORR0, fail="exec"), "frontend-x", "u")
        self.assertIn("error", ev)
        self.assertNotIn("tc_qdisc", ev)

    def test_verdict_flags_loss_that_dropped_nothing(self):
        bad = netns_evidence.summarize([{"netem": netns_evidence.parse_netem(QDISC_CORR25)}], "loss")
        self.assertEqual((bad["netem_present"], bad["applied"], bad["drop_pct"]), (True, False, 0.0))
        good = netns_evidence.summarize([{"netem": netns_evidence.parse_netem(QDISC_CORR0)}], "loss")
        self.assertTrue(good["applied"])
        delay = netns_evidence.summarize([{"netem": netns_evidence.parse_netem(QDISC_DELAY)}], "delay")
        self.assertTrue(delay["applied"])
        self.assertEqual(netns_evidence.summarize([{"error": "x"}], "loss"), {"netem_present": False, "applied": False, "tcp_delta": {}})
        self.assertIsNone(netns_evidence.summarize([], "loss")["applied"])
        start = [{"tcp": {"TcpRetransSegs": 285, "TcpOutSegs": 1000}}]
        end = [{"tcp": {"TcpRetransSegs": 349, "TcpOutSegs": 17531}, "netem": netns_evidence.parse_netem(QDISC_CORR0)}]
        self.assertEqual(netns_evidence.summarize(end, "loss", start)["tcp_delta"],
                         {"TcpRetransSegs": 64, "TcpOutSegs": 16531})


class LossTemplateTests(unittest.TestCase):
    def test_loss_template_uncorrelated(self):
        fault = {"type": "packet_loss", "target_kind": "dependency_edge", "source_service": "frontend",
                 "destination_service": "productcatalogservice", "root_cause_service": "frontend",
                 "params": {"LOSS_PERCENT": "2"}}
        text = (ROOT / "deploy/chaos-mesh/faults/packet-loss.yaml").read_text()
        manifest, _ = fault_manifest.render(text, fault, "x", 300, cluster_ip_of=lambda s: "10.43.82.246")
        loss = yaml.safe_load(manifest)["spec"]["loss"]
        self.assertEqual(loss, {"loss": "2", "correlation": "0"})


class CapabilityNetemCheckTests(unittest.TestCase):
    def test_judge_reads_probe_src_netem_drop(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "svc-tc-a-loss-end.txt")
            p.write_text("== probe-src-abc\n" + QDISC_CORR25.replace("loss 2% 25%", "loss 10% 25%").replace(
                "4873 pkt (dropped 0,", "4656 pkt (dropped 75,") + "---\n---\n== probe-dst-def\n" + QDISC_CORR0)
            self.assertEqual(judge.netem_drop_pct(p), 1.59)   # below the 5 % floor -> svc_loss_netem_drops FAIL
            self.assertIsNone(judge.netem_drop_pct(Path(tmp, "missing.txt")))

    def test_judge_delay_latency_and_jitter(self):
        import random
        rnd = random.Random(1)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "svc-addresses.txt").write_text("dst_pod=x\ndelay_from_template=100ms/10ms/0\n")
            self.assertEqual(judge.delay_spec(d), (100.0, 10.0))
            before = [0.0004 + rnd.random() * 1e-4 for _ in range(60)]
            line = lambda c: f"{c:.6f} {c + 0.1:.6f} 200"
            def shape(during):
                return judge.delay_shape(before, [x * 1000 for x in during])
            normal = [0.0004 + 0.1 + rnd.gauss(0, 0.010) for _ in range(60)]   # tc default: normal table
            flat = [0.1004 + rnd.random() * 1e-5 for _ in range(60)]           # jitter lost
            wide = [0.0004 + 0.1 + rnd.gauss(0, 0.040) for _ in range(60)]     # jitter blown up
            sn, sf, sw = shape(normal), shape(flat), shape(wide)
            self.assertLess(abs(sn["median_ms"] - 100), 15)
            self.assertTrue(2.5 <= sn["stdev_ms"] <= 15)
            self.assertLess(sf["stdev_ms"], 2.5)
            self.assertGreater(sw["stdev_ms"], 15)
            (d / "svc-a-before-dst_svc.txt").write_text("\n".join(map(line, before)) + "\n")
            (d / "svc-a-delay-dst_svc.txt").write_text("\n".join(map(line, normal)) + "\n")
            self.assertEqual(len(judge.connect_ms(d / "svc-a-delay-dst_svc.txt")), 60)
            checks = judge.service(d, "a", "a")["checks"]
            self.assertTrue(checks["svc_delay_latency_matches"] and checks["svc_delay_jitter_matches"])
            (d / "svc-a-delay-dst_svc.txt").write_text("\n".join(map(line, flat)) + "\n")
            self.assertFalse(judge.service(d, "a", "a")["checks"]["svc_delay_jitter_matches"])


if __name__ == "__main__":
    unittest.main()
