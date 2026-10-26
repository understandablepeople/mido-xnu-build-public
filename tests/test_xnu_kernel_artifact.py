from pathlib import Path
import tempfile
import unittest

from tools.check_xnu_build import save_kernel_artifact


class KernelArtifactTests(unittest.TestCase):
    def test_unstripped_output_is_retained_when_final_output_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build = output / "build"
            kernel = build / "obj/DEVELOPMENT_ARM64_MIDO/mach.development.mido.unstripped"
            kernel.parent.mkdir(parents=True)
            kernel.write_bytes(b"synthetic unstripped fixture")
            report = save_kernel_artifact(build, output, "iphoneos")
            self.assertEqual(Path(report["path"]).name, kernel.name)
            self.assertEqual(Path(report["path"]).read_bytes(), kernel.read_bytes())
            self.assertFalse(report["boot_approved"])

    def test_successful_make_output_is_copied_without_boot_approval(self):
        for sdk, name in (("iphoneos", "mach"), ("macosx", "kernel")):
            with self.subTest(sdk=sdk), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                build = output / "build"
                kernel = build / f"obj/DEVELOPMENT_ARM64_MIDO/{name}.development.mido"
                kernel.parent.mkdir(parents=True)
                kernel.write_bytes(b"synthetic copy fixture, not a linked kernel")
                report = save_kernel_artifact(build, output, sdk)
                self.assertEqual(Path(report["path"]).read_bytes(), kernel.read_bytes())
                self.assertFalse(report["boot_approved"])
                self.assertFalse(report["platform_memory_approved"])
                with self.assertRaisesRegex(ValueError, "existing"):
                    save_kernel_artifact(build, output, sdk)

    def test_missing_or_empty_output_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build = output / "build"
            with self.assertRaisesRegex(ValueError, "missing"):
                save_kernel_artifact(build, output, "iphoneos")
            kernel = build / "obj/DEVELOPMENT_ARM64_MIDO/mach.development.mido"
            kernel.parent.mkdir(parents=True)
            kernel.touch()
            with self.assertRaisesRegex(ValueError, "empty"):
                save_kernel_artifact(build, output, "iphoneos")
            self.assertFalse((output / kernel.name).exists())


if __name__ == "__main__":
    unittest.main()
