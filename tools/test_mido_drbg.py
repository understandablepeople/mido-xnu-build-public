"""Build and execute a pinned BearSSL-backed adapter on synthetic ARM64 only."""

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile

try:
    from tools.mido_elf import symbols_from_elf
except ModuleNotFoundError:
    from mido_elf import symbols_from_elf


ARCHIVE_SHA256 = "6705bba1714961b41a728dfc5debbe348d2966c117649392f8c8139efc83ff14"


class Reference:
    def __init__(self, seed):
        self.key = bytes(32)
        self.value = bytes([1]) * 32
        self.update(seed)

    def mac(self, data):
        return hmac.new(self.key, data, hashlib.sha256).digest()

    def update(self, seed):
        self.key = self.mac(self.value + b"\0" + seed)
        self.value = self.mac(self.value)
        if seed:
            self.key = self.mac(self.value + b"\1" + seed)
            self.value = self.mac(self.value)

    def generate(self, size):
        result = bytearray()
        if not size:
            return b""
        while len(result) < size:
            self.value = self.mac(self.value)
            result.extend(self.value)
        self.update(b"")
        return bytes(result[:size])

    def uniform(self, bound):
        threshold = ((1 << 64) - bound) % bound
        for _ in range(128):
            value = int.from_bytes(self.generate(8), "little")
            if value >= threshold:
                return value % bound
        raise ValueError("Reference rejection limit reached")


def verify_dependency(archive, source):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Unreviewed BearSSL archive")
    expected = set()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name)
            if relative.parts[0] != "bearssl-0.6" or ".." in relative.parts:
                raise ValueError("Unexpected dependency archive path")
            expected.add(Path(*relative.parts[1:]))
            candidate = source.joinpath(*relative.parts[1:])
            if candidate.read_bytes() != bundle.extractfile(member).read():
                raise ValueError(f"Modified dependency file: {relative}")
    paths = list(source.rglob("*"))
    if any(path.is_symlink() for path in paths) or {path.relative_to(source) for path in paths if path.is_file()} != expected:
        raise ValueError("Unexpected files or symbolic links in dependency tree")


