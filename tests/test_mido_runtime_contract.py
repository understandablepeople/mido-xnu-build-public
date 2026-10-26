import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import unittest


WORKSPACE = Path(__file__).resolve().parent.parent
RUNTIME = WORKSPACE / "devices/mido/xnu/runtime"
NDK_CLANG = (Path.home() / "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/"
             "prebuilt/windows-x86_64/bin/clang.exe")
CLANG = os.environ.get("MIDO_RUNTIME_TEST_CLANG") or shutil.which("clang")
if not CLANG and NDK_CLANG.is_file():
    CLANG = str(NDK_CLANG)

CONTRACT = """
#ifndef MIDO_MODELED_CONTRACT
#define MIDO_MODELED_CONTRACT
typedef __UINT64_TYPE__ uint64_t;
typedef __UINT16_TYPE__ uint16_t;
typedef __UINT8_TYPE__ uint8_t;
typedef __SIZE_TYPE__ size_t;
typedef __UINTPTR_TYPE__ vm_offset_t;
typedef __SIZE_TYPE__ vm_size_t;
typedef int boolean_t;
typedef _Bool bool;
#define true 1
#define false 0
#define FALSE 0
#define NULL ((void *)0)
#define MIDO 1
#define NO_MONITOR 1
#define KERNEL 1
#define OS_FIREHOSE_SPI 1
typedef struct thread *thread_t;
typedef struct processor *processor_t;
typedef struct firehose_tracepoint_s *firehose_tracepoint_t;
typedef union firehose_buffer_u *firehose_buffer_t;
typedef uint8_t firehose_stream_t;
typedef union { uint64_t ftid_value; } firehose_tracepoint_id_u;
typedef struct { uint64_t fpr_mem_flushed_pos; uint64_t fpr_io_flushed_pos; } firehose_push_reply_t;
extern boolean_t kpc_off_cpu_active;
void kpc_off_cpu_internal(thread_t);
bool kperf_is_sampling(void);
int kperf_disable_sampling(void);
void kperf_reset(void);
void ml_enable_monitor(void);
void CleanPoC_DcacheRegion_Force(vm_offset_t, size_t);
void CleanPoC_DcacheRegion_Force_nopreempt_nohid(vm_offset_t, size_t);
__attribute__((noreturn)) void panic(const char *, ...);
#endif
"""


def headers(directory):
    (directory / "contract.h").write_text(CONTRACT, encoding="utf-8")
    for relative in ("pexpert/arm64/board_config.h", "kpc.h", "kperf.h", "kern/debug.h",
                     "kern/processor.h", "kern/kpc.h", "kperf/kperf.h",
                     "machine/machine_routines.h", "arm/caches_internal.h", "vm/pmap.h",
                     "firehose/tracepoint_private.h", "stdint.h"):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#include "contract.h"\n', encoding="utf-8")
    target = directory / "os/firehose_buffer_private.h"
    target.parent.mkdir(parents=True)
    target.write_bytes((WORKSPACE / "tools/vendor/firehose_buffer_private.h").read_bytes())


@unittest.skipUnless(CLANG, "Clang required for modeled freestanding ABI checks")
class MidoRuntimeContractTests(unittest.TestCase):
    def test_pinned_cache_backend_emits_generic_arm64_clean_and_barriers(self):
        from tools.prepare_xnu_tree import ARCHIVE_ROOT, ARCHIVE_SHA256
        archive = WORKSPACE / "artifacts/xnu-source-download-v1/xnu.tar.gz"
        disassembler = Path(CLANG).with_name("llvm-objdump.exe" if os.name == "nt" else "llvm-objdump")
        if not archive.is_file() or not disassembler.is_file():
            self.skipTest("pinned local archive and LLVM disassembler required")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), ARCHIVE_SHA256)
        with tarfile.open(archive) as sources:
            data = sources.extractfile(ARCHIVE_ROOT + "/osfmk/arm64/caches_asm.s").read().decode()
        start = data.index("LEXT(CleanPoC_DcacheRegion_internal)")
        end = data.rfind("/*", start, data.index("LEXT(FlushPoC_Dcache)", start))
        assembly = ("#define MMU_CLINE 6\n#define LEXT(name) name:\n#define EXT(name) name\n"
                    ".text\n" + data[start:end])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "cache.S"
            destination = directory / "cache.o"
            source.write_text(assembly, encoding="utf-8")
            result = subprocess.run([CLANG, "--target=aarch64-none-elf", "-c", str(source),
                                     "-o", str(destination)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(disassembler), "-d", str(destination)], capture_output=True,
                                    text=True, timeout=30, check=True)
            self.assertRegex(result.stdout, r"dc\s+cvac")
            self.assertRegex(result.stdout, r"dsb\s+sy")

    def compile(self, source, directory, extra=()):
        return subprocess.run([CLANG, "--target=aarch64-none-elf", "-std=c11", "-ffreestanding",
                               "-nostdinc", "-I", str(directory), "-Wall", "-Wextra", "-Werror",
                               "-Wmissing-prototypes", "-fsyntax-only", *extra, str(source)],
                              capture_output=True, text=True, timeout=30)

    def test_runtime_matches_modeled_kernel_and_real_firehose_declarations(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            headers(directory)
            for name in ("mido_runtime.c", "mido_ubsan.c"):
                with self.subTest(name=name):
                    result = self.compile(RUNTIME / name, directory)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_enabled_hardware_backends_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            headers(directory)
            for define in ("NKPC=1", "NKPERF=1", "XNU_MONITOR=1", "KERNEL_INTEGRITY_KTRR=1",
                           "KERNEL_INTEGRITY_CTRR=1", "APPLE_ARM64_ARCH_FAMILY=1"):
                with self.subTest(define=define):
                    result = self.compile(RUNTIME / "mido_runtime.c", directory, ["-D" + define])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("error:", result.stderr)

    def test_minimal_ubsan_handlers_do_not_instrument_themselves(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            headers(directory)
            destination = directory / "mido_ubsan.ll"
            result = subprocess.run([
                CLANG, "--target=aarch64-none-elf", "-std=c11", "-ffreestanding", "-nostdinc",
                "-I", str(directory), "-fsanitize=signed-integer-overflow,unsigned-integer-overflow",
                "-fsanitize-minimal-runtime", "-S", "-emit-llvm", str(RUNTIME / "mido_ubsan.c"),
                "-o", str(destination)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = destination.read_text()
            for operation in ("add", "sub", "mul", "divrem", "negate"):
                name = f"__ubsan_handle_{operation}_overflow_minimal"
                self.assertIn("@" + name + "(", data)
                self.assertIn("@" + name + "_abort(", data)
            self.assertNotRegex(data, r"call[^\n]*@__ubsan_handle_")
            self.assertIn("@panic(", data)


if __name__ == "__main__":
    unittest.main()
