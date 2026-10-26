import unittest

from tools.audit_mido_root_support import audit


class RootSupportAuditTests(unittest.TestCase):
    def tree(self, ramdisk=None):
        properties = {} if ramdisk is None else {"RAMDisk": ramdisk}
        return dict(name="root", properties={}, children=[
            dict(name="chosen", properties={}, children=[
                dict(name="memory-map", properties=properties, children=[])])])

    def symbols(self):
        return {name: 0x1000 for name in ("_mdevadd", "_mdevlookup", "_mdevstrategy", "_mdevrw")}

    def test_current_memdev_without_disk_or_filesystem_is_not_bootable(self):
        result = audit(self.symbols(), self.tree())
        self.assertEqual(result["blockers"], ["no-ramdisk-in-chosen-memory-map",
                                             "no-recognized-root-filesystem-provider-symbols"])
        self.assertFalse(result["root_mounted"])

    def test_symbol_or_property_presence_never_approves_boot(self):
        symbols = self.symbols()
        symbols["_hfs_vfsops"] = 0x2000
        result = audit(symbols, self.tree(bytes(16)))
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["boot_approved"])
        self.assertFalse(result["root_selected"])

    def test_malformed_property_and_incomplete_memdev_remain_blockers(self):
        result = audit({}, self.tree(bytes(8)))
        self.assertIn("invalid-arm64-ramdisk-property-size", result["blockers"])
        self.assertIn("native-memory-device-path-incomplete", result["blockers"])

    def test_missing_chosen_is_not_a_configured_ramdisk(self):
        self.assertFalse(audit(self.symbols(), dict(children=[]))["ramdisk_property_present"])
