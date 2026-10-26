import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.prepare_xnu_availability import SCRIPT_LIMIT, prepare_availability, validate_inputs


class AvailabilityPreparationTests(unittest.TestCase):
    def test_changed_script_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "script size or SHA-256"):
            validate_inputs(b"exit 0", b"alias")

    def test_oversize_script_is_rejected_even_if_digest_matches(self):
        script = b"a" * (SCRIPT_LIMIT + 1)
        with patch("tools.prepare_xnu_availability.SCRIPT_SHA256", hashlib.sha256(script).hexdigest()):
            with self.assertRaisesRegex(ValueError, "script size or SHA-256"):
                validate_inputs(script, b"alias")

    def test_changed_xnu_generator_is_rejected(self):
        script = b"synthetic script"
        with patch("tools.prepare_xnu_availability.SCRIPT_SHA256", hashlib.sha256(script).hexdigest()):
            with self.assertRaisesRegex(ValueError, "original XNU"):
                validate_inputs(script, b"altered generator")

    def test_matching_synthetic_hashes_are_accepted(self):
        script, alias = b"synthetic script", b"synthetic generator"
        with patch("tools.prepare_xnu_availability.SCRIPT_SHA256", hashlib.sha256(script).hexdigest()), \
                patch("tools.prepare_xnu_availability.ALIAS_SHA256", hashlib.sha256(alias).hexdigest()):
            validate_inputs(script, alias)

    def test_outside_artifacts_rejected_before_download_or_git(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch("tools.prepare_xnu_availability.urllib.request.urlopen") as download, \
                patch("tools.prepare_xnu_availability.subprocess.run") as git:
            with self.assertRaisesRegex(ValueError, "inside workspace artifacts"):
                prepare_availability(Path(temporary))
            download.assert_not_called()
            git.assert_not_called()

    def test_artifacts_root_is_not_a_dependency_output(self):
        artifacts = Path(__file__).resolve().parent.parent / "artifacts"
        with self.assertRaisesRegex(ValueError, "inside workspace artifacts"):
            prepare_availability(artifacts)


if __name__ == "__main__":
    unittest.main()
