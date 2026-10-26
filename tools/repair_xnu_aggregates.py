"""Preserve implicit zero defaults in reviewed, prepared-source aggregates."""

import hashlib
import re


SOURCE_HASHES = {
    "osfmk/kern/kalloc.h": "caf896f8572f6867f753568a00b829a5053f3b2d9f3731a490e41017067868b7",
    "iokit/Kernel/IOSimpleReporter.cpp": "315f65a3d2db8677d678c0e0388418544f28b07ba3fd24718fe5d34512f554eb",
    "iokit/Kernel/IOStateReporter.cpp": "f4a2c3be38f43db3f93e9294ca68c8dbf521703b0bde5196bbd5e402ff6ef864",
    "iokit/Kernel/IOHistogramReporter.cpp": "ba9cba8610c0d962f559ba9ce22130bb6661a99ff29f0ebefc28bfa7fd5e992c",
    "osfmk/kern/zalloc.h": "883e8219afcf75100c0712ed88f4d656b1d03215b0d21234ca6c9bb9baf8e1a9",
    "iokit/Kernel/IOUserServer.cpp": "ae9be112e4b0b1acc841ea0245b1790b0fda477d21b65ebc873058b9188e5a70",
    "iokit/Kernel/IOPMrootDomain.cpp": "f53bbe5583027d1a7fe51f19702c610f700f86ae3ec3a6415fe29511d202c23e",
    "iokit/Kernel/IOPerfControl.cpp": "0852339c1adfb30352d94376b373a86aece8c822ea962b3b075630b24984dcab",
}


def repair_allocation_site(data):
    original = b"static vm_allocation_site_t site = { .refcount = 2, };"
    marker = b"#define VM_ALLOC_SITE_TAG() ({ " + bytes((92,)) + b"\n"
    if data.count(original) != 1 or data.count(marker) != 1:
        raise ValueError("unexpected allocation site initializer")
    prefix = (b"#if DEBUG || DEVELOPMENT\n"
              b"#define VM_ALLOC_SITE_PEAK_INITIALIZER .peak = 0,\n"
              b"#else\n#define VM_ALLOC_SITE_PEAK_INITIALIZER\n#endif\n"
              b"#ifdef __cplusplus\n"
              b"#define VM_ALLOC_SITE_SUBTOTALS_INITIALIZER .subtotals = {},\n"
              b"#else\n#define VM_ALLOC_SITE_SUBTOTALS_INITIALIZER\n#endif\n\n")
    replacement = (b"static vm_allocation_site_t site = { .total = 0, "
                   b"VM_ALLOC_SITE_PEAK_INITIALIZER .mapped = 0, .refcount = 2, "
                   b".tag = 0, .flags = 0, .subtotalscount = 0, "
                   b"VM_ALLOC_SITE_SUBTOTALS_INITIALIZER };")
    return data.replace(marker, prefix + marker).replace(original, replacement)


def repair_power_states(data, marker, count):
    if data.count(marker) != 1:
        raise ValueError("unexpected power state table")
    start = data.index(marker)
    end = data.index(b"\n};", start)
    block = data[start:end]
    defaults = (b", .staticPower = 0, .stateOrder = 0, .powerToAttain = 0, "
                b".timeToAttain = 0, .settleUpTime = 0, .timeToLower = 0, "
                b".settleDownTime = 0, .powerDomainBudget = 0")
    block, changed = re.subn(rb"(\.inputPowerRequirement\s*=\s*[^,\n{}]+?)(\s*})",
                            lambda match: match[1] + defaults + match[2], block)
    if changed != count:
        raise ValueError("unexpected power state initializer count")
    return data[:start] + block + data[end:]


def repair_perf_control(data):
    marker = b"\t\t};\n\n\t\tshared->interfaceLock = IOLockAlloc();"
    if data.count(marker) != 1:
        raise ValueError("unexpected performance interface initializer")
    data = data.replace(marker, b"\t\t\t.registerDriverDevice = nullptr,\n"
                        b"\t\t\t.unregisterDriverDevice = nullptr,\n" + marker)
    missing_started = 0

    def defaults(match):
        nonlocal missing_started
        block = match[0]
        driver = b".driver_state = &clientData.driverState"
        if block.count(driver) != 1 or b".reserved" in block:
            raise ValueError("unexpected work state initializer")
        prefix = b".reserved = 0,\n\t\t"
        if b".started" not in block:
            missing_started += 1
            prefix = b".started = false,\n\t\t" + prefix
        return block.replace(driver, prefix + driver)

    data, changed = re.subn(rb"PerfControllerInterface::WorkState state\{[^{}]+\};", defaults, data)
    if changed != 9 or missing_started != 1:
        raise ValueError("unexpected performance work state counts")
    return data


def repair_heap_view(data):
    marker = b"#define KALLOC_HEAP_DEFINE(var, name, heap_id) "
    if data.count(marker) != 1:
        raise ValueError("unexpected heap view macro")
    start = data.index(marker)
    end = data.index(b"\n\n", start)
    block = data[start:end]
    before_name = b"    .kh_name = (name),"
    after_heap_id = b"    .kh_heap_id = (heap_id),"
    if (block.count(before_name) != 1 or block.count(after_heap_id) != 1
            or b".kh_stats" in block or b".kh_views" in block):
        raise ValueError("unexpected heap view initializer")
    continuation = bytes((32, 92, 10, 9))
    block = block.replace(before_name, b"    .kh_stats = NULL," + continuation + before_name)
    defaults = continuation.join((b"    .kh_tag = 0,", b"    .kh_type_hash = 0,",
                                  b"    .kh_zstart = 0,", b"    .kh_views = NULL,"))
    block = block.replace(after_heap_id, after_heap_id + continuation + defaults)
    return data[:start] + block + data[end:]


def repair_report_channels(data):
    def defaults(match):
        block = match[0]
        marker = b".report_format = "
        if block.count(marker) != 1 or b".reserved" in block:
            raise ValueError("unexpected report channel initializer")
        end = block.index(b"\n", block.index(marker))
        return block[:end] + b"\n\t\t.reserved = 0," + block[end:]

    result, changed = re.subn(rb"IOReportChannelType channelType = \{[^{}]+\};", defaults, data)
    if changed != 2:
        raise ValueError("unexpected report channel initializer count")
    return result


def repair_aggregate(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected aggregate repair source: " + relative)
    if relative == "osfmk/kern/kalloc.h":
        return repair_heap_view(data)
    if relative in ("iokit/Kernel/IOSimpleReporter.cpp", "iokit/Kernel/IOStateReporter.cpp",
                    "iokit/Kernel/IOHistogramReporter.cpp"):
        return repair_report_channels(data)
    if relative == "osfmk/kern/zalloc.h":
        return repair_allocation_site(data)
    if relative == "iokit/Kernel/IOPerfControl.cpp":
        return repair_perf_control(data)
    if relative == "iokit/Kernel/IOUserServer.cpp":
        return repair_power_states(data, b"    sPowerStates[] = {", 3)
    return repair_power_states(data, b"    ourPowerStates[NUM_POWER_STATES] =", 5)


def stage_aggregate_repairs(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_aggregate(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
