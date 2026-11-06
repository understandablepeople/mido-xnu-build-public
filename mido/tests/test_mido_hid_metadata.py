from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
RELATIVE = "iokit/Kernel/arm/hid/MidoHID.cpp"


class HIDMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = (ROOT / "xnu/patches/0058-mido-hid-event-services.patch").read_text(encoding="utf-8", errors="replace")
        section = base.split("+++ b/" + RELATIVE + "\n", 1)[1].split("\n--- ", 1)[0]
        source = "\n".join(line[1:] for line in section.splitlines() if line.startswith("+")) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / RELATIVE
            target.parent.mkdir(parents=True)
            target.write_text(source)
            for name in ("0061-mido-iphone-x-display-size.patch",
                         "0106-mido-bgr24-scaled-display.patch",
                         "0107-mido-polled-input-battery.patch"):
                subprocess.run(["git", "apply", "--include=" + RELATIVE,
                                str(ROOT / "xnu/patches" / name)],
                               cwd=directory, capture_output=True, check=True)
            cls.before = target.read_text()
            subprocess.run(["git", "apply", str(ROOT / "xnu/patches/0114-mido-hid-built-in-display-events.patch")],
                           cwd=directory, capture_output=True, check=True)
            cls.after = target.read_text()

    def test_built_in_flag_is_set_before_client_dispatch(self):
        dispatch = self.after.split("IOHIDEventService::dispatchEvent(", 1)[1].split("IOHIDEventService::copyEvent(", 1)[0]
        self.assertIn("event->setIntegerValue(kIOHIDEventFieldIsBuiltIn, TRUE);", dispatch)
        self.assertLess(dispatch.index("kIOHIDEventFieldIsBuiltIn"), dispatch.index("event->setSenderID"))
        self.assertLess(dispatch.index("kIOHIDEventFieldIsBuiltIn"), dispatch.index("(*data->action)"))

    def test_collection_and_children_identify_the_integrated_display(self):
        touch = self.after.split("MidoHIDTouch::touch(", 1)[1]
        self.assertIn("collection->setIntegerValue(kIOHIDEventFieldDigitizerIsDisplayIntegrated, TRUE);", touch)
        self.assertIn("child->setIntegerValue(kIOHIDEventFieldDigitizerIsDisplayIntegrated, TRUE);", touch)
        self.assertIn("child->setIntegerValue(kIOHIDEventFieldIsBuiltIn, TRUE);", touch)
        self.assertLess(touch.index("child->setIntegerValue(kIOHIDEventFieldIsBuiltIn"),
                        touch.index("collection->appendChild(child)"))
        self.assertLess(touch.index("collection->setIntegerValue(kIOHIDEventFieldDigitizerIsDisplayIntegrated"),
                        touch.index("dispatchEvent(collection)"))

    def test_only_metadata_and_registration_marker_change(self):
        restored = self.after
        for line in ("\tevent->setIntegerValue(kIOHIDEventFieldIsBuiltIn, TRUE);\n",
                     "\tcollection->setIntegerValue(kIOHIDEventFieldDigitizerIsDisplayIntegrated, TRUE);\n",
                     "\t\tchild->setIntegerValue(kIOHIDEventFieldIsBuiltIn, TRUE);\n",
                     "\t\tchild->setIntegerValue(kIOHIDEventFieldDigitizerIsDisplayIntegrated, TRUE);\n"):
            self.assertEqual(restored.count(line), 1)
            restored = restored.replace(line, "")
        restored = restored.replace("touch registered (built-in display events)", "touch registered")
        self.assertEqual(restored, self.before)


if __name__ == "__main__":
    unittest.main()
