"""Prepare an offline, hash-pinned OSObject RPC backport candidate; not boot approval."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


IMPLEMENTATION_SHA256 = "39d669f6a505167c6cc268baca4e29a99cea0c66c154358c4865837ab040c10a"
IORPC_SHA256 = "2876c631f84240faf655fad1c06d2fcec4abfd5b777c2d297cb0aaf0b8715c49"
BLOCK = re.compile(rb"(?m)^#ifdef KERNEL\n(.*?)^#endif /\* KERNEL \*/\n", re.S)


def unreviewed_legacy_candidate(implementation, header):
    if hashlib.sha256(header).hexdigest() != IORPC_SHA256:
        raise ValueError("unreviewed IORPC header")
    banner = re.match(rb"/\* iig\(DriverKit-286 Mar 29 2024 10:27:09\) generated from (\w+)\.iig \*/\n", implementation)
    if (banner is None or not 0 < len(implementation) <= 2 * 1024 * 1024 or
            b"kernelContent" in implementation or b"messageContent" in implementation or
            BLOCK.search(implementation)):
        raise ValueError("unreviewed OSObject implementation: not an eligible DriverKit-286 legacy output")
    unions = list(re.finditer(
        rb"typedef union\s*\{\s*const IORPC rpc;\s*struct\s*\{([^}]+)\};\s*}\s*(\w+)_Invocation;",
        implementation))
    assertions, count = invocation_assertions(implementation)
    if not unions or len(unions) != count:
        raise ValueError("unreviewed legacy invocation union")
    for union in unions:
        name = union[2]
        fields = (rb"\s*const struct " + re.escape(name) + rb"_Msg\s*\*\s*message;\s*"
                  rb"struct " + re.escape(name) + rb"_Rpl\s*\*\s*reply;\s*"
                  rb"uint32_t\s+sendSize;\s*uint32_t\s+replySize;\s*")
        if not name.startswith(banner[1] + b"_") or not re.fullmatch(fields, union[1]):
            raise ValueError("unreviewed legacy invocation fields")
        if not re.search(rb"struct " + re.escape(name) + rb"_Msg\s*\{[^}]*" +
                         re.escape(name) + rb"_Msg_Content\s+content;\s*};", implementation):
            raise ValueError("unreviewed legacy inline message")
    digest = hashlib.sha256(implementation).hexdigest()
    print("WARNING: unreviewed legacy IIG hash: " + banner[1].decode() + " sha256=" + digest +
          "; preserving actual implementation for diagnostic compilation only", file=sys.stderr)
    return implementation, {
        "input_sha256": digest, "output_sha256": digest,
        "iorpc_sha256": IORPC_SHA256, "hash_reviewed": False,
        "temporary_legacy_passthrough": True, "selected_legacy_branches": {},
        "ignored_oneway_return_declarations": 0, "invocation_unions_checked": count,
        "kernel_abi_modified": False, "boot_approved": False,
        "scope": "unreviewed unchanged DriverKit-286 output; structural checks only",
    }


def legacy_candidate(implementation, header, profile=None, allow_unreviewed_legacy=False):
    implementation = implementation.replace(b"\r\n", b"\n")
    header = header.replace(b"\r\n", b"\n")
    if profile:
        input_hash = hashlib.sha256(implementation).hexdigest()
        matches = [entry for entry in (profile, *profile.get("variants", []))
                   if entry["input_sha256"] == input_hash]
        if not matches and allow_unreviewed_legacy:
            return unreviewed_legacy_candidate(implementation, header)
        if len(matches) != 1:
            raise ValueError("unreviewed OSObject implementation")
        profile = matches[0]
    expected_input = profile["input_sha256"] if profile else IMPLEMENTATION_SHA256
    if hashlib.sha256(implementation).hexdigest() != expected_input:
        if allow_unreviewed_legacy:
            return unreviewed_legacy_candidate(implementation, header)
        raise ValueError("unreviewed OSObject implementation")
    if hashlib.sha256(header).hexdigest() != IORPC_SHA256:
        raise ValueError("unreviewed IORPC header")
    counts = Counter()

    def select_legacy(match):
        body = match[1]
        branches = body.split(b"#else /* KERNEL */\n")
        if len(branches) > 2 or b"#if" in body or b"#endif" in body:
            raise ValueError("unexpected nested RPC branch")
        kernel = branches[0]
        legacy = branches[1] if len(branches) == 2 else b""
        if b"kernelContent;" in kernel and not legacy:
            role = "invocation_field"
        elif b"#define MESSAGE_CONTENT" in kernel:
            role = "content_accessor"
        elif b"IORPCMessage * msg = rpc.kernelContent;" in kernel:
            role = "message_lookup"
        elif b".kernelContent = &buf.msg.content.__hdr" in kernel:
            role = "rpc_initializer"
        elif b"messageContent = rpc.kernelContent;" in kernel:
            role = "typed_message_lookup"
        elif b"_Msg * message;" in kernel:
            role = "invocation_message_type"
        elif b"message = rpc.kernelContent;" in kernel:
            role = "reply_lookup"
        elif b"replyMessage = rpc.rpc.kernelContent;" in kernel:
            role = "nested_reply_lookup"
        elif b"rpc.kernelContent = &msg->content.__hdr;" in kernel:
            role = "kernel_content_assignment"
        else:
            raise ValueError("unreviewed RPC conditional")
        counts[role] += 1
        return legacy

    result = BLOCK.sub(select_legacy, implementation)
    expected = {"invocation_field": 2, "content_accessor": 1, "message_lookup": 2,
                "rpc_initializer": 2, "typed_message_lookup": 2, "invocation_message_type": 2}
    if profile:
        expected = profile["selected_legacy_branches"]
    if dict(counts) != expected or b"kernelContent" in result or b"messageContent" in result:
        raise ValueError("incomplete legacy RPC projection")
    ignored_returns = 0

    def annotate_oneway(match):
        nonlocal ignored_returns
        body = match[0]
        uses = len(re.findall(rb"\bret\b", body))
        if uses not in (2, 3) or len(re.findall(rb"\bret\s*=", body)) != uses - 1:
            return body
        ignored_returns += 1
        return body.replace(b"kern_return_t ret;", b"[[maybe_unused]] kern_return_t ret;", 1)

    result = re.sub(rb"(?m)^void\n\w+::[^{]+\{\n    kern_return_t ret;.*?^}\n",
                    annotate_oneway, result, flags=re.S)
    if ignored_returns != (profile.get("ignored_oneway_return_declarations", 0) if profile else 0):
        raise ValueError("unexpected ignored one-way RPC result layout")
    output_hash = hashlib.sha256(result).hexdigest()
    if profile and output_hash != profile["output_sha256"]:
        raise ValueError("unexpected legacy RPC output hash")
    return result, {"selected_legacy_branches": dict(counts),
                    "input_sha256": expected_input,
                    "output_sha256": output_hash,
                    "ignored_oneway_return_declarations": ignored_returns,
                    "iorpc_sha256": IORPC_SHA256,
                    "kernel_abi_modified": False, "boot_approved": False,
                    "scope": "hash-pinned candidate only; not integrated into full kernel build"}


def prepare_candidates(directory, header):
    profiles = json.loads(Path(__file__).with_name("iig_legacy_profiles.json").read_text())
    paths = {path.name: path for path in directory.glob("*.iig.cpp")}
    if set(paths) != set(profiles) or len(profiles) != 17:
        raise ValueError("expected exact reviewed set of 17 IIG classes")
    candidates = {}
    reports = {}
    for name, path in sorted(paths.items()):
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("unsafe IIG class output")
        candidates[name], reports[name] = legacy_candidate(path.read_bytes(), header, profiles[name])
    return candidates, reports


def compiler_inline_assertions(candidate, name, body):
    banner = re.match(rb"/\* iig\(DriverKit-286 Mar 29 2024 10:27:09\) generated from (\w+)\.iig \*/\n", candidate)
    prefix = re.fullmatch(rb"(\s*IORPCMessageMach\s+mach;.*?)" + re.escape(name) +
                          rb"_Msg_Content\s+content;\s*", body, flags=re.S)
    if banner is None or not name.startswith(banner[1] + b"_") or prefix is None:
        raise ValueError("unreviewed inline RPC message layout")
    layout = prefix[1]
    print("WARNING: unreviewed RPC layout in " + banner[1].decode() + ".iig.cpp: " + name.decode() +
          "; using compiler-derived packed prefix sizeof; layout_sha256=" + hashlib.sha256(body).hexdigest() +
          "\n" + body.decode("utf-8", errors="replace"), file=sys.stderr)
    prefix_name = name + b"_MidoInlinePrefix"
    message = name + b"_Msg"
    assertions = (b"#pragma pack(push, 4)\nstruct " + prefix_name + b" {\n" + layout +
                  b"\n};\n#pragma pack(pop)\n")
    assertions += (b"static_assert(__builtin_offsetof(" + message + b", content) == sizeof(" +
                   prefix_name + b"), \"RPC compiler-derived inline content offset\");\n")
    assertions += (b"static_assert(sizeof(" + message + b") >= sizeof(" + prefix_name + b") + sizeof(" +
                   name + b"_Msg_Content), \"RPC compiler-derived inline size\");\n")
    assertions += (b"static_assert(__builtin_offsetof(" + message +
                   b", mach) == 0, \"RPC Mach header offset\");\n")
    return assertions


def invocation_assertions(candidate):
    names = re.findall(rb"}\s+(\w+)_Invocation;", candidate)
    if not names or len(names) > 256 or len(names) != len(set(names)):
        raise ValueError("expected bounded distinct invocation unions")
    assertions = b"\n#if KERNEL\n"
    for name in names:
        invocation = name + b"_Invocation"
        assertions += b"static_assert(sizeof(" + invocation + b") == sizeof(IORPC), \"RPC overlay size\");\n"
        assertions += b"static_assert(alignof(" + invocation + b") == alignof(IORPC), \"RPC overlay alignment\");\n"
        for field in (b"message", b"reply", b"sendSize", b"replySize"):
            assertions += (b"static_assert(__builtin_offsetof(" + invocation + b", " + field +
                           b") == __builtin_offsetof(IORPC, " + field + b"), \"RPC overlay field\");\n")
        inline = re.search(rb"struct " + re.escape(name) + rb"_Msg\s*\{([^}]+)\};", candidate)
        if inline and re.search(re.escape(name) + rb"_Msg_Content\s+content;", inline[1]):
            fields = re.fullmatch(
                rb"\s*IORPCMessageMach\s+mach;\s*"
                rb"((?:mach_msg_(?:port|ool|ool_ports)_descriptor_t\s+\w+;\s*)*)" +
                re.escape(name) + rb"_Msg_Content\s+content;\s*", inline[1])
            if fields is None:
                assertions += compiler_inline_assertions(candidate, name, inline[1])
                continue
            descriptor_types = re.findall(rb"(mach_msg_\w+_descriptor_t)\s+\w+;", fields[1])
            counts = Counter(descriptor_types)
            if not counts:
                counts[b"mach_msg_port_descriptor_t"] = 0
            descriptor_size = b" + ".join(str(count).encode() + b" * sizeof(" + kind + b")"
                                           for kind, count in counts.items())
            assertions += (b"static_assert(__builtin_offsetof(" + name + b"_Msg, content) == "
                           b"sizeof(IORPCMessageMach) + " + descriptor_size +
                           b", \"RPC inline content offset\");\n")
        else:
            assertions += (b"static_assert(__builtin_offsetof(" + name + b"_Msg_With_Content, content) == sizeof(" +
                           name + b"_Msg), \"RPC inline content offset\");\n")
    return assertions + b"#endif\n", len(names)


def layout_probe(candidate, header):
    start = candidate.index(b"struct OSObject_SetDispatchQueue_Msg_Content")
    end = candidate.index(b"#if !KERNEL\nextern OSMetaClass", start)
    declaration = re.search(rb"struct IORPC\s*\{[^}]+\};", header)
    if declaration is None:
        raise ValueError("missing IORPC declaration")
    prelude = b"""#define KERNEL 1
