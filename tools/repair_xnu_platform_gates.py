"""Review-gated field conditions and exclusion of Apple-only DMA bootstraps."""

import hashlib
import re


SOURCE_HASHES = {
    "osfmk/arm/pmap/pmap.c": "78cdd8a97fae341dd2b757c8def4799e824f56e79ccb8d1b654f92cd6c78e375",
    "osfmk/kern/task.c": "67d88c279b1d2174f6d85f952fadfd698419a4d6e8537134a6e25bf912019289",
    "osfmk/bank/bank.c": "c54f3de8958cb7ba0b58780f0343ff6f3790027c6de5d7b27ae9ce99c86c984e",
    "osfmk/kern/zalloc_internal.h": "0e2a9cb2bc7e90f873f586dcb43677b5f7154d9175eb7c52fb92fcd4691fc65b",
    "osfmk/kern/zalloc.c": "f7f13736ad7e6de9b8939bace558b25b80614e2565304d9b997d8342515860df",
}


def repair_pmap_apple_dma(data):
    for original in (b"#include <arm64/ppl/sart.h>\n", b"#include <arm64/ppl/uat.h>\n",
                     b"\tuat_bootstrap();\n", b"\tsart_bootstrap();\n"):
        if data.count(original) != 1:
            raise ValueError("unexpected Apple DMA bootstrap layout")
        data = data.replace(original, b"#if !defined(MIDO)\n" + original + b"#endif\n")
    return data


def repair_task_kpc(data):
    original = b"\tnew_task->t_kpc = 0;\n"
    if data.count(original) != 1:
        raise ValueError("unexpected task KPC initializer")
    return data.replace(original, b"#if KPC\n" + original + b"#endif\n")


def repair_pmap_visibility(data):
    declaration = b"static bool alloc_asid(pmap_t pmap);\n"
    definition = b"MARK_AS_PMAP_TEXT static void\npmap_phys_write_disable(vm_address_t va)\n"
    if data.count(declaration) != 1 or data.count(definition) != 1:
        raise ValueError("unexpected pmap physical protection declaration layout")
    data = data.replace(declaration,
                        b"MARK_AS_PMAP_TEXT static void pmap_phys_write_disable(vm_address_t va);\n" + declaration)
    start = b"MARK_AS_PMAP_TEXT static inline void\npmap_cs_lockdown_pages("
    end = b"\tpmap_ppl_unlockdown_pages(kva, size, 0, ppl_writable);\n#endif\n}\n"
    if data.count(start) != 1 or data.count(end) != 1:
        raise ValueError("unexpected pmap code signing helper layout")
    first = data.index(start)
    last = data.index(end) + len(end)
    if last <= first:
        raise ValueError("unexpected pmap code signing helper order")
    data = (data[:first] + b"#if PMAP_CS_PPL_MONITOR || PMAP_CS_INCLUDE_CODE_SIGNING\n" +
            data[first:last] + b"#endif\n" + data[last:])
    pattern = (rb'(?P<indent>\t+)panic\("pmap_page_protect: [^\n]*owned by iommu %p, pve_p=%p",\n'
               rb'\s+ppnum, ptep_get_iommu\(pte_p\), pve_p\);\n')
    matches = list(re.finditer(pattern, data))
    if len(matches) != 2 or data.count(b"ptep_get_iommu(pte_p)") != 2:
        raise ValueError("unexpected pmap IOMMU panic diagnostics")
    for match in reversed(matches):
        original = match.group(0)
        diagnostic = original.replace(b"owned by iommu %p", b"owned by iommu ptep %p")
        diagnostic = diagnostic.replace(b"ptep_get_iommu(pte_p)", b"pte_p")
        data = (data[:match.start()] + b"#if defined(MIDO)\n" + diagnostic + b"#else\n" +
                original + b"#endif\n" + data[match.end():])
    return data


def repair_bank_telemetry(data):
    initializer = (b"#if CONFIG_COALITIONS\n"
                   b"\tcoalition_t rsrc_coal = task->coalition[COALITION_TYPE_RESOURCE];\n"
                   b"\tnew_bank_task->bt_rsrc_coal_id = rsrc_coal != COALITION_NULL ? coalition_id(rsrc_coal) : 0;\n")
    getter = (b"bank_get_bank_account_holder_resource_coalition_id(bank_account_t bank_account __unused)\n"
              b"{\n#if CONFIG_COALITIONS\n")
    for original in (initializer, getter):
        if data.count(original) != 1:
            raise ValueError("unexpected bank telemetry field guard")
        data = data.replace(original, original.replace(b"#if CONFIG_COALITIONS\n",
                            b"#if CONFIG_COALITIONS && CONFIG_TELEMETRY\n"))
    return data


def repair_zone_logging(data, expected):
    if data.count(b"ZONE_ENABLE_LOGGING") != expected:
        raise ValueError("unexpected zone logging flag layout")
    return data.replace(b"ZONE_ENABLE_LOGGING", b"ZALLOC_ENABLE_LOGGING")


def repair_platform_gates(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected platform gate source: " + relative)
    if relative == "osfmk/arm/pmap/pmap.c":
        return repair_pmap_visibility(repair_pmap_apple_dma(data))
    if relative == "osfmk/kern/task.c":
        return repair_task_kpc(data)
    if relative == "osfmk/bank/bank.c":
        return repair_bank_telemetry(data)
    return repair_zone_logging(data, 1 if relative.endswith(".h") else 2)


def stage_platform_gates(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_platform_gates(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
