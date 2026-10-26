"""Inspect the saved mido interrupt topology; never access device registers."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

try:
    from tools.inspect_boot import parse_fdt
except ModuleNotFoundError:
    from inspect_boot import parse_fdt


def cells(value, count):
    if not isinstance(value, bytes) or len(value) != 4 * count:
        raise ValueError("unexpected DT cell count")
    return struct.unpack(f">{count}I", value)


def strings(value):
    if not value or not value.endswith(b"\0"):
        raise ValueError("unterminated DT string list")
    return value[:-1].decode("ascii").split("\0")


def inspect_nodes(nodes):
    if "qcom,msm8953" not in strings(nodes.get("/", {}).get("compatible", b"")):
        raise ValueError("expected the MSM8953 device family")
    phandles = {}
    for path, props in nodes.items():
        identifiers = [cells(props[name], 1)[0] for name in ("phandle", "linux,phandle") if name in props]
        if identifiers and (len(set(identifiers)) != 1 or identifiers[0] in (0, 0xFFFFFFFF)):
            raise ValueError("invalid or inconsistent phandle")
        if identifiers:
            identifier = identifiers[0]
            if identifier in phandles:
                raise ValueError("duplicate phandle")
            phandles[identifier] = path
    timers = [path for path, props in nodes.items() if "compatible" in props and "arm,armv8-timer" in strings(props["compatible"])]
    if len(timers) != 1:
        raise ValueError("expected exactly one architectural timer")
    timer = timers[0]

    def parent_of(path):
        current = path
        while True:
            if "interrupt-parent" in nodes.get(current, {}):
                identifier = cells(nodes[current]["interrupt-parent"], 1)[0]
                if identifier not in phandles:
                    raise ValueError("unresolved interrupt parent")
                return phandles[identifier]
            if current == "/":
                raise ValueError("missing interrupt parent")
            current = current.rsplit("/", 1)[0] or "/"

    route = []
    current = parent_of(timer)
    while True:
        if current in route:
            raise ValueError("interrupt parent cycle")
        route.append(current)
        props = nodes[current]
        if cells(props.get("#interrupt-cells"), 1)[0] != 3 or "interrupt-map" in props:
            raise ValueError("unsupported interrupt translation")
        compatible = strings(props.get("compatible", b""))
        if "qcom,msm-qgic2" in compatible:
            controller = current
            break
        if "qcom,mpm-gic" not in compatible:
            raise ValueError("unreviewed intermediate interrupt controller")
        current = parent_of(current)
    for path in [timer, *route]:
        if nodes[path].get("status", b"okay\0") not in (b"okay\0", b"ok\0"):
            raise ValueError("disabled timer or interrupt controller")
    timer_props = nodes[timer]
    values = cells(timer_props.get("interrupts"), 12)
    if "interrupt-names" in timer_props and strings(timer_props["interrupt-names"]) != ["sec-phys", "phys", "virt", "hyp-phys"]:
        raise ValueError("unreviewed timer interrupt order")
    frequency = cells(timer_props.get("clock-frequency"), 1)[0]
    if not frequency:
        raise ValueError("zero timer frequency")
    interrupts = []
    for index, name in enumerate(("secure-physical", "nonsecure-physical", "virtual", "hypervisor")):
        kind, number, flags = values[index * 3:index * 3 + 3]
        if kind != 1 or number >= 16 or flags & ~0xFF0F or flags & 15 not in (4, 8):
            raise ValueError("expected level-triggered PPI timer specifiers")
        interrupts.append({"name": name, "ppi_index": number, "gic_intid_candidate": 16 + number, "flags": flags})
    if controller.rsplit("/", 1)[0] != "/soc" or cells(nodes["/soc"].get("#address-cells"), 1) != (1,) or cells(nodes["/soc"].get("#size-cells"), 1) != (1,):
        raise ValueError("unreviewed GIC bus layout")
    if cells(nodes["/"].get("#address-cells"), 1) != (2,) or nodes["/soc"].get("ranges") != struct.pack(">4I", 0, 0, 0, 0xFFFFFFFF):
        raise ValueError("unreviewed GIC bus translation")
    distributor, distributor_size, cpu, cpu_size = cells(nodes[controller].get("reg"), 4)
    for base, size in ((distributor, distributor_size), (cpu, cpu_size)):
        if base & 4095 or size < 4096 or base + size > 0xFFFFFFFF:
            raise ValueError("invalid GIC register window")
    if distributor < cpu + cpu_size and cpu < distributor + distributor_size:
        raise ValueError("overlapping GIC register windows")
    return {
        "purpose": "saved DT topology inspection, not hardware IRQ validation",
        "timer_path": timer, "parent_route": route, "gic_path": controller,
        "distributor": {"physical_base": distributor, "size": distributor_size},
        "cpu_interface": {"physical_base": cpu, "size": cpu_size},
        "dt_frequency_hz": frequency, "timer_interrupts": interrupts,
        "virtual_timer_intid_candidate": interrupts[2]["gic_intid_candidate"],
        "mpm_passthrough_reference": "LineageOS/android_kernel_xiaomi_msm8953@0ac2c6831eabb90d18f49081bc2221a715763e50 drivers/irqchip/qcom/mpm.c",
        "hardware_route_verified": False, "boot_approved": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    data = args.dtb.read_bytes()
    result = inspect_nodes(parse_fdt(data)["nodes"])
    result["dtb_sha256"] = hashlib.sha256(data).hexdigest()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
