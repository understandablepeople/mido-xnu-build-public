import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("bringup_report", ROOT / "tools/mido_bringup_report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class BringupReportTests(unittest.TestCase):
    def log(self):
        text = "".join(f"MIDO GPU CLOCKS: branch={offset} on=00000001 polls=1\n"
                       for offset in ("59028", "59030", "59034", "59040", "59044", "59020"))
        return text + ("MIDO GPU CLOCKS: result=1\n"
            "MIDO GPU STATUS: rbbm=00000000 status3=00000000 ahb-error=00000000 vbif-version=12345678\n"
            "MIDO GPU STATUS: result=1\n"
            "MIDO SCM: PAS supported peripheral=6 result=0 supported=1 smc64=1\n"
            "MIDO SCM: PAS supported peripheral=13 result=0 supported=1 smc64=1\n"
            "MIDO WIFI CLOCKS: crypto-root=80000000 cfg=00000113 core=80000000 bus=80000000 iface=80000000\n"
            "MIDO WIFI CLOCKS: result=1\n")

    def test_complete_stage_proof_never_claims_acceleration_or_network(self):
        report = REPORT.summarize(self.log())
        self.assertTrue(report["gpu_six_clocks_on"])
        self.assertTrue(report["gpu_readonly_probe_ok"])
        self.assertEqual(report["issues"], [])
        self.assertFalse(report["gpu_acceleration_established"])
        self.assertFalse(report["wifi_network_established"])

    def test_old_or_empty_log_not_mislabeled_success(self):
        report = REPORT.summarize("MIDO GPU GX: POWER_ON\nMIDO SCM: PAS command=7 availability result=0 available=1\n")
        self.assertFalse(report["gpu_six_clocks_on"])
        self.assertFalse(report["gpu_readonly_probe_ok"])
        self.assertEqual(len(report["issues"]), 5)

    def test_control_mismatch_or_missing_branch_rejects_clock_proof(self):
        for text in (self.log().replace("branch=59034", "branch=12345"),
                     self.log().replace("on=00000001", "on=80000001", 1),
                     self.log().replace("polls=1", "polls=1001", 1),
                     self.log().replace("CLOCKS: result=1", "CLOCKS: result=-5", 1)):
            self.assertFalse(REPORT.summarize(text)["gpu_six_clocks_on"])

    def test_bad_version_or_failed_transport_not_success(self):
        for value in ("00000000", "ffffffff"):
            self.assertFalse(REPORT.summarize(self.log().replace("12345678", value))["gpu_readonly_probe_ok"])
        report = REPORT.summarize(self.log().replace("peripheral=6 result=0", "peripheral=6 result=-12"))
        self.assertIsNone(report["pas_support"]["6"]["supported"])
        self.assertIn("PAS6 support query missing or transport failed", report["issues"])
