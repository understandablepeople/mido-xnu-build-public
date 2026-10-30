"""Opt-in native 4-KiB userspace page policy; not a complete iOS boot path."""

import hashlib
from pathlib import Path
import subprocess
import tempfile


SOURCE_HASHES = {
    "osfmk/arm/pmap/pmap.h": "c146d0ff53f3147aa041a50bfaaebcb723f259f86963734aefac877e30b52cfc",
    "osfmk/arm64/start.s": "0c1ee26454db866e13ebfc183cd213c29c65d6742ad4eff3b01886ff9d1c98c9",
    "osfmk/arm64/genassym.c": "a6fced49d3d64b132b19b8099e893f7bca9661e772cd38f064c2e8c2e837c33c",
    "bsd/kern/mach_loader.c": "584c063d99037194f0783df52d2ca205e47c4568bfb9fb48b46e211f7ae4efa9",
    "osfmk/arm/arm_init.c": "212a931f5b08e6812cbfea8bd4b920e29a6a51909629f180799831a17fbccab3",
    "osfmk/arm/commpage/commpage.c": "9b1050a77cca5b2aad668ef87f5a6edbe5faee8c0b658e71ea5ff45c947d58e8",
    "osfmk/vm/vm_shared_region.c": "5043b34437b65845da89889232baf7b3731bc4ee4e7436bbcad5908a3ee9752b",
}
PATCH = Path(__file__).resolve().parent.parent / "devices/mido/xnu/candidates/native-4k-user-abi.patch"
FEATURE = b"MIDO_NATIVE_4K_USER_ABI"
PATCH_SHA256 = "c4359d2107aca49e2d119779b803c35d02059b6bbe7891ae5d3a73cbfe623ee8"
FLAGS = "makedefs/MakeInc.def"


def stage_native_4k(source):
    source = source.resolve()
    before = {}
    for relative in (*SOURCE_HASHES, FLAGS):
        path = source / relative
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped native 4K staging path")
        before[relative] = path.read_bytes().replace(b"\r\n", b"\n")
    for relative, expected in SOURCE_HASHES.items():
        if hashlib.sha256(before[relative]).hexdigest() != expected:
            raise ValueError(f"unreviewed native 4K source: {relative}")
    flags = before[FLAGS]
    if FEATURE in flags:
        raise ValueError("native 4K policy already staged")
    definitions = [line for line in flags.splitlines()
                   if line.startswith(b"MACHINE_FLAGS_ARM64_MIDO =")]
    if len(definitions) != 1 or b"-DARM64_BOARD_CONFIG_MIDO" not in definitions[0]:
        raise ValueError("native 4K policy requires MIDO machine flags")
    patch = PATCH.read_bytes()
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise ValueError("unreviewed native 4K patch")
    after = {}
    with tempfile.TemporaryDirectory(prefix="mido-native-4k-") as temporary:
        scratch = Path(temporary)
        for relative in SOURCE_HASHES:
            destination = scratch / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(before[relative])
        result = subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--check", "-"], input=patch,
                                cwd=scratch, capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError("native 4K patch preflight failed: " + result.stderr.decode(errors="replace"))
        subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "-"], input=patch, cwd=scratch,
                       capture_output=True, check=True, timeout=30)
        for relative in SOURCE_HASHES:
            after[relative] = (scratch / relative).read_bytes().replace(b"\r\n", b"\n")
    after[FLAGS] = flags + b"\nMACHINE_FLAGS_ARM64_MIDO += -DMIDO_NATIVE_4K_USER_ABI=1\n"
    records = {}
    for relative, data in after.items():
        (source / relative).write_bytes(data)
        records[relative] = {"before_sha256": hashlib.sha256(before[relative]).hexdigest(),
                             "sha256": hashlib.sha256(data).hexdigest()}
    return {"files": records, "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "experimental": True, "kernel_page_shift": 12, "user_page_shift": 12,
            "bootstrap_capacity_updated": True, "signature_subpage_support_verified": False,
            "shared_cache_verified": False, "boot_approved": False}
