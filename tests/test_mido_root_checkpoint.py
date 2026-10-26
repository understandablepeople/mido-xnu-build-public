import unittest

from tools.mido_root_checkpoint import ROOT, WAIT, root_resource_wait


class RootResourceCheckpointTests(unittest.TestCase):
    def events(self):
        return [dict(function=ROOT, native_thread=42, caller_return_va=0x1004),
                dict(function=WAIT, native_thread=42, caller_return_va=0x2004,
                     timeout_nanoseconds=30_000_000_000)]

    def test_native_first_wait_is_not_a_mount_claim(self):
        result = root_resource_wait(self.events(), [0x3000, 0x2000], 42)
        self.assertEqual(result["audited_call"], 0x2000)
        for key in ("root_selected", "root_mounted", "userspace_booted", "device_boot_proven"):
            self.assertIs(result[key], False)

    def test_earlier_rtc_wait_is_not_root_evidence(self):
        self.assertIsNone(root_resource_wait(self.events()[1:], [0x2000], 42))

    def test_wrong_thread_or_later_call_is_not_checkpoint(self):
        for field, value in (("native_thread", 43), ("caller_return_va", 0x3004)):
            events = self.events()
            events[-1][field] = value
            self.assertIsNone(root_resource_wait(events, [0x2000, 0x3000], 42))

    def test_missing_audit_and_changed_timeout_fail_closed(self):
        with self.assertRaises(ValueError):
            root_resource_wait(self.events(), [], 42)
        events = self.events()
        events[-1]["timeout_nanoseconds"] = 1
        with self.assertRaises(ValueError):
            root_resource_wait(events, [0x2000], 42)
