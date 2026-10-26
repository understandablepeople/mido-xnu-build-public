import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_platform_gates import (SOURCE_HASHES, repair_bank_telemetry,
                                            repair_platform_gates, repair_pmap_apple_dma,
                                            repair_task_kpc, repair_zone_logging,
                                            stage_platform_gates, repair_pmap_visibility)


def pmap_visibility_fixture():
    return (b"static bool alloc_asid(pmap_t pmap);\n"
            b"MARK_AS_PMAP_TEXT static inline void\npmap_cs_lockdown_pages(vm_address_t kva, vm_size_t size, bool ppl_writable)\n"
            b"{\n#if XNU_MONITOR\n\tpmap_ppl_lockdown_pages(kva, size, PVH_FLAG_LOCKDOWN_CS, ppl_writable);\n"
            b"#else\n\tpmap_ppl_lockdown_pages(kva, size, 0, ppl_writable);\n#endif\n}\n"
            b"MARK_AS_PMAP_TEXT static inline void\npmap_cs_unlockdown_pages(vm_address_t kva, vm_size_t size, bool ppl_writable)\n"
            b"{\n#if XNU_MONITOR\n\tpmap_ppl_unlockdown_pages(kva, size, PVH_FLAG_LOCKDOWN_CS, ppl_writable);\n"
            b"#else\n\tpmap_ppl_unlockdown_pages(kva, size, 0, ppl_writable);\n#endif\n}\n"
            b"MARK_AS_PMAP_TEXT static void\npmap_phys_write_disable(vm_address_t va)\n{ protect(va); }\n"
            b'\tpanic("pmap_page_protect: ppnum 0x%x locked down, cannot be owned by iommu %p, pve_p=%p",\n'
            b"\t    ppnum, ptep_get_iommu(pte_p), pve_p);\n"
            b'\tpanic("pmap_page_protect: attempt to compress ppnum 0x%x owned by iommu %p, pve_p=%p",\n'
            b"\t    ppnum, ptep_get_iommu(pte_p), pve_p);\n")


class PlatformGateTests(unittest.TestCase):
    def test_pmap_declaration_and_unused_code_signing_gate_preserve_implementation(self):
        original = pmap_visibility_fixture()
        result = repair_pmap_visibility(original)
        self.assertEqual(result.count(b"static void pmap_phys_write_disable(vm_address_t va);"), 1)
        self.assertIn(b"#if PMAP_CS_PPL_MONITOR || PMAP_CS_INCLUDE_CODE_SIGNING\n", result)
        first = original.index(b"MARK_AS_PMAP_TEXT static inline void")
        last = original.index(b"MARK_AS_PMAP_TEXT static void\npmap_phys_write_disable")
        self.assertIn(original[first:last], result)
        self.assertIn(b"{ protect(va); }", result)

    def test_pmap_iommu_diagnostics_preserve_original_and_identify_raw_pointer(self):
        original = pmap_visibility_fixture()
        result = repair_pmap_visibility(original)
        self.assertEqual(result.count(b"#if defined(MIDO)\n"), 2)
        self.assertEqual(result.count(b"ptep_get_iommu(pte_p)"), 2)
        self.assertEqual(result.count(b"owned by iommu ptep %p"), 2)
        self.assertEqual(result.count(b"ppnum, pte_p, pve_p);"), 2)
        self.assertEqual(result.count(b"panic("), 4)

    def test_pmap_visibility_rejects_changed_or_duplicate_layout(self):
        original = pmap_visibility_fixture()
        for invalid in (original + original, original.replace(b"static bool alloc_asid", b"static bool changed"),
                        original.replace(b"pmap_phys_write_disable(vm_address_t va)", b"changed(vm_address_t va)"),
                        original.replace(b"pmap_cs_lockdown_pages(", b"changed("),
                        original.replace(b"ptep_get_iommu(pte_p)", b"changed(pte_p)")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                repair_pmap_visibility(invalid)

    def test_all_sources_reject_unpinned_data(self):
        self.assertEqual(len(SOURCE_HASHES), 5)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "platform gate source"):
                repair_platform_gates(relative, b"unreviewed")

    def test_only_apple_dma_references_are_excluded_for_mido(self):
        data = (b"#include <arm64/ppl/sart.h>\n#include <arm64/ppl/uat.h>\n"
                b"pmap_data_bootstrap();\n\tuat_bootstrap();\n\tsart_bootstrap();\n"
                b"avail_start = aligned;\n")
        result = repair_pmap_apple_dma(data)
        self.assertEqual(result.count(b"#if !defined(MIDO)\n"), 4)
        self.assertEqual(result.replace(b"#if !defined(MIDO)\n", b"").replace(b"#endif\n", b""), data)
        self.assertNotIn(b"#else", result)
        with self.assertRaisesRegex(ValueError, "DMA bootstrap layout"):
            repair_pmap_apple_dma(data + data)

    def test_task_kpc_guard_preserves_other_initializers(self):
        data = b"before();\n\tnew_task->t_kpc = 0;\nafter();\n"
        result = repair_task_kpc(data)
        self.assertEqual(result, b"before();\n#if KPC\n\tnew_task->t_kpc = 0;\n#endif\nafter();\n")
        for invalid in (b"", data + data):
            with self.assertRaisesRegex(ValueError, "KPC initializer"):
                repair_task_kpc(invalid)

    def test_bank_telemetry_guards_match_field_without_changing_fallback(self):
        data = (b"#if CONFIG_COALITIONS\n"
                b"\tcoalition_t rsrc_coal = task->coalition[COALITION_TYPE_RESOURCE];\n"
                b"\tnew_bank_task->bt_rsrc_coal_id = rsrc_coal != COALITION_NULL ? coalition_id(rsrc_coal) : 0;\n"
                b"#endif\n"
                b"bank_get_bank_account_holder_resource_coalition_id(bank_account_t bank_account __unused)\n"
                b"{\n#if CONFIG_COALITIONS\nreturn bank_task->bt_rsrc_coal_id;\n#endif\nreturn 0;\n}\n")
        result = repair_bank_telemetry(data)
        self.assertEqual(result.count(b"#if CONFIG_COALITIONS && CONFIG_TELEMETRY\n"), 2)
        self.assertEqual(result.replace(b" && CONFIG_TELEMETRY", b""), data)
        for invalid in (data + data, result):
            with self.assertRaisesRegex(ValueError, "telemetry field guard"):
                repair_bank_telemetry(invalid)

    def test_zone_flag_typo_is_corrected_without_changing_flag_policy(self):
        for count in (1, 2):
            data = b"#define ZALLOC_ENABLE_LOGGING 1\n" + b"ZONE_ENABLE_LOGGING\n" * count
            result = repair_zone_logging(data, count)
            self.assertEqual(result, data.replace(b"ZONE_ENABLE_LOGGING", b"ZALLOC_ENABLE_LOGGING"))
            with self.assertRaisesRegex(ValueError, "logging flag layout"):
                repair_zone_logging(data, count + 1)

    def test_staging_validates_every_source_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            profiles = {relative: hashlib.sha256(b"original").hexdigest()
                        for relative in ("first.c", "second.c")}
            with patch.dict(SOURCE_HASHES, profiles, clear=True):
                with patch("tools.repair_xnu_platform_gates.repair_platform_gates",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaisesRegex(ValueError, "bad source"):
                        stage_platform_gates(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
