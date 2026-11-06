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
        value["value"] & 3 == 1 and value["value"] & 0xf0000000 in (0, 0x20000000) and 1 <= value["polls"] <= 1000
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
    rates = re.findall(r"MIDO GPU RATE: GPLL0/2 HID=5 nominal=(\d+) polls=(\d+)", text)
    rate_results = re.findall(r"MIDO GPU RATE: result=(-?\d+)", text)
    rate_ack = bool(rates) and rates[-1][0] == "133330000" and 1 <= int(rates[-1][1]) <= 1000 and bool(rate_results) and rate_results[-1] == "1"
    supply_votes = {}
    for match in re.finditer(r"MIDO WIFI POWER: supply=(\d+) id=(\d+) set=(\d+) value=(\d+) result=(-?\d+)", text):
        index, number, selected, value, result = map(int, match.groups())
        supply_votes[(index, selected)] = (number, value, result)
    expected_supplies = {(index, selected): (number, value) for index, number, value, sets in
                         ((0, 7, 384, 1), (1, 2, 256, 3), (2, 5, 1800000, 3),
                          (3, 7, 1800000, 3), (4, 19, 1300000, 3), (5, 9, 3300000, 3))
                         for selected in range(2) if sets & (1 << selected)}
    power_results = re.findall(r"MIDO WIFI POWER: result=(-?\d+) shared-cx-floor=(\d+)", text)
    supplies_ack = set(supply_votes) == set(expected_supplies) and all(
        supply_votes[key][0] == expected[0] and supply_votes[key][2] == 0 and
        (supply_votes[key][1] in (256, 320, 384) if key[0] == 1 else supply_votes[key][1] == expected[1])
        for key, expected in expected_supplies.items())
    power_ack = supplies_ack and bool(power_results) and power_results[-1][0] == "1" and int(power_results[-1][1]) in (256, 320, 384) and "MIDO WIFI POWER: supplies/XO acknowledged;" in text
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
            "gpu_nominal_133mhz_selection_acknowledged": rate_ack,
            "wifi_supplies_xo_acknowledged": power_ack,
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
