from copy import deepcopy
import unittest

from tools.mido_root_mount import image_loader_entry, init_exec_entry, mounted_diagnostic_root, user_entry_evidence


class RootMountTests(unittest.TestCase):
    def test_el0_requires_native_eret_and_matching_user_executable_mapping(self):
        init = dict(original_init_loader_return_observed=True, native_thread=7)
        eret = dict(native_thread=9, elr=0x100004000, spsr=0, original_kernel_eret=True)
        mapping = dict(status="mapped", access_flag=True, access_permissions=3, levels=[dict(descriptor=0x743)])
        code = bytes(range(28))
        evidence = user_entry_evidence(init, eret, 9, 0x100004000, 0, mapping, code, code)
        self.assertTrue(evidence["original_el0_entry_observed"])
        self.assertFalse(evidence["first_instruction_executed"])
        for thread, pc, state in ((7, 0x100004000, 0), (9, 0x100004004, 0), (9, 0x100004000, 4)):
            with self.assertRaises(ValueError):
                user_entry_evidence(init, eret, thread, pc, state, mapping, code, code)
        with self.assertRaises(ValueError):
            user_entry_evidence(init, eret, 9, 0x100004000, 0, mapping, code, bytes(28))
        mapping["levels"][0]["descriptor"] |= 1 << 54
        with self.assertRaises(ValueError):
            user_entry_evidence(init, eret, 9, 0x100004000, 0, mapping, code, code)

    def fixture(self):
        selection = dict(root_selected=True, root_name="md0", root_device=0x01000000,
                         native_registration=dict(native_thread=7))
        entry = dict(function="_vfs_mountroot", native_thread=7, returned_status=0)
        provider = dict(function="_mockfs_mountroot", native_thread=7, returned_status=0,
                        mount_pointer=0x1000, device_vnode=0x2000)
        return selection, [entry, provider], entry

    def test_accepts_only_observed_native_success_without_execution_claims(self):
        selection, events, mount = self.fixture()
        before = deepcopy(events)
        result = mounted_diagnostic_root(selection, events, mount, 7)
        self.assertTrue(result["root_vfs_mounted"])
        self.assertEqual(result["filesystem"], "mockfs")
        for key in ("disk_io_validated", "executable_validated", "userspace_booted", "device_boot_proven", "boot_approved"):
            self.assertFalse(result[key])
        self.assertEqual(events, before)

    def test_rejects_failed_or_wrong_thread_provider(self):
        for key, value in (("returned_status", 5), ("native_thread", 8), ("mount_pointer", 0), ("device_vnode", 0)):
            selection, events, mount = self.fixture()
            events[1][key] = value
            with self.assertRaises(ValueError):
                mounted_diagnostic_root(selection, events, mount, 7)

    def test_original_init_entry_is_not_userspace_execution(self):
        task = dict(function="_bsdinit_task", native_thread=9)
        entry = dict(function="_load_init_program", native_thread=9, process_pointer=0x1234,
                     caller_return_va=0x2004)
        result = init_exec_entry(dict(root_vfs_mounted=True), [task, entry], entry, [0x2000])
        self.assertTrue(result["original_init_loader_entered"])
        self.assertFalse(result["executable_loaded"])
        self.assertFalse(result["userspace_booted"])
        with self.assertRaises(ValueError):
            init_exec_entry(None, [task, entry], entry, [0x2000])
        with self.assertRaises(ValueError):
            init_exec_entry(dict(root_vfs_mounted=True), [task, entry], entry, [0x3000])
        task["native_thread"] = 8
        with self.assertRaises(ValueError):
            init_exec_entry(dict(root_vfs_mounted=True), [task, entry], entry, [0x2000])

    def test_image_entry_requires_actual_matching_header_and_strategy_return(self):
        header = bytes.fromhex("cffaedfe0c00000100000000") + bytes(20)
        init = dict(original_init_loader_entered=True, native_thread=9)
        read = dict(function="_mdevstrategy", native_thread=9, buffer_pointer=0x3000, original_return_observed=True)
        entry = dict(function="_load_machfile", native_thread=9, caller_return_va=0x4004)
        result = image_loader_entry(init, [read, entry], entry, [0x4000], header, header, True)
        self.assertTrue(result["root_payload_header_read"])
        self.assertFalse(result["executable_loaded"])
        self.assertFalse(result["userspace_booted"])
        with self.assertRaises(ValueError):
            image_loader_entry(init, [entry], entry, [0x4000], header, header, True)
        with self.assertRaises(ValueError):
            image_loader_entry(init, [read, entry], entry, [0x4000], header, bytes(32), True)
        with self.assertRaises(ValueError):
            image_loader_entry(init, [read, entry], entry, [0x4000], header, header, False)

    def test_rejects_missing_selection_vfs_failure_and_missing_callback(self):
        selection, events, mount = self.fixture()
        with self.assertRaises(ValueError):
            mounted_diagnostic_root(None, events, mount, 7)
        with self.assertRaises(ValueError):
            mounted_diagnostic_root(selection, [mount], mount, 7)
        mount["returned_status"] = 6
        with self.assertRaises(ValueError):
            mounted_diagnostic_root(selection, events, mount, 7)


if __name__ == "__main__":
    unittest.main()
