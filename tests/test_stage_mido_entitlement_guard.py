import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_entitlement_guard import ANCHOR, GUARD, stage_entitlement_guard


class EntitlementGuardTests(unittest.TestCase):
    def populate(self, root):
        unit = ANCHOR + b"\t\ttask = current_task();\n\t}\n\treturn amfi->query(task, entitlement);\n}\n"
        files = {"iokit/bsddev/IOKitBSDInit.cpp": unit,
                 "iokit/conf/Makefile.arm64": b"original rules\n",
                 "config/MASTER.arm64.MIDO": b"pseudo-device mido_runtime\n"}
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return files, hashlib.sha256(unit).hexdigest()

    def test_missing_provider_denied_and_original_query_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, digest = self.populate(root)
            with patch("tools.stage_mido_entitlement_guard.SOURCE_SHA256", digest):
                report = stage_entitlement_guard(root)
            after = (root / "iokit/bsddev/IOKitBSDInit.cpp").read_bytes()
            self.assertEqual(after.replace(GUARD, b""), before["iokit/bsddev/IOKitBSDInit.cpp"])
            self.assertIn(b"if (amfi == NULL) {\n\t\treturn false;", after)
            self.assertNotIn(b"return true", after)
            self.assertIn(b"IOKitBSDInit.cpo_CFLAGS_ADD", (root / "iokit/conf/Makefile.arm64").read_bytes())
            self.assertFalse(report["entitlements_granted"])
            self.assertFalse(report["signature_verification_bypassed"])

    def test_unknown_source_or_config_fails_before_writes(self):
        for name in ("iokit/bsddev/IOKitBSDInit.cpp", "config/MASTER.arm64.MIDO"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                before, digest = self.populate(root)
                before[name] = b"unknown input\n"
                (root / name).write_bytes(before[name])
                with patch("tools.stage_mido_entitlement_guard.SOURCE_SHA256", digest), self.assertRaises(ValueError):
                    stage_entitlement_guard(root)
                self.assertTrue(all((root / name).read_bytes() == data for name, data in before.items()))

    def test_opt_in_requires_mockfs_before_setup(self):
        with patch("tools.check_xnu_build.setup") as setup, self.assertRaisesRegex(ValueError, "explicit mockfs"):
            check(Path("unused"), "iphoneos", experimental_entitlement_guard=True)
        setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
