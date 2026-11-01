import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from tools.mido_vm_ttbr1_carrier_config import (
    ISLAND_SHA256, MAGIC, RECORD, build_island, configure_ttbr1_carrier)
from tools.mido_vm_physmap_carrier_config import configure_physmap_carrier
from tools.mido_vm_transition_island import transition_island, _select_padding, _b26_reachable


class TTBR1CarrierConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        kernel = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", root /
            "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        cls.kernel = kernel.read_bytes()
        cls.toolchain = Path.home() / "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin"
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.payload, cls.symbols = build_island(cls.kernel,cls.toolchain,Path(cls.temporary.name)/"island")

    def baseline(self):
        review = {"values":{"MIDO_EARLY_VIRT_BASE":0xfffffff007000000,"MIDO_EARLY_STOP_PA":0},
                  "post_c_definitions":{"MIDO_C_RECORD":0x12400800,"MIDO_C_RETURN_LITERAL":0x850},
                  "vm_dynamic":True,"boot_approved":False}
        return configure_physmap_carrier(self.kernel,"#define UNRELATED 7\n",review)

    def test_compiled_payload_is_pinned_and_within_section_free_padding(self):
        island = transition_island(self.kernel)
        self.assertTrue(island["found"])
        candidate = island["candidate"]
        self.assertEqual(candidate["va"],0xfffffff007b4ff00)
        self.assertEqual(candidate["budget"],256)
        self.assertEqual(len(self.payload),212)
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(),ISLAND_SHA256)
        self.assertEqual(self.kernel[candidate["fileoff"]:candidate["fileoff"]+256],bytes(256))
        self.assertGreaterEqual(candidate["va"],island["final_section_end_va"])
        self.assertTrue(candidate["b26_reachable"])

    def test_exact_stop_record_and_mapping_contract(self):
        header,review = self.baseline()
        result,extended = configure_ttbr1_carrier(self.kernel,header,review,self.payload,self.symbols)
        self.assertEqual(extended["stop_va"],0xfffffff007446a38)
        self.assertEqual(extended["original_stop_word"],0x90ffe8f4)
        self.assertEqual(extended["ttbr1_record"],dict(physical=RECORD,words=9,magic=MAGIC))
        self.assertFalse(extended["full_activation"])
        self.assertEqual(len(extended["transition_mapping_audits"]),3)
        self.assertIn("#define MIDO_VM_TTBR1_ROUNDTRIP 0x1ULL",result)
        self.assertIn("#define MIDO_VM_PROTECTION_SPANS ",result)
        self.assertIn("#define UNRELATED 7",result)
        self.assertEqual(extended["post_c_definitions"]["MIDO_C_RECORD"],review["post_c_definitions"]["MIDO_C_RECORD"])
        self.assertEqual(review["stop_va"],0xfffffff007446a34)
        self.assertEqual(configure_ttbr1_carrier(self.kernel,result,extended,self.payload,self.symbols),(result,extended))

    def test_explicit_prefix_is_required(self):
        header,review = self.baseline()
        for flag in ("vm_dynamic","vm_physmap_complete"):
            candidate = dict(review,**{flag:False})
            with self.assertRaisesRegex(ValueError,"explicit complete"):
                configure_ttbr1_carrier(self.kernel,header,candidate,self.payload,self.symbols)

    def test_modified_payload_and_each_label_are_rejected(self):
        header,review = self.baseline()
        for offset in (0,76,156,len(self.payload)-1):
            candidate = bytearray(self.payload)
            candidate[offset] ^= 1
            with self.assertRaisesRegex(ValueError,"layout"):
                configure_ttbr1_carrier(self.kernel,header,review,bytes(candidate),self.symbols)
        for name in self.symbols:
            symbols = dict(self.symbols)
            symbols[name] += 4
            with self.assertRaises(ValueError):
                configure_ttbr1_carrier(self.kernel,header,review,self.payload,symbols)

    def test_unknown_kernel_and_padding_modification_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"exact reviewed"):
            transition_island(b"unknown")
        candidate = bytearray(self.kernel)
        candidate[transition_island(self.kernel)["candidate"]["fileoff"]] ^= 1
        with self.assertRaisesRegex(ValueError,"exact reviewed"):
            transition_island(bytes(candidate))

    def test_padding_selector_and_branch_boundaries(self):
        self.assertEqual(_select_padding(0x1001,0x2100),(0x2000,0x100))
        self.assertIsNone(_select_padding(0x1001,0x107f))
        self.assertEqual(_select_padding(0x1fff,0x2080),(0x2000,128))
        self.assertTrue(_b26_reachable(0x10000000,0x08000000))
        self.assertTrue(_b26_reachable(0x10000000,0x17fffffc))
        self.assertFalse(_b26_reachable(0x10000000,0x18000000))
        self.assertFalse(_b26_reachable(0x10000000,0x10000001))
