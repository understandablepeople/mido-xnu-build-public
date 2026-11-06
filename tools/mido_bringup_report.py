"""Summarize a fresh combined bring-up console without claiming working drivers."""

import argparse
import json
from pathlib import Path
import re


def summarize(text):
    branches = {}
    for match in re.finditer(r"MIDO GPU CLOCKS: branch=([0-9a-f]+) on=([0-9a-f]+) polls=(\d+)", text):
        branches[match[1]] = {"value": int(match[2], 16), "polls": int(match[3])}
    expected = {"59028", "59030", "59034", "59040", "59044", "59020"}
    clocks = re.findall(r"MIDO GPU CLOCKS: result=(-?\d+)", text)
    six_on = set(branches) == expected and all(
        value["value"] & 0x80000003 == 1 and 1 <= value["polls"] <= 1000
        for value in branches.values())
    clock_proof = six_on and bool(clocks) and clocks[-1] == "1"
    support = {}
    for match in re.finditer(r"MIDO SCM: PAS supported peripheral=(6|13) result=(-?\d+) supported=(\d+) smc64=(0|1)", text):
        support[match[1]] = {"transport_result": int(match[2]),
                            "supported": int(match[3]) if match[2] == "0" else None,
                            "smc64": match[4] == "1"}
    gpu = re.findall(r"MIDO GPU STATUS: rbbm=([0-9a-f]+) status3=([0-9a-f]+) ahb-error=([0-9a-f]+) vbif-version=([0-9a-f]+)", text)
    gpu_results = re.findall(r"MIDO GPU STATUS: result=(-?\d+)", text)
    status = dict(zip(("rbbm", "status3", "ahb_error", "vbif_version"),
                      (int(value, 16) for value in gpu[-1]))) if gpu else None
    gpu_proof = clock_proof and status is not None and status["vbif_version"] not in (0, 0xffffffff) and bool(gpu_results) and gpu_results[-1] == "1"
    wifi = re.findall(r"MIDO WIFI CLOCKS: crypto-root=([0-9a-f]+) cfg=([0-9a-f]+) core=([0-9a-f]+) bus=([0-9a-f]+) iface=([0-9a-f]+)", text)
    wifi_results = re.findall(r"MIDO WIFI CLOCKS: result=(-?\d+)", text)
    wifi_snapshot = dict(zip(("root", "config", "core", "bus", "iface"),
                             (int(value, 16) for value in wifi[-1]))) if wifi else None
    problems = []
    if not clock_proof:
        problems.append("GPU six-branch on proof incomplete or failed")
    if not gpu_proof:
        problems.append("GPU read-only status proof incomplete or failed")
    for peripheral in ("6", "13"):
        if peripheral not in support or support[peripheral]["transport_result"] != 0:
            problems.append("PAS" + peripheral + " support query missing or transport failed")
        elif not support[peripheral]["supported"]:
            problems.append("PAS" + peripheral + " reports unsupported")
    if not wifi_snapshot or not wifi_results or wifi_results[-1] != "1":
        problems.append("Wi-Fi clock snapshot incomplete or failed")
    return {"clock_branches": branches, "gpu_six_clocks_on": clock_proof,
            "gpu_registers": status, "gpu_readonly_probe_ok": gpu_proof,
            "pas_support": support, "wifi_clock_snapshot": wifi_snapshot,
            "issues": problems, "panic_text_present": "panic(cpu" in text or "SWEET EARLY PANIC:" in text,
            "gpu_acceleration_established": False, "wifi_network_established": False,
            "note": "Input must be a fresh single-boot pull; register reads/support are not working drivers."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.log.read_text(encoding="utf-8", errors="replace")), indent=2))


if __name__ == "__main__":
    main()
