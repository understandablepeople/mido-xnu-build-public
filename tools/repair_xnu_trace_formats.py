"""Repair pinned trace macros without changing policy decisions or warning flags."""

import hashlib


SOURCE_HASHES = {
    "bsd/net/necp.c": "cffdf00c4c91bb94f5067244a15ef336bfd04da7ceb8a44aa2f718f7978c7fff",
    "osfmk/kern/core_analytics.c": "2c3fb28d922d084def5c0715c18963dc7be13fe9cc825e32a9899f0c8aee11f9",
}
TRACE_MACROS = ("SOCKET", "SOCKET_RESULT", "IP", "IP_RESULT", "POLICY", "CONDITION3")


def macro_bounds(data, name):
    prefix = b"#define NECP_DATA_TRACE_LOG_" + name.encode("ascii") + b"("
    lines = data.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError("unexpected NECP trace macro: " + name)
    first = matches[0]
    last = first
    while lines[last].rstrip(b"\r\n").endswith(b"\\"):
        last += 1
        if last >= len(lines):
            raise ValueError("unterminated NECP trace macro")
    return sum(map(len, lines[:first])), sum(map(len, lines[:last + 1]))


def replace_once(data, original, replacement):
    if data.count(original) != 1:
        raise ValueError("unexpected NECP trace expression")
    return data.replace(original, replacement)


def integer_check(expression):
    expression = expression.encode("ascii")
    return (b"    _Static_assert(__builtin_classify_type(+(" + expression + b")) == 1 && "
            b"sizeof(+(" + expression + b")) <= sizeof(unsigned int), "
            b'"NECP trace requires <=32-bit integers"); \\\n')


def repair_trace_macro(name, data):
    if data.count(b"NECPDATATRACELOG(") != 1:
        raise ValueError("unexpected NECP trace logger count")
    if name in ("SOCKET", "SOCKET_RESULT", "IP", "IP_RESULT"):
        data = replace_once(data, b"drop-all order %d", b"drop-all order %u")
        data = replace_once(data, b"BoundInterface %d", b"BoundInterface %u")
    if name in ("SOCKET", "SOCKET_RESULT"):
        data = replace_once(data, b"Application %d Real Application %d", b"Application %u Real Application %u")
    if name in ("SOCKET_RESULT", "IP_RESULT", "POLICY"):
        data = replace_once(data, b"policy id=%d session_order=%d policy_order=%d",
                            b"policy id=%u session_order=%u policy_order=%u")
    if name == "SOCKET":
        data = replace_once(data, b"policy_id %d skip_policy_id %d", b"policy_id %u skip_policy_id %u")
        data = replace_once(data, b", policy_id, skip_policy_id);",
                            b", (unsigned int)(policy_id), (unsigned int)(skip_policy_id));")
        checks = integer_check("policy_id") + integer_check("skip_policy_id")
        data = replace_once(data, b"    NECPDATATRACELOG(", checks + b"    NECPDATATRACELOG(")
    elif name == "IP":
        data = replace_once(data, b"socket policy id %d socket skip id %d", b"socket policy id %u socket skip id %u")
    elif name == "POLICY":
        data = replace_once(data, b"cond_policy_id %d", b"cond_policy_id %u")
        data = replace_once(data, b"skip_session_order %d skip_order %d", b"skip_session_order %u skip_order %u")
    elif name == "CONDITION3":
        parameters = ("val1", "val2", "val3", "input1", "input2", "input3")
        original = b", " + b", ".join(parameter.encode("ascii") for parameter in parameters for repeat in range(2)) + b");"
        converted = b", " + b", ".join(
            (b"(" + primitive + b")(" + parameter.encode("ascii") + b")")
            for parameter in parameters for primitive in (b"int", b"unsigned int")) + b");"
        data = replace_once(data, original, converted)
        checks = b"".join(integer_check(parameter) for parameter in parameters)
        data = replace_once(data, b"    NECPDATATRACELOG(", checks + b"    NECPDATATRACELOG(")
    return data


def repair_necp_trace_formats(data):
    for name in TRACE_MACROS:
        first, last = macro_bounds(data, name)
        data = data[:first] + repair_trace_macro(name, data[first:last]) + data[last:]
    return data


def repair_analytics_queue_failure(data):
    original = (b'\t    "daemon.core-analytics-events", MPSC_DAEMON_INIT_NONE);\n')
    include = b"#include <kern/mpsc_queue.h>\n"
    if (data.count(original) != 1 or data.count(b"\tkern_return_t result;\n") != 1 or
            data.count(include) != 1 or b"#include <kern/debug.h>" in data):
        raise ValueError("unexpected analytics queue initialization")
    data = data.replace(include, b"#include <kern/debug.h>\n" + include)
    return data.replace(original, original + b"\tif (result != KERN_SUCCESS) {\n"
                        b'\t\tpanic("telemetry_init: core analytics daemon creation failed");\n\t}\n')


def repair_trace_formats(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected trace repair source: " + relative)
    if relative == "bsd/net/necp.c":
        return repair_necp_trace_formats(data)
    return repair_analytics_queue_failure(data)


def stage_trace_formats(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_trace_formats(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