#define XNU_PLATFORM_DriverKit 1
#define DRIVERKIT_PRIVATE 1
typedef int kern_return_t;
"""
    assertions = b"""
static_assert(sizeof(void *) == 8, "LP64 required");
static_assert(sizeof(IORPC) == 24, "four-field RPC size");
static_assert(__builtin_offsetof(IORPC, message) == 0, "message offset");
static_assert(__builtin_offsetof(IORPC, reply) == 8, "reply offset");
static_assert(__builtin_offsetof(IORPC, sendSize) == 16, "send size offset");
static_assert(__builtin_offsetof(IORPC, replySize) == 20, "reply size offset");
"""
    for method in (b"SetDispatchQueue", b"CopyDispatchQueue"):
        name = b"OSObject_" + method
        assertions += b"static_assert(sizeof(" + name + b"_Invocation) == sizeof(IORPC), \"invocation size\");\n"
        assertions += b"static_assert(alignof(" + name + b"_Invocation) == alignof(IORPC), \"invocation alignment\");\n"
        for field in (b"message", b"reply", b"sendSize", b"replySize"):
            assertions += (b"static_assert(__builtin_offsetof(" + name + b"_Invocation, " + field +
                           b") == __builtin_offsetof(IORPC, " + field + b"), \"overlay offset\");\n")
        descriptor_count = b"2" if method == b"SetDispatchQueue" else b"1"
        assertions += (b"static_assert(__builtin_offsetof(" + name + b"_Msg_With_Content, content) == "
                       b"sizeof(IORPCMessageMach) + " + descriptor_count +
                       b" * sizeof(mach_msg_port_descriptor_t), \"inline content matches descriptor walk\");\n")
    return prelude + header + b"\n" + candidate[start:end] + assertions


def compile_layout(compiler, probe):
    command = [str(compiler.resolve()), "--target=arm64-apple-ios16.0", "-std=gnu++17",
               "-ffreestanding", "-fno-exceptions", "-fno-rtti", "-Wall", "-Wextra",
               "-Werror", "-fsyntax-only", str(probe.resolve())]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return {"command": command, "exit_code": result.returncode,
                "passed": result.returncode == 0,
                "diagnostics": (result.stdout + result.stderr)[:65536]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": command, "passed": False, "error": str(error)[:4000]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", type=Path, required=True)
    parser.add_argument("--iorpc-header", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args()
    implementation = args.implementation.resolve()
    header = args.iorpc_header.resolve()
    output = args.output_directory.resolve()
    if output == implementation.parent or output == header.parent or output.exists():
        raise ValueError("use a new isolated output directory")
    candidate, report = legacy_candidate(implementation.read_bytes(), header.read_bytes())
    probe = layout_probe(candidate, header.read_bytes())
    output.mkdir(parents=True)
    (output / "OSObject.legacy.cpp").write_bytes(candidate)
    (output / "rpc-layout-probe.cpp").write_bytes(probe)
    report["layout_probe_scope"] = "real generated unions and entire pinned IORPC header using its DriverKit declarations with KERNEL=1; not full exported kernel headers or runtime IPC validation"
    report["layout_compile"] = (compile_layout(args.compiler, output / "rpc-layout-probe.cpp")
                                if args.compiler else {"passed": False, "requested": False})
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.compiler and not report["layout_compile"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
