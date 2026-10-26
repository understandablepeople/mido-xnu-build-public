"""Execute bridge callbacks with a synthetic recipient, NOT original XNU registration."""

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys

try:
    from tools.test_mido_drbg import Reference, verify_dependency, ARCHIVE_SHA256
    from tools.mido_elf import symbols_from_elf
except ModuleNotFoundError:
    from test_mido_drbg import Reference, verify_dependency, ARCHIVE_SHA256
    from mido_elf import symbols_from_elf


def input_hashes(workspace, paths):
    return {str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def require_unchanged_inputs(workspace, expected):
    for name, digest in expected.items():
        path = workspace / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Evidence input changed during execution: " + name)


def run(workspace, toolchain, output):
    import cryptography
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_SP, UC_ARM64_REG_X30, UC_ARM64_REG_PC, UC_CPU_ARM64_A53

    source = workspace / "artifacts/bearssl-0.6"
    verify_dependency(workspace / "artifacts/bearssl-0.6.tar.gz", source)
    if output.exists():
        raise ValueError("Output exists; refusing overwrite")
    output.mkdir(parents=True)
    includes = [source / "inc", source / "src", workspace / "devices/mido/xnu/early",
                workspace / "devices/mido/xnu/runtime", workspace / "artifacts/mido-runtime-v3/source/EXTERNAL_HEADERS",
                workspace / "artifacts/mido-runtime-v3/source/libkern"]
    sources = [source / name for name in ("src/hash/sha2small.c", "src/mac/hmac.c", "src/rand/hmac_drbg.c",
                                         "src/codec/dec32be.c", "src/codec/enc32be.c", "src/hash/md5.c", "src/hash/sha1.c",
                                         "src/hash/sha2big.c", "src/codec/dec64be.c", "src/codec/enc64be.c",
                                         "src/codec/dec32le.c", "src/codec/enc32le.c",
                                         "src/symcipher/aes_ct.c", "src/symcipher/aes_ct_enc.c", "src/symcipher/aes_ct_dec.c",
                                         "src/symcipher/aes_ct_cbcenc.c", "src/symcipher/aes_ct_cbcdec.c",
                                         "src/symcipher/aes_ct_ctr.c", "src/aead/gcm.c", "src/hash/ghash_ctmul32.c")]
    sources += [workspace / name for name in ("devices/mido/xnu/early/drbg.c", "devices/mido/xnu/early/kernel_prng.c",
                "devices/mido/xnu/runtime/mido_prng_bridge.c", "devices/mido/xnu/runtime/mido_kmem_random.c",
                "devices/mido/xnu/runtime/mido_sha256.c", "tests/fixtures/mido_sha256_support.c",
                "devices/mido/xnu/runtime/mido_hmac_sha256.c", "tests/fixtures/mido_hmac_sha256_support.c",
                "devices/mido/xnu/runtime/mido_digest.c", "tests/fixtures/mido_digest_support.c",
                "devices/mido/xnu/runtime/mido_hmac.c",
                "devices/mido/xnu/runtime/mido_aes_cbc.c", "tests/fixtures/mido_aes_cbc_support.c",
                "devices/mido/xnu/runtime/mido_aes_ctr.c", "tests/fixtures/mido_aes_ctr_support.c",
                "devices/mido/xnu/runtime/mido_aes_xts.c", "tests/fixtures/mido_aes_xts_support.c",
                "devices/mido/xnu/runtime/mido_aes_gcm.c", "tests/fixtures/mido_aes_gcm_support.c",
                "devices/mido/xnu/runtime/mido_ccrng.c", "tests/fixtures/mido_ccrng_support.c",
                "tests/fixtures/mido_drbg_support.c",
                "tests/fixtures/mido_prng_bridge_support.c")]
    source_hashes = input_hashes(workspace, sources)
    abi_headers = sorted((workspace / "artifacts/mido-runtime-v3/source/EXTERNAL_HEADERS/corecrypto").glob("*.h"))
    abi_headers += [workspace / ("artifacts/mido-runtime-v3/source/libkern/libkern/crypto/" + name)
                   for name in ("rand.h", "crypto.h", "register_crypto.h", "sha2.h", "aes.h", "aesxts.h")]
    abi_hashes = input_hashes(workspace, abi_headers)
    port_headers = sorted((workspace / "devices/mido/xnu/runtime").glob("*.h"))
    port_headers += sorted((workspace / "devices/mido/xnu/early").glob("*.h"))
    header_hashes = input_hashes(workspace, port_headers)
    harness_hashes = input_hashes(workspace, [workspace / ("tools/" + name) for name in
                                 ("test_mido_prng_bridge.py", "mido_gcm_checks.py", "test_mido_drbg.py", "mido_elf.py")])
    commands = []
    objects = []
    for index, path in enumerate(sources):
        target = output / f"unit-{index}.o"
        command = [str(toolchain / "clang.exe"), "--target=aarch64-linux-android28", "-mcpu=cortex-a53",
                   "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic", "-fno-pie",
                   "-fno-asynchronous-unwind-tables", "-mgeneral-regs-only", "-Wall", "-Wextra", "-Werror",
                   "-O2", "-c", str(path), "-o", str(target)]
        command += [item for include in includes for item in ("-I", str(include))]
        subprocess.run(command, check=True, capture_output=True, text=True)
        commands.append(command)
        objects.append(str(target))
    elf, binary = output / "bridge.elf", output / "bridge.bin"
    subprocess.run([str(toolchain / "ld.lld.exe"), "-T", str(workspace / "tests/fixtures/mido_prng_bridge.ld"),
                    "--build-id=none", *objects, "-o", str(elf)], check=True, capture_output=True, text=True)
    subprocess.run([str(toolchain / "llvm-objcopy.exe"), "-O", "binary", str(elf), str(binary)], check=True)
    required = ("mido_bridge_test_start", "mido_bridge_test_read", "mido_bridge_test_refresh", "mido_bridge_test_mix",
                "mido_bridge_test_init_cpu", "mido_bridge_test_wrong_context", "mido_bridge_test_invalid_services",
                "mido_kmem_random_size", "mido_kmem_random_init", "mido_kmem_random_generate", "mido_kmem_random_uniform",
                "mido_bridge_test_service_entries", "mido_bridge_test_random_calls",
                "mido_sha256_test_size", "mido_sha256_test_init", "mido_sha256_test_update",
                "mido_sha256_test_final", "mido_sha256_test_digest", "mido_sha256_test_wrong_info",
                "mido_sha256_test_callback_final",
                "mido_hmac_test_init", "mido_hmac_test_update", "mido_hmac_test_final", "mido_hmac_test_oneshot",
                "mido_digest_test_init", "mido_digest_test_update", "mido_digest_test_final", "mido_digest_test_oneshot",
                "mido_hmac_all_test_init", "mido_hmac_all_test_update", "mido_hmac_all_test_final", "mido_hmac_all_test_oneshot",
                "mido_aes_test_size", "mido_aes_test_init", "mido_aes_test_update",
                "mido_ctr_test_size", "mido_ctr_test_init", "mido_ctr_test_update", "mido_ctr_test_set_counter",
                "mido_xts_test_size", "mido_xts_test_init", "mido_xts_test_set_tweak", "mido_xts_test_update", "mido_xts_test_schedule",
                "mido_gcm_test_size", "mido_gcm_test_init", "mido_gcm_test_init_managed", "mido_gcm_test_iv",
                "mido_gcm_test_aad", "mido_gcm_test_update", "mido_gcm_test_final", "mido_gcm_test_reset", "mido_gcm_test_inc",
                "mido_ccrng_test_get", "mido_ccrng_test_generate", "mido_ccrng_test_wrong_state", "mido_kernel_prng_is_ready",
                "panic", "_writable_start", "_image_end")
    symbols = symbols_from_elf(elf.read_bytes(), required=required)
    payload = binary.read_bytes()
    code_base, data_base, stack_base, stop = 0x10000000, 0x20000000, 0x21000000, 0x22000000
    mapped_size = (symbols["_image_end"] - code_base + 4095) & -4096
    if not 0 < len(payload) <= mapped_size <= 1024 * 1024 or symbols["_writable_start"] % 4096:
        raise ValueError("Unexpected bridge fixture layout")
    passed, panics = [], []

    def create():
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        cpu.ctl_set_cpu_model(UC_CPU_ARM64_A53)
        cpu.mem_map(code_base, mapped_size)
        cpu.mem_write(code_base, payload)
        cpu.mem_protect(code_base, symbols["_writable_start"] - code_base, UC_PROT_READ | UC_PROT_EXEC)
        cpu.mem_protect(symbols["_writable_start"], mapped_size - symbols["_writable_start"] + code_base,
                        UC_PROT_READ | UC_PROT_WRITE)
        cpu.mem_map(data_base, 8192)
        cpu.mem_map(stack_base, 32768)
        cpu.mem_map(stop, 4096)
        panic_event = []
        def panic_observer(engine, address, size, context):
            pointer = engine.reg_read(UC_ARM64_REG_X0)
            text = bytes(engine.mem_read(pointer, 128)).split(b"\0", 1)[0].decode("ascii")
            panic_event.append(text)
            engine.emu_stop()
        cpu.hook_add(UC_HOOK_CODE, panic_observer, begin=symbols["panic"], end=symbols["panic"])
        return cpu, panic_event

    def call(cpu, events, name, arguments=(), expect_panic=False):
        events.clear()
        for register, value in zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5), arguments):
            cpu.reg_write(register, value)
        cpu.reg_write(UC_ARM64_REG_SP, stack_base + 32768)
        cpu.reg_write(UC_ARM64_REG_X30, stop)
        cpu.emu_start(symbols[name], stop, timeout=30000000, count=100000000)
        if expect_panic:
            if not events or cpu.reg_read(UC_ARM64_REG_PC) != symbols["panic"]:
                raise AssertionError(f"{name} failed to panic")
            panics.append(dict(function=name, format=events[0]))
        elif events or cpu.reg_read(UC_ARM64_REG_PC) != stop:
            raise AssertionError(f"{name} did not return normally: {events}")
        if bytes(cpu.mem_read(code_base, symbols["_writable_start"] - code_base)) != payload[:symbols["_writable_start"] - code_base].ljust(symbols["_writable_start"] - code_base, b"\0"):
            raise AssertionError("Bridge executable or constants modified")
        return cpu.reg_read(UC_ARM64_REG_X0)

    def check(name, condition=True):
        if not condition:
            raise AssertionError(name)
        passed.append(name)
        print("PASS", name, flush=True)

    def initialize(legacy=0):
        cpu, events = create()
        check(f"synthetic-recipient-registration-legacy-{legacy}",
              call(cpu, events, "mido_bridge_test_start", (1, 1, legacy)) == 1)
        return cpu, events, Reference(bytes(range(40)) + b"MIDO-XNU-kernel-PRNG-v1".ljust(24, b"\0"))

    cpu, events = create()
    error_pointer = data_base + 7808
    check("ccrng-not-ready-before-registration", call(cpu, events, "mido_kernel_prng_is_ready") == 0 and
          call(cpu, events, "mido_ccrng_test_get", (error_pointer,)) == 0 and
          int.from_bytes(cpu.mem_read(error_pointer, 4), "little", signed=True) != 0)
    for length in (0, 1, 255, 256, 257, 512, 1024):
        cpu, events, reference = initialize()
        state = call(cpu, events, "mido_ccrng_test_get", (error_pointer,))
        check("ccrng-published-after-registration", state != 0 and call(cpu, events, "mido_kernel_prng_is_ready") == 1 and
              bytes(cpu.mem_read(error_pointer, 4)) == bytes(4) and call(cpu, events, "mido_ccrng_test_get", (0,)) == state)
        cpu.mem_write(data_base + length, b"guard")
        expected = b"".join(reference.generate(min(256, length - start)) for start in range(0, length, 256))
        check(f"ccrng-reference-{length}", call(cpu, events, "mido_ccrng_test_generate", (state, length, data_base if length else 0)) == 0 and
              bytes(cpu.mem_read(data_base, length)) == expected and bytes(cpu.mem_read(data_base + length, 5)) == b"guard" and
              call(cpu, events, "mido_bridge_test_random_calls") == (length + 255) // 256)
        before = bytes(cpu.mem_read(state, 8))
        check("ccrng-getter-cannot-overwrite-callback", call(cpu, events, "mido_ccrng_test_get", (state,)) == 0 and
              bytes(cpu.mem_read(state, 8)) == before)
        for invalid_length, pointer in ((1, 0), (8, state), (16, (1 << 64) - 8), ((1 << 64) - 8, data_base)):
            before = bytes(cpu.mem_read(data_base, 8192))
            check("ccrng-reject-invalid-output", call(cpu, events, "mido_ccrng_test_generate", (state, invalid_length, pointer)) != 0 and
                  bytes(cpu.mem_read(data_base, 8192)) == before)
        check("ccrng-reject-copied-state", call(cpu, events, "mido_ccrng_test_wrong_state", (state, 1, data_base)) != 0)
    try:
        from tools.mido_gcm_checks import run as check_gcm
    except ModuleNotFoundError:
        from mido_gcm_checks import run as check_gcm
    check_gcm(create, call, check, data_base)

    cpu, events, reference = initialize()
    call(cpu, events, "mido_bridge_test_read", (256, data_base))
    check("bridge-eight-argument-init-and-generate", bytes(cpu.mem_read(data_base, 256)) == reference.generate(256))
    user_input = b"arbitrary user input with no fresh entropy credit"
    cpu.mem_write(data_base + 4096, user_input)
    call(cpu, events, "mido_bridge_test_mix", (len(user_input), data_base + 4096))
    reference.update(hashlib.sha256(user_input).digest())
    call(cpu, events, "mido_bridge_test_read", (128, data_base))
    check("bridge-arbitrary-input-hash-reference", bytes(cpu.mem_read(data_base, 128)) == reference.generate(128))
    call(cpu, events, "mido_bridge_test_refresh", (1, 1))
    call(cpu, events, "mido_bridge_test_read", (32, data_base))
    check("bridge-busy-refresh-defers", bytes(cpu.mem_read(data_base, 32)) == reference.generate(32))
    call(cpu, events, "mido_bridge_test_refresh", (1, 0))
    reference.update(bytes(range(0xa0, 0xc0)))
    call(cpu, events, "mido_bridge_test_read", (64, data_base))
    check("bridge-qualified-refresh-reference", bytes(cpu.mem_read(data_base, 64)) == reference.generate(64))
    cpu, events, reference = initialize(1)
    call(cpu, events, "mido_bridge_test_read", (64, data_base))
    check("bridge-seven-argument-legacy-init", bytes(cpu.mem_read(data_base, 64)) == reference.generate(64))
    for name, function, arguments, needs_init in (
        ("reject-no-crypto-provider", "mido_bridge_test_start", (0, 1, 0), False),
        ("reject-smp", "mido_bridge_test_start", (1, 2, 0), False),
        ("reject-double-registration", "mido_bridge_test_start", (1, 1, 0), True),
        ("reject-oversize-request", "mido_bridge_test_read", (257, data_base), True),
        ("reject-duplicate-cpu", "mido_bridge_test_init_cpu", (0,), True),
        ("reject-secondary-cpu", "mido_bridge_test_init_cpu", (1,), True),
        ("reject-wrong-context", "mido_bridge_test_wrong_context", (data_base,), True),
        ("reject-null-user-input", "mido_bridge_test_mix", (1, 0), True),
        ("reject-null-output", "mido_bridge_test_read", (1, 0), True),
        ("reject-no-services", "mido_bridge_test_invalid_services", (0,), False),
        ("reject-no-enter-service", "mido_bridge_test_invalid_services", (1,), False),
        ("reject-no-leave-service", "mido_bridge_test_invalid_services", (2,), False),
        ("reject-entropy-health-error", "mido_bridge_test_refresh", ((1 << 32) - 1, 0), True),
        ("reject-entropy-length", "mido_bridge_test_refresh", (2, 0), True),
    ):
        cpu, events = create()
        if needs_init:
            call(cpu, events, "mido_bridge_test_start", (1, 1, 0))
        call(cpu, events, function, arguments, expect_panic=True)
        check("bridge-" + name)
    cpu, events, reference = initialize()
    context = data_base + 4096
    context_size = call(cpu, events, "mido_kmem_random_size")
    check("kmem-original-context-size-contract", 0 < context_size <= 256)
    call(cpu, events, "mido_kmem_random_init", (context,))
    service_entries = call(cpu, events, "mido_bridge_test_service_entries")
    check("kmem-seed-request-count", call(cpu, events, "mido_bridge_test_random_calls") == 1)
    kmem_reference = Reference(reference.generate(48) + b"MIDO-kmem-v1".ljust(16, b"\0"))
    call(cpu, events, "mido_kmem_random_generate", (context, data_base, 513))
    expected = kmem_reference.generate(256) + kmem_reference.generate(256) + kmem_reference.generate(1)
    check("kmem-seeded-through-bridge-and-chunk-reference", bytes(cpu.mem_read(data_base, 513)) == expected)
    call(cpu, events, "mido_kmem_random_generate", (context, 0, 0))
    call(cpu, events, "mido_kmem_random_generate", (context, data_base, 32))
    check("kmem-zero-length-preserves-state", bytes(cpu.mem_read(data_base, 32)) == kmem_reference.generate(32))
    for bound in (1, 3, (1 << 63) + 1, (1 << 64) - 1):
        threshold = (1 << 64) % bound
        for attempt in range(128):
            value = int.from_bytes(kmem_reference.generate(8), "little")
            if value >= threshold:
                break
        else:
            raise AssertionError("Reference rejection limit")
        call(cpu, events, "mido_kmem_random_uniform", (context, bound, data_base))
        check(f"kmem-uniform-reference-{bound}", int.from_bytes(cpu.mem_read(data_base, 8), "little") == value % bound)
    check("kmem-generation-does-not-enter-prng-lock-services",
          call(cpu, events, "mido_bridge_test_service_entries") == service_entries)
    check("kmem-generation-does-not-request-seed",
          call(cpu, events, "mido_bridge_test_random_calls") == 1)
    for name, function, arguments, initialized in (
        ("uninitialized", "mido_kmem_random_generate", (context, data_base, 8), False),
        ("null-context", "mido_kmem_random_init", (0,), False),
        ("unaligned-context", "mido_kmem_random_init", (context + 1,), False),
        ("null-output", "mido_kmem_random_generate", (context, 0, 1), True),
        ("overlap", "mido_kmem_random_generate", (context, context, 1), True),
        ("overflow", "mido_kmem_random_generate", (context, (1 << 64) - 8, 16), True),
        ("zero-bound", "mido_kmem_random_uniform", (context, 0, data_base), True),
        ("unaligned-uniform-output", "mido_kmem_random_uniform", (context, 3, data_base + 1), True),
    ):
        cpu, events, reference = initialize()
        if initialized:
            call(cpu, events, "mido_kmem_random_init", (context,))
        call(cpu, events, function, arguments, expect_panic=True)
        check("kmem-reject-" + name)
    cpu, events = create()
    check("sha256-original-entropy-context-size", call(cpu, events, "mido_sha256_test_size") >= 108)
    for length in (0, 1, 55, 56, 63, 64, 65, 119, 120, 127, 128, 129, 4096):
        message = bytes(index % 251 for index in range(length))
        if message:
            cpu.mem_write(data_base, message)
        call(cpu, events, "mido_sha256_test_digest", (length, data_base, data_base + 6144))
        expected = hashlib.sha256(message).digest()
        check(f"sha256-oneshot-reference-{length}", bytes(cpu.mem_read(data_base + 6144, 32)) == expected)
        call(cpu, events, "mido_sha256_test_init", (context,))
        offset = 0
        for chunk in (1, 7, 55, 64, 127, 3842):
            consumed = min(chunk, length - offset)
            call(cpu, events, "mido_sha256_test_update", (context, consumed, data_base + offset))
            offset += consumed
        check(f"sha256-stream-covered-{length}", offset == length)
        check(f"sha256-original-state-fields-{length}",
              int.from_bytes(cpu.mem_read(context, 8), "little") == (length // 64) * 512 and
              int.from_bytes(cpu.mem_read(context + 104, 4), "little") == length % 64)
        call(cpu, events, "mido_sha256_test_final", (context, data_base + 6144))
        check(f"sha256-stream-reference-{length}", bytes(cpu.mem_read(data_base + 6144, 32)) == expected)
    cpu.mem_write(data_base, b"a" * 4096)
    call(cpu, events, "mido_sha256_test_init", (context,))
    for offset in range(0, 1000000, 4096):
        call(cpu, events, "mido_sha256_test_update", (context, min(4096, 1000000 - offset), data_base))
    before_zero_update = bytes(cpu.mem_read(context, 108))
    call(cpu, events, "mido_sha256_test_update", (context, 0, 0))
    check("sha256-zero-update-preserves-state", bytes(cpu.mem_read(context, 108)) == before_zero_update)
    call(cpu, events, "mido_sha256_test_callback_final", (context, data_base + 6144))
    check("sha256-million-a-known-answer", bytes(cpu.mem_read(data_base + 6144, 32)).hex() ==
          "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")
    for name, function, arguments in (
        ("wrong-info", "mido_sha256_test_wrong_info", (context,)),
        ("null-context", "mido_sha256_test_init", (0,)),
        ("unaligned-context", "mido_sha256_test_init", (context + 1,)),
        ("overlap", "mido_sha256_test_update", (context, 1, context)),
        ("null-input", "mido_sha256_test_update", (context, 1, 0)),
        ("null-output", "mido_sha256_test_final", (context, 0)),
    ):
        cpu, events = create()
        call(cpu, events, "mido_sha256_test_init", (context,))
        call(cpu, events, function, arguments, expect_panic=True)
        check("sha256-reject-" + name)
    for name, field_offset, value, size in (
        ("buffer-count", 104, 64, 4),
        ("unaligned-bit-count", 0, 1, 8),
    ):
        cpu, events = create()
        call(cpu, events, "mido_sha256_test_init", (context,))
        cpu.mem_write(context + field_offset, value.to_bytes(size, "little"))
        call(cpu, events, "mido_sha256_test_update", (context, 0, 0), expect_panic=True)
        check("sha256-reject-corrupt-" + name)
    cpu, events = create()
    for key_length in (0, 1, 32, 63, 64, 65, 131):
        key = bytes(index % 251 for index in range(key_length))
        cpu.mem_write(data_base + 2048, key or b"\0")
        for length in (0, 1, 55, 64, 65, 129, 1024):
            message = bytes((index * 7) % 251 for index in range(length))
            cpu.mem_write(data_base, message or b"\0")
            expected = hmac.new(key, message, hashlib.sha256).digest()
            call(cpu, events, "mido_hmac_test_oneshot", (key_length, data_base + 2048, length, data_base, data_base + 6144))
            check(f"hmac-oneshot-{key_length}-{length}", bytes(cpu.mem_read(data_base + 6144, 32)) == expected)
            call(cpu, events, "mido_hmac_test_init", (context, key_length, data_base + 2048))
            split = min(length, 17)
            call(cpu, events, "mido_hmac_test_update", (context, split, data_base))
            call(cpu, events, "mido_hmac_test_update", (context, length - split, data_base + split))
            call(cpu, events, "mido_hmac_test_final", (context, data_base + 6144))
            check(f"hmac-stream-{key_length}-{length}", bytes(cpu.mem_read(data_base + 6144, 32)) == expected)
    cpu.mem_write(data_base, b"Hi There")
    cpu.mem_write(data_base + 2048, bytes([0x0b]) * 20)
    call(cpu, events, "mido_hmac_test_oneshot", (20, data_base + 2048, 8, data_base, data_base + 6144))
    check("hmac-fixed-known-answer", bytes(cpu.mem_read(data_base + 6144, 32)).hex() ==
          "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7")
    for name, function, arguments, initialized in (
        ("uninitialized", "mido_hmac_test_final", (context, data_base), False),
        ("unaligned", "mido_hmac_test_init", (context + 1, 0, 0), False),
        ("null-key", "mido_hmac_test_init", (context, 1, 0), False),
        ("overlap-key", "mido_hmac_test_init", (context, 1, context + 120), False),
        ("overlap-input", "mido_hmac_test_update", (context, 1, context + 120), True),
        ("overlap-output", "mido_hmac_test_final", (context, context + 112), True),
        ("null-input", "mido_hmac_test_update", (context, 1, 0), True),
        ("null-output", "mido_hmac_test_final", (context, 0), True),
    ):
        cpu, events = create()
        if initialized:
            call(cpu, events, "mido_hmac_test_init", (context, 0, 0))
        call(cpu, events, function, arguments, expect_panic=True)
        check("hmac-reject-" + name)
    cpu, events = create()
    for algorithm, name in enumerate(("md5", "sha1", "sha256", "sha384", "sha512"), 1):
        for length in (0, 1, 55, 56, 63, 64, 65, 111, 112, 119, 127, 128, 129, 1024):
            message = bytes((index * 13) % 251 for index in range(length))
            expected = hashlib.new(name, message).digest()
            cpu.mem_write(data_base, message or b"\0")
            call(cpu, events, "mido_digest_test_oneshot", (algorithm, length, data_base, data_base + 6144))
            check(f"digest-{name}-oneshot-{length}", bytes(cpu.mem_read(data_base + 6144, len(expected))) == expected)
            call(cpu, events, "mido_digest_test_init", (algorithm, context))
            split = min(length, 61)
            call(cpu, events, "mido_digest_test_update", (algorithm, context, split, data_base))
            call(cpu, events, "mido_digest_test_update", (algorithm, context, length - split, data_base + split))
            call(cpu, events, "mido_digest_test_final", (algorithm, context, data_base + 6144))
            check(f"digest-{name}-stream-{length}", bytes(cpu.mem_read(data_base + 6144, len(expected))) == expected)
    call(cpu, events, "mido_digest_test_init", (0, context), expect_panic=True)
    check("digest-reject-unsupported-algorithm")
    cpu, events = create()
    for algorithm, name in enumerate(("md5", "sha1", "sha256", "sha384", "sha512"), 1):
        for key_length in (0, 63, 64, 65, 127, 128, 129, 200):
            key = bytes(index % 251 for index in range(key_length))
            cpu.mem_write(data_base + 2048, key or b"\0")
            for length in (0, 111, 128, 1024):
                message = bytes((index * 17) % 251 for index in range(length))
                cpu.mem_write(data_base, message or b"\0")
                expected = hmac.new(key, message, name).digest()
                call(cpu, events, "mido_hmac_all_test_oneshot",
                     (algorithm, key_length, data_base + 2048, length, data_base, data_base + 6144))
                check(f"all-hmac-{name}-{key_length}-{length}-oneshot",
                      bytes(cpu.mem_read(data_base + 6144, len(expected))) == expected)
                call(cpu, events, "mido_hmac_all_test_init", (algorithm, context, key_length, data_base + 2048))
                split = min(length, 73)
                call(cpu, events, "mido_hmac_all_test_update", (algorithm, context, split, data_base))
                call(cpu, events, "mido_hmac_all_test_update", (algorithm, context, length - split, data_base + split))
                call(cpu, events, "mido_hmac_all_test_final", (algorithm, context, data_base + 6144))
                check(f"all-hmac-{name}-{key_length}-{length}-stream",
                      bytes(cpu.mem_read(data_base + 6144, len(expected))) == expected)
    call(cpu, events, "mido_hmac_all_test_init", (0, context, 0, 0), expect_panic=True)
    check("all-hmac-reject-unsupported-algorithm")
    for algorithm, block_size, state_size in ((1, 64, 16), (2, 64, 20), (3, 64, 32), (4, 128, 64), (5, 128, 64)):
        cpu, events = create()
        call(cpu, events, "mido_digest_test_init", (algorithm, context))
        cpu.mem_write(context + 8 + state_size + block_size, block_size.to_bytes(4, "little"))
        call(cpu, events, "mido_digest_test_update", (algorithm, context, 0, 0), expect_panic=True)
        check(f"digest-reject-corrupt-buffer-{algorithm}")
        cpu, events = create()
        call(cpu, events, "mido_hmac_all_test_init", (algorithm, context, 0, 0))
        call(cpu, events, "mido_hmac_all_test_update", (algorithm, context, 1, context + 110), expect_panic=True)
        check(f"all-hmac-reject-full-context-alias-{algorithm}")
        cpu, events = create()
        call(cpu, events, "mido_hmac_all_test_final", (algorithm, context, data_base), expect_panic=True)
        check(f"all-hmac-reject-uninitialized-{algorithm}")
    aes_context, aes_input, aes_output = data_base, data_base + 1024, data_base + 3072
    aes_iv, aes_key = data_base + 7008, data_base + 7040
    nist_key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    nist_iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    nist_input = bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")
    nist_output = bytes.fromhex("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2")
    reference_cipher = Cipher(algorithms.AES(nist_key), modes.CBC(nist_iv)).encryptor()
    check("aes-reference-nist-sp800-38a", reference_cipher.update(nist_input) + reference_cipher.finalize() == nist_output)
    cpu, events = create()
    cpu.mem_write(aes_key, nist_key)
    cpu.mem_write(aes_iv, nist_iv)
    cpu.mem_write(aes_input, nist_input)
    call(cpu, events, "mido_aes_test_init", (0, aes_context, 16, aes_key))
    check("aes-native-nist-sp800-38a",
          call(cpu, events, "mido_aes_test_update", (0, aes_context, aes_iv, 2, aes_input, aes_output)) == 0 and
          bytes(cpu.mem_read(aes_output, len(nist_output))) == nist_output)
    for key_pointer in (0, aes_context, aes_context + 256, (1 << 64) - 8):
        call(cpu, events, "mido_aes_test_init", (0, aes_context, 16, aes_key))
        check(f"aes-reject-invalid-key-pointer-{key_pointer}",
              call(cpu, events, "mido_aes_test_init", (0, aes_context, 16, key_pointer)) != 0 and
              bytes(cpu.mem_read(aes_context, 272)) == bytes(272))
    for key_length in (16, 24, 32):
        key = bytes((index * 7 + key_length) % 256 for index in range(key_length))
        for blocks in (0, 1, 2, 3, 4, 17, 64):
            plain = bytes((index * 13 + blocks) % 256 for index in range(blocks * 16))
            reference_cipher = Cipher(algorithms.AES(key), modes.CBC(nist_iv)).encryptor()
            encrypted = reference_cipher.update(plain) + reference_cipher.finalize()
            for decrypt in (0, 1):
                aes_source, expected = (encrypted, plain) if decrypt else (plain, encrypted)
                for inplace in (0, 1):
                    cpu, events = create()
                    cpu.mem_write(aes_key, key)
                    cpu.mem_write(aes_iv, nist_iv)
                    cpu.mem_write(aes_input, aes_source or b"\0")
                    destination = aes_input if inplace else aes_output
                    cpu.mem_write(destination + len(aes_source), b"guard")
                    check(f"aes-init-{key_length}-{blocks}-{decrypt}-{inplace}",
                          call(cpu, events, "mido_aes_test_init", (decrypt, aes_context, key_length, aes_key)) == 0)
                    context_size = call(cpu, events, "mido_aes_test_size")
                    check("aes-context-fits-original-allocation", context_size <= 280)
                    original_context = bytes(cpu.mem_read(aes_context, context_size))
                    first = min(blocks, 1)
                    for start, count in ((0, first), (first, blocks - first)):
                        check(f"aes-cbc-return-{key_length}-{blocks}-{decrypt}-{inplace}-{start}",
                              call(cpu, events, "mido_aes_test_update",
                                   (decrypt, aes_context, aes_iv, count, aes_input + start * 16, destination + start * 16)) == 0)
                    expected_iv = encrypted[-16:] if blocks else nist_iv
                    check(f"aes-cbc-reference-{key_length}-{blocks}-{decrypt}-{inplace}",
                          bytes(cpu.mem_read(destination, len(expected))) == expected and
                          bytes(cpu.mem_read(aes_iv, 16)) == expected_iv and
                          bytes(cpu.mem_read(aes_context, context_size)) == original_context and
                          bytes(cpu.mem_read(destination + len(expected), 5)) == b"guard")
    for name, arguments in (
        ("uninitialized", (0, aes_context, aes_iv, 1, aes_input, aes_output)),
        ("wrong-direction", (1, aes_context, aes_iv, 1, aes_input, aes_output)),
        ("misaligned-context", (0, aes_context + 1, aes_iv, 1, aes_input, aes_output)),
        ("null-context", (0, 0, aes_iv, 1, aes_input, aes_output)),
        ("null-iv", (0, aes_context, 0, 1, aes_input, aes_output)),
        ("misaligned-iv", (0, aes_context, aes_iv + 1, 1, aes_input, aes_output)),
        ("null-input", (0, aes_context, aes_iv, 1, 0, aes_output)),
        ("null-output", (0, aes_context, aes_iv, 1, aes_input, 0)),
        ("partial-overlap", (0, aes_context, aes_iv, 1, aes_input, aes_input + 1)),
        ("partial-overlap-reverse", (0, aes_context, aes_iv, 1, aes_input + 1, aes_input)),
        ("iv-input-alias", (0, aes_context, aes_iv, 1, aes_iv, aes_output)),
        ("iv-output-alias", (0, aes_context, aes_iv, 1, aes_input, aes_iv)),
        ("context-input-alias", (0, aes_context, aes_iv, 1, aes_context, aes_output)),
        ("context-output-alias", (0, aes_context, aes_iv, 1, aes_input, aes_context)),
        ("context-iv-alias", (0, aes_context, aes_context, 1, aes_input, aes_output)),
        ("length-overflow", (0, aes_context, aes_iv, 1 << 60, aes_input, aes_output)),
        ("input-range-overflow", (0, aes_context, aes_iv, 1, (1 << 64) - 8, aes_output)),
        ("output-range-overflow", (0, aes_context, aes_iv, 1, aes_input, (1 << 64) - 8)),
    ):
        cpu, events = create()
        cpu.mem_write(aes_key, nist_key)
        cpu.mem_write(aes_iv, nist_iv)
        if name != "uninitialized":
            call(cpu, events, "mido_aes_test_init", (0, aes_context, 16, aes_key))
        before = bytes(cpu.mem_read(data_base, 8192))
        result = call(cpu, events, "mido_aes_test_update", arguments)
        check("aes-reject-" + name, result != 0 and bytes(cpu.mem_read(data_base, 8192)) == before)
    for key_length in (0, 1, 15, 17, 23, 25, 31, 33, 128, 256):
        cpu, events = create()
        cpu.mem_write(aes_key, nist_key)
        call(cpu, events, "mido_aes_test_init", (0, aes_context, 16, aes_key))
        check(f"aes-reject-key-length-{key_length}",
              call(cpu, events, "mido_aes_test_init", (0, aes_context, key_length, aes_key)) != 0 and
              bytes(cpu.mem_read(aes_context, 272)) == bytes(272))
        check("aes-failed-reinit-invalidates-context",
              call(cpu, events, "mido_aes_test_update", (0, aes_context, aes_iv, 0, 0, 0)) != 0)
    ctr_iv = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    ctr_nist = bytes.fromhex("874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff")
    reference_cipher = Cipher(algorithms.AES(nist_key), modes.CTR(ctr_iv)).encryptor()
    check("ctr-reference-nist-sp800-38a", reference_cipher.update(nist_input) + reference_cipher.finalize() == ctr_nist)
    for key_length in (16, 24, 32):
        key = bytes(range(key_length))
        for iv in (ctr_iv, bytes.fromhex("000000000000000000000000fffffffe")):
            for length in (0, 1, 15, 16, 17, 31, 32, 33, 127, 128, 129, 1024):
                plain = bytes((index * 17 + length) % 256 for index in range(length))
                reference_cipher = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
                expected = reference_cipher.update(plain) + reference_cipher.finalize()
                for inplace in (0, 1):
                    cpu, events = create()
                    cpu.mem_write(aes_key, key)
                    cpu.mem_write(aes_iv, iv)
                    cpu.mem_write(aes_input, plain or b"\0")
                    destination = aes_input if inplace else aes_output
                    cpu.mem_write(destination + length, b"guard")
                    check("ctr-init", call(cpu, events, "mido_ctr_test_init", (aes_context, key_length, aes_key, aes_iv)) == 0)
                    offset = 0
                    for chunk in (0, min(length, 1), min(max(length - 1, 0), 16), max(length - 17, 0)):
                        check("ctr-split-return", call(cpu, events, "mido_ctr_test_update",
                              (aes_context, chunk, aes_input + offset, destination + offset)) == 0)
                        offset += chunk
                    check(f"ctr-reference-{key_length}-{iv.hex()}-{length}-{inplace}",
                          offset == length and bytes(cpu.mem_read(destination, length)) == expected and
                          bytes(cpu.mem_read(destination + length, 5)) == b"guard" and bytes(cpu.mem_read(aes_iv, 16)) == iv)
                    check("ctr-reset-discards-partial-stream", call(cpu, events, "mido_ctr_test_set_counter", (aes_context, aes_iv)) == 0)
                    cpu.mem_write(aes_input, plain or b"\0")
                    check("ctr-reset-one-shot", call(cpu, events, "mido_ctr_test_update", (aes_context, length, aes_input, destination)) == 0 and
                          bytes(cpu.mem_read(destination, length)) == expected)
                    cpu.mem_write(aes_input, expected or b"\0")
                    call(cpu, events, "mido_ctr_test_set_counter", (aes_context, aes_iv))
                    check("ctr-decrypt", call(cpu, events, "mido_ctr_test_update", (aes_context, length, aes_input, destination)) == 0 and
                          bytes(cpu.mem_read(destination, length)) == plain)
    cpu, events = create()
    cpu.mem_write(aes_key, nist_key)
    cpu.mem_write(aes_iv, ctr_iv)
    cpu.mem_write(aes_input, nist_input)
    call(cpu, events, "mido_ctr_test_init", (aes_context, 16, aes_key, aes_iv))
    check("ctr-native-nist-sp800-38a", call(cpu, events, "mido_ctr_test_update", (aes_context, 32, aes_input, aes_output)) == 0 and
          bytes(cpu.mem_read(aes_output, 32)) == ctr_nist)
    for last_counter, allowed in (((1 << 128) - 1, 16), ((1 << 128) - 2, 32)):
        cpu.mem_write(aes_iv, last_counter.to_bytes(16, "big"))
        call(cpu, events, "mido_ctr_test_set_counter", (aes_context, aes_iv))
        before = bytes(cpu.mem_read(data_base, 8192))
        check("ctr-reject-wrap-before-output", call(cpu, events, "mido_ctr_test_update",
              (aes_context, allowed + 1, aes_input, aes_output)) != 0 and bytes(cpu.mem_read(data_base, 8192)) == before)
        for chunk in (1, allowed - 2, 1):
            check("ctr-allow-final-counter-buffer", call(cpu, events, "mido_ctr_test_update",
                  (aes_context, chunk, aes_input, aes_output)) == 0)
        before = bytes(cpu.mem_read(data_base, 8192))
        check("ctr-reject-exhausted", call(cpu, events, "mido_ctr_test_update",
              (aes_context, 1, aes_input, aes_output)) != 0 and bytes(cpu.mem_read(data_base, 8192)) == before)
        check("ctr-exhausted-zero-length", call(cpu, events, "mido_ctr_test_update", (aes_context, 0, 0, 0)) == 0)
    for name, arguments in (
        ("uninitialized", (aes_context, 1, aes_input, aes_output)),
        ("null-context", (0, 1, aes_input, aes_output)),
        ("misaligned-context", (aes_context + 1, 1, aes_input, aes_output)),
        ("null-input", (aes_context, 1, 0, aes_output)),
        ("null-output", (aes_context, 1, aes_input, 0)),
        ("partial-overlap", (aes_context, 16, aes_input, aes_input + 1)),
        ("context-input", (aes_context, 1, aes_context, aes_output)),
        ("context-output", (aes_context, 1, aes_input, aes_context)),
        ("wrapped-input", (aes_context, 16, (1 << 64) - 8, aes_output)),
        ("wrapped-output", (aes_context, 16, aes_input, (1 << 64) - 8)),
    ):
        cpu, events = create()
        cpu.mem_write(aes_key, nist_key)
        cpu.mem_write(aes_iv, ctr_iv)
        if name != "uninitialized":
            call(cpu, events, "mido_ctr_test_init", (aes_context, 16, aes_key, aes_iv))
        before = bytes(cpu.mem_read(data_base, 8192))
        check("ctr-reject-" + name, call(cpu, events, "mido_ctr_test_update", arguments) != 0 and
              bytes(cpu.mem_read(data_base, 8192)) == before)
    cpu, events = create()
    ctr_size = call(cpu, events, "mido_ctr_test_size")
    check("ctr-context-size", 272 < ctr_size <= 512 and ctr_size % 16 == 0)
    cpu.mem_write(aes_key, nist_key)
    cpu.mem_write(aes_iv, ctr_iv)
    call(cpu, events, "mido_ctr_test_init", (aes_context, 16, aes_key, aes_iv))
    call(cpu, events, "mido_ctr_test_update", (aes_context, 1, aes_input, aes_output))
    for pointer in (0, aes_context, aes_context + ctr_size - 8, (1 << 64) - 8):
        before = bytes(cpu.mem_read(data_base, 8192))
        check("ctr-reject-invalid-reset", call(cpu, events, "mido_ctr_test_set_counter", (aes_context, pointer)) != 0 and
              bytes(cpu.mem_read(data_base, 8192)) == before)
    for key_length, key_pointer, iv_pointer in ((15, aes_key, aes_iv), (16, 0, aes_iv),
            (16, aes_context, aes_iv), (16, aes_key, 0), (16, aes_key, aes_context),
            (16, (1 << 64) - 8, aes_iv), (16, aes_key, (1 << 64) - 8)):
        call(cpu, events, "mido_ctr_test_init", (aes_context, 16, aes_key, aes_iv))
        check("ctr-failed-reinit-clears-context", call(cpu, events, "mido_ctr_test_init",
              (aes_context, key_length, key_pointer, iv_pointer)) != 0 and
              bytes(cpu.mem_read(aes_context, ctr_size)) == bytes(ctr_size))
    xts_tweak, xts_second_key = data_base + 6400, aes_key + 64
    for key_length in (16, 32):
        data_key = bytes(range(key_length))
        tweak_key = bytes(index + 64 for index in range(key_length))
        for iv in (bytes(16), bytes(range(16))):
            for blocks in (1, 2, 3, 16, 31, 64):
                plain = bytes((index * 29 + blocks) % 256 for index in range(blocks * 16))
                reference_cipher = Cipher(algorithms.AES(data_key + tweak_key), modes.XTS(iv)).encryptor()
                encrypted = reference_cipher.update(plain) + reference_cipher.finalize()
                for decrypt in (0, 1):
                    xts_source, expected = (encrypted, plain) if decrypt else (plain, encrypted)
                    for inplace in (0, 1):
                        cpu, events = create()
                        cpu.mem_write(aes_key, data_key)
                        cpu.mem_write(xts_second_key, tweak_key)
                        cpu.mem_write(aes_iv, iv)
                        cpu.mem_write(aes_input, xts_source)
                        destination = aes_input if inplace else aes_output
                        cpu.mem_write(destination + len(xts_source), b"guard")
                        check("xts-init", call(cpu, events, "mido_xts_test_init",
                              (decrypt, aes_context, key_length, aes_key, xts_second_key)) == 0)
                        xts_size = call(cpu, events, "mido_xts_test_size")
                        original_context = bytes(cpu.mem_read(aes_context, xts_size))
                        check("xts-set-tweak", call(cpu, events, "mido_xts_test_set_tweak",
                              (decrypt, aes_context, xts_tweak, aes_iv)) == 0)
                        first = min(blocks, 1)
                        for start, count in ((0, first), (first, blocks - first)):
                            check("xts-return-tweak-pointer", call(cpu, events, "mido_xts_test_update",
                                  (decrypt, aes_context, xts_tweak, count, aes_input + start * 16, destination + start * 16)) == xts_tweak)
                        check(f"xts-reference-{key_length}-{iv.hex()}-{blocks}-{decrypt}-{inplace}",
                              bytes(cpu.mem_read(destination, len(expected))) == expected and
                              bytes(cpu.mem_read(destination + len(expected), 5)) == b"guard" and
                              bytes(cpu.mem_read(aes_context, xts_size)) == original_context and
                              bytes(cpu.mem_read(aes_iv, 16)) == iv)
    for name, arguments in (
        ("uninitialized", (0, aes_context, xts_tweak, 1, aes_input, aes_output)),
        ("wrong-direction", (1, aes_context, xts_tweak, 1, aes_input, aes_output)),
        ("missing-tweak-init", (0, aes_context, xts_tweak, 1, aes_input, aes_output)),
        ("null-context", (0, 0, xts_tweak, 1, aes_input, aes_output)),
        ("misaligned-context", (0, aes_context + 1, xts_tweak, 1, aes_input, aes_output)),
        ("null-tweak", (0, aes_context, 0, 1, aes_input, aes_output)),
        ("misaligned-tweak", (0, aes_context, xts_tweak + 1, 1, aes_input, aes_output)),
        ("context-tweak-alias", (0, aes_context, aes_context, 1, aes_input, aes_output)),
        ("null-input", (0, aes_context, xts_tweak, 1, 0, aes_output)),
        ("null-output", (0, aes_context, xts_tweak, 1, aes_input, 0)),
        ("context-input", (0, aes_context, xts_tweak, 1, aes_context, aes_output)),
        ("context-output", (0, aes_context, xts_tweak, 1, aes_input, aes_context)),
        ("tweak-input", (0, aes_context, xts_tweak, 1, xts_tweak, aes_output)),
        ("tweak-output", (0, aes_context, xts_tweak, 1, aes_input, xts_tweak)),
        ("partial-overlap", (0, aes_context, xts_tweak, 1, aes_input, aes_input + 1)),
        ("data-unit-limit", (0, aes_context, xts_tweak, (1 << 20) + 1, aes_input, aes_output)),
        ("length-overflow", (0, aes_context, xts_tweak, 1 << 60, aes_input, aes_output)),
        ("input-range-overflow", (0, aes_context, xts_tweak, 1, (1 << 64) - 8, aes_output)),
        ("output-range-overflow", (0, aes_context, xts_tweak, 1, aes_input, (1 << 64) - 8)),
    ):
        cpu, events = create()
        cpu.mem_write(aes_key, bytes(range(16)))
        cpu.mem_write(xts_second_key, bytes(range(64, 80)))
        cpu.mem_write(aes_iv, bytes(16))
        if name != "uninitialized":
            call(cpu, events, "mido_xts_test_init", (0, aes_context, 16, aes_key, xts_second_key))
        if name not in ("uninitialized", "missing-tweak-init"):
            call(cpu, events, "mido_xts_test_set_tweak", (0, aes_context, xts_tweak, aes_iv))
        before = bytes(cpu.mem_read(data_base, 8192))
        call(cpu, events, "mido_xts_test_update", arguments, expect_panic=True)
        check("xts-reject-" + name, bytes(cpu.mem_read(data_base, 8192)) == before)
    cpu, events = create()
    cpu.mem_write(aes_key, bytes(range(16)))
    cpu.mem_write(xts_second_key, bytes(range(64, 80)))
    cpu.mem_write(aes_iv, bytes(16))
    for key_length, second_pointer in ((0, xts_second_key), (24, xts_second_key), (16, aes_key)):
        call(cpu, events, "mido_xts_test_init", (0, aes_context, 16, aes_key, xts_second_key))
        xts_size = call(cpu, events, "mido_xts_test_size")
        check("xts-reject-keys", call(cpu, events, "mido_xts_test_init",
              (0, aes_context, key_length, aes_key, second_pointer)) != 0 and
              bytes(cpu.mem_read(aes_context, xts_size)) == bytes(xts_size))
    call(cpu, events, "mido_xts_test_schedule", (0, aes_context, 16, aes_key, xts_second_key))
    call(cpu, events, "mido_xts_test_set_tweak", (0, aes_context, xts_tweak, aes_iv))
    cpu.mem_write(xts_tweak + 16, ((1 << 20) - 1).to_bytes(8, "little"))
    before = bytes(cpu.mem_read(data_base, 8192))
    call(cpu, events, "mido_xts_test_update", (0, aes_context, xts_tweak, 2, aes_input, aes_output), expect_panic=True)
    check("xts-streaming-limit-is-atomic", bytes(cpu.mem_read(data_base, 8192)) == before)
    check("xts-final-block-allowed", call(cpu, events, "mido_xts_test_update",
          (0, aes_context, xts_tweak, 1, aes_input, aes_output)) == xts_tweak)
    check("xts-exhausted-zero-length", call(cpu, events, "mido_xts_test_update", (0, aes_context, xts_tweak, 0, 0, 0)) == xts_tweak)
    call(cpu, events, "mido_xts_test_update", (0, aes_context, xts_tweak, 1, aes_input, aes_output), expect_panic=True)
    check("xts-exhausted-fails-closed")
    call(cpu, events, "mido_xts_test_schedule", (0, aes_context, 16, aes_key, aes_key), expect_panic=True)
    check("xts-void-key-schedule-fails-closed")
    for expected in (source_hashes, abi_hashes, header_hashes, harness_hashes):
        require_unchanged_inputs(workspace, expected)
    verify_dependency(workspace / "artifacts/bearssl-0.6.tar.gz", source)
    report = dict(scope=__doc__, passed=passed, expected_panics=panics,
                  independent_aes_reference="cryptography " + cryptography.__version__,
                  dependency_archive_sha256=ARCHIVE_SHA256, code_sha256=hashlib.sha256(payload).hexdigest(),
                  original_xnu_registration_executed=False, kernel_provider_registered=False,
                  phone_image_changed=False, boot_approved=False, compilation_commands=commands,
                  abi_header_sha256=abi_hashes, port_header_sha256=header_hashes,
                  source_sha256=source_hashes, harness_sha256=harness_hashes, inputs_unchanged=True,
                  warning="Synthetic recipient, lock and entropy services only. No original XNU execution or real kernel locks are proven.")
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
