import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_mockfs import CONFIG_ANCHOR, FAST_BEGIN, FAST_END, SOURCE_HASHES, stage_mockfs


class MockfsStagingTests(unittest.TestCase):
    def populate(self, root):
        config = CONFIG_ANCHOR + b"\npseudo-device mido_runtime\n"
        files = {"config/MASTER.arm64.MIDO": config, "bsd/conf/Makefile.arm64": b"original rules\n"}
        hashes = {}
        for name in SOURCE_HASHES:
            data = name.encode() + b"\n"
            if name == "mockfs_fsnode.c":
                data += b"kalloc_type(mockfs_fsnode_t, flags);\nkfree_type(mockfs_fsnode_t, node);\n"
            if name == "mockfs_vfsops.c":
                data += FAST_BEGIN + b"\t\tmockfs_mount_data->mockfs_memory_backed = memdev_info.mi_mdev;\n" + FAST_END
            files["bsd/miscfs/mockfs/" + name] = data
            hashes[name] = hashlib.sha256(data).hexdigest()
        files["bsd/conf/files"] = b"".join(("bsd/miscfs/mockfs/" + name + "\toptional mockfs\n").encode()
                                            for name in SOURCE_HASHES if name.endswith(".c"))
        for relative, data in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return files, hashes, hashlib.sha256(config).hexdigest()

    def test_real_allocation_type_and_original_block_io_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, hashes, config_hash = self.populate(root)
            with patch("tools.stage_mido_mockfs.SOURCE_HASHES", hashes), \
                    patch("tools.stage_mido_mockfs.CONFIG_SHA256", config_hash):
                report = stage_mockfs(root)
            nodes = (root / "bsd/miscfs/mockfs/mockfs_fsnode.c").read_bytes()
            self.assertIn(b"kalloc_type(struct mockfs_fsnode,", nodes)
            self.assertIn(b"kfree_type(struct mockfs_fsnode,", nodes)
            mount = (root / "bsd/miscfs/mockfs/mockfs_vfsops.c").read_bytes()
            self.assertIn(b"#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_DIAGNOSTIC_MOCKFS)\n" + FAST_BEGIN, mount)
            self.assertIn(b"\t}\n#endif\n\n\tlck_mtx_init", mount)
            self.assertEqual((root / "bsd/miscfs/mockfs/mockfs_vnops.c").read_bytes(), before["bsd/miscfs/mockfs/mockfs_vnops.c"])
            self.assertEqual((root / "bsd/conf/files").read_bytes(), before["bsd/conf/files"])
            self.assertIn(b" config_fse mockfs ]", (root / "config/MASTER.arm64.MIDO").read_bytes())
            self.assertEqual((root / "bsd/conf/Makefile.arm64").read_bytes().count(b"-fno-lto"), 3)
            self.assertFalse(report["boot_approved"])
            self.assertFalse(report["root_mounted"])
            self.assertFalse(report["production_filesystem"])

    def test_unknown_source_config_and_graph_fail_before_any_writes(self):
        for changed in ("bsd/miscfs/mockfs/mockfs_fsnode.c", "config/MASTER.arm64.MIDO", "bsd/conf/files"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                before, hashes, config_hash = self.populate(root)
                (root / changed).write_bytes(b"unreviewed data\n")
                before[changed] = b"unreviewed data\n"
                with patch("tools.stage_mido_mockfs.SOURCE_HASHES", hashes), \
                        patch("tools.stage_mido_mockfs.CONFIG_SHA256", config_hash), self.assertRaises(ValueError):
                    stage_mockfs(root)
                self.assertTrue(all((root / name).read_bytes() == data for name, data in before.items()))

    def test_opt_in_requires_memory_root_before_setup(self):
        with patch("tools.check_xnu_build.setup") as setup, \
                self.assertRaisesRegex(ValueError, "explicit memory-root"):
            check(Path("unused"), "iphoneos", experimental_mockfs=True)
        setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