def run(workspace, toolchain, output):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC, UC_CPU_ARM64_A53

    source = workspace / "artifacts/bearssl-0.6"
    verify_dependency(workspace / "artifacts/bearssl-0.6.tar.gz", source)
    if output.exists():
        raise ValueError("Output exists; refusing overwrite")
    output.mkdir(parents=True)
    includes = [source / "inc", source / "src", workspace / "devices/mido/xnu/early"]
    files = [source / name for name in (
        "src/hash/sha2small.c", "src/mac/hmac.c", "src/rand/hmac_drbg.c",
        "src/codec/dec32be.c", "src/codec/enc32be.c")]
    files += [workspace / name for name in ("devices/mido/xnu/early/drbg.c",
              "devices/mido/xnu/early/kernel_prng.c", "tests/fixtures/mido_drbg_support.c",
              "tests/fixtures/mido_kernel_prng_support.c")]
    objects = []
    commands = []
    for index, path in enumerate(files):
        target = output / f"unit-{index}.o"
        command = [str(toolchain / "clang.exe"), "--target=aarch64-linux-android28", "-mcpu=cortex-a53",
                   "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic", "-fno-pie",
                   "-fno-asynchronous-unwind-tables", "-mgeneral-regs-only", "-O2", "-c", str(path), "-o", str(target)]
        command += [item for include in includes for item in ("-I", str(include))]
        subprocess.run(command, check=True, capture_output=True, text=True)
        commands.append(command)
        objects.append(str(target))
    bridge = workspace / "devices/mido/xnu/runtime/mido_prng_bridge.c"
    bridge_command = [str(toolchain / "clang.exe"), "--target=aarch64-linux-android28", "-mcpu=cortex-a53",
                      "-ffreestanding", "-mgeneral-regs-only", "-Wall", "-Wextra", "-Werror",
                      "-fsyntax-only", str(bridge)]
    bridge_command += [item for include in includes + [workspace / "artifacts/mido-runtime-v3/source/EXTERNAL_HEADERS"]
                      for item in ("-I", str(include))]
    subprocess.run(bridge_command, check=True, capture_output=True, text=True)
    commands.append(bridge_command)
    elf = output / "drbg.elf"
    subprocess.run([str(toolchain / "ld.lld.exe"), "-T", str(workspace / "tests/fixtures/mido_drbg.ld"),
                    "--build-id=none", *objects, "-o", str(elf)], check=True, capture_output=True, text=True)
    binary = output / "drbg.bin"
    subprocess.run([str(toolchain / "llvm-objcopy.exe"), "-O", "binary", str(elf), str(binary)], check=True)
    symbols = symbols_from_elf(elf.read_bytes(), required=(
        "mido_drbg_init", "mido_drbg_generate", "mido_drbg_reseed", "mido_drbg_uniform",
        "mido_drbg_clear", "mido_drbg_test_size", "mido_drbg_test_counter_offset",
        "mido_prng_test_init", "mido_prng_generate", "mido_prng_init_cpu", "mido_prng_refresh",
        "mido_prng_mix_input", "mido_prng_test_size", "mido_prng_test_counter_offset"))
    payload = binary.read_bytes()
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(UC_CPU_ARM64_A53)
    cpu.mem_map(0x10000000, (len(payload) + 4095) & -4096)
    cpu.mem_write(0x10000000, payload)
    cpu.mem_protect(0x10000000, (len(payload) + 4095) & -4096, UC_PROT_READ | UC_PROT_EXEC)
    cpu.mem_map(0x20000000, 0x40000)
    cpu.mem_map(0x21000000, 0x4000)
    cpu.mem_map(0x22000000, 4096)
    state, seed_address, buffer = 0x20000000, 0x20001000, 0x20010000

    def call(name, *arguments):
        for register, value in zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3), arguments):
            cpu.reg_write(register, value)
        cpu.reg_write(UC_ARM64_REG_SP, 0x21004000)
        cpu.reg_write(UC_ARM64_REG_X30, 0x22000000)
        cpu.emu_start(symbols[name], 0x22000000, timeout=30000000, count=100000000)
        if cpu.reg_read(UC_ARM64_REG_PC) != 0x22000000:
            raise AssertionError(f"{name} did not return")
        return cpu.reg_read(UC_ARM64_REG_X0) & 0xffffffff

    passed = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        passed.append(name)
        print("PASS", name, flush=True)

    context_size = call("mido_drbg_test_size")
    counter_offset = call("mido_drbg_test_counter_offset")
    check("context-fits-xnu-kmem-limit", context_size <= 256)
    seed = bytes(range(64))
    cpu.mem_write(seed_address, seed)
    check("reject-uninitialized", call("mido_drbg_generate", state, buffer, 32) == 0xffffffff)
    check("reject-short-seed", call("mido_drbg_init", state, seed_address, 47) == 0xffffffff)
    check("reject-overlapping-seed", call("mido_drbg_init", state, state, 64) == 0xffffffff)
    check("initialize", call("mido_drbg_init", state, seed_address, 64) == 0)
    reference = Reference(seed)
    for length in (0, 1, 31, 32, 33, 1024, 65536):
        check(f"sha256-hmac-drbg-reference-{length}",
              call("mido_drbg_generate", state, buffer, length) == 0 and
              bytes(cpu.mem_read(buffer, length)) == reference.generate(length))
    before = bytes(cpu.mem_read(state, context_size))
    check("reject-oversize-request", call("mido_drbg_generate", state, buffer, 65537) == 0xffffffff)
    check("reject-overlapping-output", call("mido_drbg_generate", state, state, 32) == 0xffffffff)
    check("rejected-requests-preserve-state", bytes(cpu.mem_read(state, context_size)) == before)
    for bound in (1, 3, 257, (1 << 63) + 1, (1 << 64) - 1):
        check(f"uniform-reference-{bound}", call("mido_drbg_uniform", state, bound, buffer) == 0 and
              struct.unpack("<Q", cpu.mem_read(buffer, 8))[0] == reference.uniform(bound))
    check("reject-zero-bound", call("mido_drbg_uniform", state, 0, buffer) == 0xffffffff)
    check("reject-null-state", call("mido_drbg_generate", 0, buffer, 32) == 0xffffffff)
    check("reject-null-output", call("mido_drbg_generate", state, 0, 32) == 0xffffffff)
    check("reject-uniform-state-overlap", call("mido_drbg_uniform", state, 17, state) == 0xffffffff)
    cpu.mem_write(state + counter_offset, struct.pack("<Q", 16777216))
    check("require-reseed-at-byte-budget", call("mido_drbg_generate", state, buffer, 1) == 0xfffffffe)
    check("uniform-propagates-reseed-required", call("mido_drbg_uniform", state, 17, buffer) == 0xfffffffe)
    check("reject-short-reseed", call("mido_drbg_reseed", state, seed_address, 31) == 0xffffffff)
    check("reseed", call("mido_drbg_reseed", state, seed_address, 64) == 0)
    reference.update(seed)
    check("reseed-reference", call("mido_drbg_generate", state, buffer, 64) == 0 and
          bytes(cpu.mem_read(buffer, 64)) == reference.generate(64))
    for seed_length in (48, 65, 128):
        test_seed = bytes(index % 256 for index in range(seed_length))
        cpu.mem_write(seed_address, test_seed)
        check(f"seed-length-reference-{seed_length}",
              call("mido_drbg_init", state, seed_address, seed_length) == 0 and
              call("mido_drbg_generate", state, buffer, 64) == 0 and
              bytes(cpu.mem_read(buffer, 64)) == Reference(test_seed).generate(64))
    call("mido_drbg_clear", state)
    check("clear-entire-context", not any(cpu.mem_read(state, context_size)))
    check("reject-cleared-state", call("mido_drbg_generate", state, buffer, 32) == 0xffffffff)
    kernel_state, environment = 0x20002000, 0x20003000
    kernel_size = call("mido_prng_test_size")
    kernel_counter = call("mido_prng_test_counter_offset")
    cpu.mem_write(seed_address, bytes(range(64)))
    check("kernel-reject-smp", call("mido_prng_test_init", kernel_state, environment, seed_address, 2) == 0xffffffff)
    check("kernel-original-32-byte-seed-8-byte-nonce", call("mido_prng_test_init", kernel_state, environment, seed_address, 1) == 0)
    kernel_reference = Reference(bytes(range(40)) + b"MIDO-XNU-kernel-PRNG-v1".ljust(24, b"\0"))
    check("kernel-reject-uninitialized-cpu", call("mido_prng_generate", kernel_state, 0, buffer, 32) == 0xffffffff)
    check("kernel-reject-secondary-cpu", call("mido_prng_init_cpu", kernel_state, 1) == 0xffffffff)
    check("kernel-initialize-cpu0", call("mido_prng_init_cpu", kernel_state, 0) == 0)
    check("kernel-reject-duplicate-cpu-init", call("mido_prng_init_cpu", kernel_state, 0) == 0xffffffff)
    check("kernel-generate-reference", call("mido_prng_generate", kernel_state, 0, buffer, 256) == 0 and
          bytes(cpu.mem_read(buffer, 256)) == kernel_reference.generate(256))
    before = bytes(cpu.mem_read(kernel_state, kernel_size))
    check("kernel-original-request-limit", call("mido_prng_generate", kernel_state, 0, buffer, 257) == 0xffffffff)
    check("kernel-reject-state-output-alias", call("mido_prng_generate", kernel_state, 0, kernel_state, 32) == 0xffffffff)
    check("kernel-invalid-requests-preserve-state", bytes(cpu.mem_read(kernel_state, kernel_size)) == before)
    cpu.mem_write(kernel_state + kernel_counter, struct.pack("<Q", 16777216))
    check("kernel-mix-untrusted-input", call("mido_prng_mix_input", kernel_state, seed_address, 32) == 0)
    check("kernel-untrusted-input-no-entropy-credit", struct.unpack("<Q", cpu.mem_read(kernel_state + kernel_counter, 8))[0] == 16777216)
    kernel_reference.update(bytes(range(32)))
    check("kernel-exhausted-after-user-reseed", call("mido_prng_generate", kernel_state, 0, buffer, 1) == 0xfffffffe)
    check("kernel-refresh-with-no-entropy", call("mido_prng_refresh", kernel_state) == 0)
    check("kernel-no-entropy-keeps-limit", call("mido_prng_generate", kernel_state, 0, buffer, 1) == 0xfffffffe)
    cpu.mem_write(environment + 12, struct.pack("<I", 1))
    check("kernel-refresh-lock-contention", call("mido_prng_refresh", kernel_state) == 0xfffffffc)
    check("kernel-generate-lock-contention", call("mido_prng_generate", kernel_state, 0, buffer, 1) == 0xfffffffc)
    cpu.mem_write(environment + 12, bytes(4))
    cpu.mem_write(environment + 20, struct.pack("<I", 1))
    check("kernel-refresh-qualified-entropy", call("mido_prng_refresh", kernel_state) == 0)
    kernel_reference.update(bytes(range(0xa0, 0xc0)))
    check("kernel-after-refresh-reference", call("mido_prng_generate", kernel_state, 0, buffer, 256) == 0 and
          bytes(cpu.mem_read(buffer, 256)) == kernel_reference.generate(256))
    cpu.mem_write(environment + 20, struct.pack("<I", 2))
    check("kernel-entropy-health-failure", call("mido_prng_refresh", kernel_state) == 0xfffffffb)
    check("kernel-health-failure-sticky", call("mido_prng_generate", kernel_state, 0, buffer, 1) == 0xfffffffb)
    check("kernel-health-failure-clears-drbg", not any(cpu.mem_read(kernel_state, context_size)))
    for mode in (3, 4, 5):
        cpu.mem_write(kernel_state, bytes(kernel_size))
        cpu.mem_write(environment, bytes(32))
        call("mido_prng_test_init", kernel_state, environment, seed_address, 1)
        call("mido_prng_init_cpu", kernel_state, 0)
        cpu.mem_write(environment + 20, struct.pack("<I", mode))
        check(f"kernel-reject-entropy-contract-{mode}", call("mido_prng_refresh", kernel_state) == 0xfffffffa)
    lock_state = struct.unpack("<8I", cpu.mem_read(environment, 32))
    check("kernel-locks-balanced", lock_state[1] == lock_state[2] and lock_state[4] == 0 and lock_state[7] == 0)
    report = dict(scope="Isolated ARM64 adapter only; NOT integrated into XNU or a handset image",
                  dependency_archive_sha256=ARCHIVE_SHA256, code_sha256=hashlib.sha256(payload).hexdigest(),
                  context_bytes=context_size, passed=passed, compilation_commands=commands,
                  kernel_provider_registered=False, kernel_prng_registered=False, boot_approved=False,
                  bridge_validation="Original cckprng_funcs header, Android ARM64 syntax/type checking only; not a kernel build or registration test",
                  reference_scope="Independent Python HMAC/SHA256 implementation; not CAVP certification")
    report["source_sha256"] = {str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in files + [bridge, workspace / "devices/mido/xnu/runtime/mido_prng_bridge.h",
                                                    workspace / "devices/mido/xnu/early/kernel_prng.h",
                                                    workspace / "artifacts/mido-runtime-v3/source/EXTERNAL_HEADERS/corecrypto/cckprng.h",
                                                    workspace / "devices/mido/xnu/early/drbg.h",
                                                    workspace / "tests/fixtures/mido_drbg.ld"]}
    report["compiler_version"] = subprocess.run([str(toolchain / "clang.exe"), "--version"],
                                                  check=True, capture_output=True, text=True).stdout
    report["original_contract_sources"] = {
        name: hashlib.sha256((workspace / "artifacts/mido-runtime-v3/source" / name).read_bytes()).hexdigest()
        for name in ("osfmk/prng/prng_random.c", "osfmk/prng/entropy.c")}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "BEARSSL_LICENSE.txt").write_bytes((source / "LICENSE.txt").read_bytes())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace / "artifacts/python-deps"))
    try:
        run(workspace, args.toolchain, args.output.resolve())
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr) from error


if __name__ == "__main__":
    main()
