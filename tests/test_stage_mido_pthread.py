import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_pthread import COMMIT, SUPPORT_REPAIRS, SYNCH_REPAIRS, dependency_files, stage_pthread


ROOT = Path(__file__).resolve().parents[1]


class PthreadStagingTests(unittest.TestCase):
    def archive(self, directory, extra=None):
        path = directory / "artifacts/libpthread-mido.tar.gz"
        path.parent.mkdir()
        members = {"kern/" + name: b"native implementation\n" for name in
                   ("kern_init.c", "kern_support.c", "kern_synch.c")}
        members.update(extra or {})
        members["kern/kern_support.c"] = b"\n".join(
            original for original, replacement, count in SUPPORT_REPAIRS for occurrence in range(count))
        members["kern/kern_synch.c"] = b"\n".join(
            original for original, replacement, count in SYNCH_REPAIRS for occurrence in range(count))
        members["kern/kern_trace.h"] = b"vm_kernel_unslide_or_perm_external(ptr, &unslid_ptr);"
        with tarfile.open(path, "w:gz") as package:
            for name, data in members.items():
                member = tarfile.TarInfo("libpthread-" + COMMIT + "/" + name)
                member.size = len(data)
                package.addfile(member, io.BytesIO(data))
        return path

    def test_unknown_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.archive(Path(temporary))
            with self.assertRaisesRegex(ValueError, "unreviewed"):
                dependency_files(path)

    def test_traversal_rejected_even_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.archive(Path(temporary), {"../escape.c": b"bad"})
            with patch("tools.stage_mido_pthread.ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    dependency_files(path)

    def test_staging_is_mido_only_and_preserves_original_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            archive = self.archive(workspace)
            source = workspace / "source"
            configuration = source / "bsd/conf"
            configuration.mkdir(parents=True)
            for name in ("files", "Makefile.arm64"):
                (configuration / name).write_bytes(b"original\n")
            runtime = workspace / "devices/mido/xnu/runtime"
            runtime.mkdir(parents=True)
            (runtime / "mido_pthread_startup.c").write_bytes(b"registration\n")
            with patch("tools.stage_mido_pthread.ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()):
                report = stage_pthread(source, workspace)
                self.assertFalse(report["boot_approved"])
                graph = (configuration / "files").read_text()
                self.assertTrue(graph.startswith("original\n"))
                self.assertEqual(graph.count("optional mido_runtime"), 4)
                flags = (configuration / "Makefile.arm64").read_text()
                self.assertEqual(flags.count("-Dpthread_kern=mido_pthread_callbacks"), 3)
                self.assertEqual(flags.count("-UBSD_KERNEL_PRIVATE"), 3)
                self.assertEqual(flags.count("-UXNU_KERNEL_PRIVATE -UMACH_KERNEL_PRIVATE"), 3)
                self.assertIn("-Dcurrent_uthread=mido_pthread_current_uthread", flags)
                self.assertIn("mido_pthread_kern_synch.o_CFLAGS_ADD", flags)
                self.assertIn("-idirafter $(SDKROOT)/usr/include", flags)
                self.assertNotIn("\nkern_synch.o_CFLAGS_ADD", flags)
                self.assertEqual((source / "bsd/pthread/mido_pthread/kern/mido_pthread_kern_init.c").read_bytes(),
                                 b"native implementation\n")
                with self.assertRaisesRegex(ValueError, "already staged"):
                    stage_pthread(source, workspace)

    def test_dependency_gate_runs_before_any_build(self):
        with self.assertRaisesRegex(ValueError, "explicit diagnostic platform"):
            check(Path("unused"), "iphoneos", experimental_pthread=True)

    def test_registration_is_original_and_does_not_replace_bsd_init(self):
        wrapper = (ROOT / "devices/mido/xnu/runtime/mido_pthread_startup.c").read_text()
        self.assertIn("pthread_start(NULL, NULL) != KERN_SUCCESS", wrapper)
        self.assertIn("STARTUP(THREAD_CALL, STARTUP_RANK_LAST, mido_pthread_startup)", wrapper)
        self.assertNotIn("pthread_init(", wrapper)


if __name__ == "__main__":
    unittest.main()
