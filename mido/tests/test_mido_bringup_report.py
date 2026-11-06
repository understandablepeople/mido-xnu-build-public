import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("bringup_report", ROOT / "tools/mido_bringup_report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class BringupReportTests(unittest.TestCase):
    def test_noc_fsm_on_is_valid_but_other_status_nibbles_are_not(self):
        text = self.log().replace("on=00000001", "on=20008001", 1)
        self.assertTrue(REPORT.summarize(text)["gpu_six_clocks_on"])
        for nibble in range(1, 16):
            if nibble == 2:
                continue
            text = self.log().replace("on=00000001", f"on={nibble:x}0000001", 1)
            self.assertFalse(REPORT.summarize(text)["gpu_six_clocks_on"])

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

    def power_log(self):
        text = ""
        for index, number, value, sets in ((0, 7, 384, 1), (1, 2, 256, 3),
                (2, 5, 1800000, 3), (3, 7, 1800000, 3),
                (4, 19, 1300000, 3), (5, 9, 3300000, 3)):
            for selected in range(2):
                if sets & (1 << selected):
                    text += f"MIDO WIFI POWER: supply={index} id={number} set={selected} value={value} result=0\n"
        return text + ("MIDO WIFI POWER: supplies/XO acknowledged; SCM clocks/IRIS/PAS/SMD/DXE not started\n"
                       "MIDO WIFI POWER: result=1 shared-cx-floor=256\n")

    def test_new_power_and_nominal_rate_proof_never_imply_drivers(self):
        text = self.log() + self.power_log() + ("MIDO GPU RATE: GPLL0/2 HID=5 nominal=133330000 polls=1; no GPU/SMMU access\n"
                                               "MIDO GPU RATE: result=1\n")
        report = REPORT.summarize(text)
        self.assertTrue(report["gpu_nominal_133mhz_selection_acknowledged"])
        self.assertTrue(report["wifi_supplies_xo_acknowledged"])
        self.assertFalse(report["gpu_acceleration_established"])
        self.assertFalse(report["wifi_network_established"])
        self.assertFalse(REPORT.summarize(text + "MIDO GPU RATE: result=-7\n")["gpu_nominal_133mhz_selection_acknowledged"])

    def test_missing_failed_wrong_or_sleep_supply_vote_is_not_success(self):
        text = self.power_log()
        for changed in (text.replace("supply=5 id=9 set=1 value=3300000 result=0\n", "", 1),
                        text.replace("result=0", "result=-9", 1),
                        text.replace("value=1300000", "value=1800000", 1),
                        text.replace("shared-cx-floor=256", "shared-cx-floor=192", 1),
                        text + "MIDO WIFI POWER: result=-3 shared-cx-floor=256\n"):
            self.assertFalse(REPORT.summarize(changed)["wifi_supplies_xo_acknowledged"])
        self.assertTrue(REPORT.summarize(text.replace("value=256", "value=320").replace("floor=256", "floor=320"))["wifi_supplies_xo_acknowledged"])

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
