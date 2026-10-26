"""Stage matching, hash-pinned open pthread kernel sources for diagnostic MIDO."""

import hashlib
import io
from pathlib import Path, PurePosixPath
import tarfile


COMMIT = "a6c70ca0e544347a0377babf748f831577ec24f9"
ARCHIVE_SHA256 = "216360dcfdd7228294faeea6612aaa4967aa64a04dcbd06327d4408f26c38f7c"
TARGET = Path("bsd/pthread/mido_pthread")
UNITS = ("kern_init.c", "kern_support.c", "kern_synch.c")
SUPPORT_REPAIRS = (
    (b"extern void panic(const char *string, ...)", b"extern void (panic)(const char *string, ...)", 1),
    (b"*kevent_list_out = NULL;", b"*kevent_list_out = 0;", 1),
    (b"user_addr_t kevent_list = NULL;", b"user_addr_t kevent_list = 0;", 2),
    (b"workq_kevent(p, &th_addrs, NULL, 0, flags,", b"workq_kevent(p, &th_addrs, 0, 0, flags,", 1),
)
SYNCH_REPAIRS = (
    (b"psynch_wait_update_owner(kwq,", b"psynch_wait_update_owner((uintptr_t)kwq,", 4),
    (b"psynch_wait_wakeup(kwq,", b"psynch_wait_wakeup((uintptr_t)kwq,", 2),
    (b"psynch_wait_complete(kwq,", b"psynch_wait_complete((uintptr_t)kwq,", 1),
)


def dependency_files(archive):
    data = archive.read_bytes()
    if len(data) > 8 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("unreviewed pthread archive")
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as package:
        members = package.getmembers()
        if len(members) > 3000 or sum(member.size for member in members) > 32 * 1024 * 1024:
            raise ValueError("oversized pthread archive")
        for member in members:
            path = PurePosixPath(member.name)
            if (not path.parts or path.parts[0] != "libpthread-" + COMMIT or
                    path.is_absolute() or ".." in path.parts or "\\" in member.name or
                    ":" in member.name or not (member.isfile() or member.isdir())):
                raise ValueError("unsafe pthread archive member")
            relative = PurePosixPath(*path.parts[1:])
            if member.isfile() and (relative.parts[0] in ("kern", "include", "private")):
                if str(relative) in contents:
                    raise ValueError("duplicate pthread archive member")
                contents[str(relative)] = package.extractfile(member).read()
    for name in UNITS:
        if "kern/" + name not in contents:
            raise ValueError("missing pthread kernel unit")
    return contents


def stage_pthread(source, workspace=None):
    source = source.resolve()
    workspace = (workspace or Path(__file__).resolve().parents[1]).resolve()
    contents = dependency_files(workspace / "artifacts/libpthread-mido.tar.gz")
    for name in UNITS:
        contents["kern/mido_pthread_" + name] = contents.pop("kern/" + name)
    support_path = "kern/mido_pthread_kern_support.c"
    support_before = contents[support_path]
    for original, replacement, count in SUPPORT_REPAIRS:
        if contents[support_path].count(original) != count:
            raise ValueError("unreviewed pthread typed address or panic declaration")
        contents[support_path] = contents[support_path].replace(original, replacement)
    synch_path = "kern/mido_pthread_kern_synch.c"
    synch_before = contents[synch_path]
    for original, replacement, count in SYNCH_REPAIRS:
        if contents[synch_path].count(original) != count:
            raise ValueError("unreviewed pthread synchronization key")
        contents[synch_path] = contents[synch_path].replace(original, replacement)
    trace_before = contents["kern/kern_trace.h"]
    trace_call = b"vm_kernel_unslide_or_perm_external(ptr, &unslid_ptr);"
    if trace_before.count(trace_call) != 1:
        raise ValueError("unreviewed pthread unslide call")
    contents["kern/kern_trace.h"] = trace_before.replace(
        trace_call, b"vm_kernel_unslide_or_perm_external((vm_offset_t)ptr, &unslid_ptr);")
    contents["mido_pthread_startup.c"] = (
        workspace / "devices/mido/xnu/runtime/mido_pthread_startup.c").read_bytes()
    target = source / TARGET
    configuration = source / "bsd/conf/files"
    makefile = source / "bsd/conf/Makefile.arm64"
    for path in (target, configuration, makefile):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped pthread staging path")
    if target.exists():
        raise ValueError("pthread already staged")
    before = {path: path.read_bytes() for path in (configuration, makefile)}
    if any(b"MIDO_PTHREAD_DIAGNOSTIC" in data or b"mido_pthread/" in data for data in before.values()):
        raise ValueError("pthread graph already staged")
    units = ["kern/mido_pthread_" + name for name in UNITS] + ["mido_pthread_startup.c"]
    graph = before[configuration] + b"\n" + b"".join(
        f"{TARGET.as_posix()}/{name} optional mido_runtime\n".encode() for name in units)
    base = "$(SRCROOT)/" + TARGET.as_posix()
    flags = ("-DMIDO_PTHREAD_DIAGNOSTIC=1 -mgeneral-regs-only -fno-lto "
             "-DABSOLUTETIME_SCALAR_TYPE -DNEEDS_SCHED_CALL_T -D__PTHREAD_EXPOSE_INTERNALS__ "
             "-include mach/kmod.h "
             "-include sys/proc.h -UBSD_KERNEL_PRIVATE -UXNU_KERNEL_PRIVATE -UMACH_KERNEL_PRIVATE "
             "-Dport_name_to_thread=mido_pthread_port_name_to_thread "
             "-Dpthread_kern=mido_pthread_callbacks -Dcurrent_uthread=mido_pthread_current_uthread "
             f"-I{base} -I{base}/private -I{base}/include -idirafter $(SDKROOT)/usr/include")
    make = before[makefile] + b"\n" + b"".join(
        f"{Path(name).stem}.o_CFLAGS_ADD += {flags}\n".encode() for name in units[:-1])
    make += b"mido_pthread_startup.o_CFLAGS_ADD += -DMIDO_PTHREAD_DIAGNOSTIC=1 -mgeneral-regs-only -fno-lto\n"
    target.mkdir(parents=True)
    records = {}
    for name, data in contents.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest()}
        if name == "kern/kern_trace.h":
            records[path.relative_to(source).as_posix()]["before_sha256"] = hashlib.sha256(trace_before).hexdigest()
        if name == support_path:
            records[path.relative_to(source).as_posix()]["before_sha256"] = hashlib.sha256(support_before).hexdigest()
        if name == synch_path:
            records[path.relative_to(source).as_posix()]["before_sha256"] = hashlib.sha256(synch_before).hexdigest()
    for path, data in ((configuration, graph), (makefile, make)):
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = {
            "before_sha256": hashlib.sha256(before[path]).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}
    return {"commit": COMMIT, "archive_sha256": ARCHIVE_SHA256, "files": records,
            "registration": "THREAD_CALL/LAST; original pthread_init remains in BSD",
            "boot_approved": False, "hardware_verified": False}
