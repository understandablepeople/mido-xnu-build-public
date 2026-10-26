# Experimental bootstrap crypto integration

This opt-in build integrates the tested components into the actual XNU build
graph. It is deliberately not a complete crypto provider or an installable
phone image. The purpose is to execute original XNU registration and advance
the exact-image offline bootstrap beyond the observed null crypto-table fault.

Select --experimental-boot-crypto together with --attempt-kernel and iphoneos.
The ordinary build remains unchanged. The separate manual
mido-bootstrap-kernel workflow performs a full kernel build, not just another
object compilation audit. A successful build is not a successful boot.

The staging step verifies the pinned BearSSL archive and entire extracted
dependency tree, preserves its license, records staged hashes, and uses uniquely
prefixed source/object names to avoid colliding with XNU's existing hash and
HMAC objects. Compiler changes are per-file and limited to staged units.
The staged limits.h adapter includes XNU's genuine machine/limits.h, because
the kernel's -nostdinc build intentionally has no libc limits.h search path.
It does not invent integer limits or add a user-space SDK include directory.

The EARLY_BOOT/FIRST callback runs after LOCKS and PERCPU initialization and
before kmem_crypto_init at EARLY_BOOT/MIDDLE. It calls the original
register_crypto_functions and then the native-lock bridge, which calls the
original register_and_init_prng. No emulator injection or forced return is
part of this registration path. Execution of that path still requires proof
from the rebuilt kernel, not merely the presence of this source.

Supported callbacks use the tested digest/HMAC, AES CBC/CTR/XTS/GCM, CCRNG,
kmem random and kernel PRNG adapters. AES ECB, DES/TDES, CTS3, ChaCha20-Poly1305,
RSA and the newer enum-based digest/HMAC interfaces remain unavailable.
Their entries and descriptor methods are typed panic traps: they never report
success, fake a signature verification, provide dummy entropy, or silently
leave an unsupported callback null. These traps are for boot diagnostics,
not a claim of implementing the algorithms. A trap reached by the rebuilt
kernel identifies the next actual consumer to implement or legitimately disable.

This is an explicit exception to the previous full-table-before-integration
development gate, only for a clearly labeled diagnostic build. The complete
provider and production-readiness gates remain unmet. The unchanged platform-v5
image and prior isolated tests cannot establish registration or boot success
for this new build. IRQ/timer, console, physical-memory ownership and phone
boot approval remain separate gates; no phone command is authorized here.

## Non-Apple startup experiment

The first rebuilt kernel, Actions run 40254796891 at def1363, executes both
original registrations, returns from kmem_crypto_init and reaches the original
post-EARLY_BOOT IRQ-unmask boundary. It then panics in trust_cache_runtime_init:
image4 interface not available. BSD entry is not reached. The MIDO configuration
already omits config_img4; upstream startup.c nevertheless calls the Apple
trust-cache initializer unconditionally except on BCM2837.

A separate --mido-no-image4-boot opt-in extends that existing non-Apple startup
gate to MIDO. It is not enabled by --experimental-boot-crypto alone. The stager
requires the exact original startup.c hash and refuses a MIDO configuration
requesting config_img4. It does not change that configuration, trust-cache API
implementations, code-signature checks, or return successful signature results.
It only avoids initializing a proprietary service the platform does not supply.
Non-MIDO behavior is unchanged. The manual workflow requires the additional
approve_nonapple_boot input for this experiment.

This does not provide Image4, AMFI, Apple secure boot or a trusted user-space
execution chain. Later use of unavailable services can still fail or panic.
No phone boot or installation approval follows from this diagnostic gate.

## Rebuilt-image execution result

Actions run 40256185024 at d57412d completed a full kernel build with both
explicit options. The kernel SHA-256 is
5f5bd857d0f63fe7fa6782737ceac4549b96fa2e040649efb368a386e0ad3d10.
All 67 staged runtime/header/license inputs match local hashes; the startup
guard transformation also matches the recorded original and output hashes.

The new local platform-v7 image passes nine handoff, three original MMU entry
and eight copy scenarios. Its original execution reaches bsd_init after both
original registrations, kmem_crypto_init returning, EARLY_BOOT completing,
and original IRQ unmasking. The single BSD-entry trace captures these earlier
milestones as well, rather than assuming that entry alone proves them.
All 15 execution-input hashes remain unchanged; the offline boot-tree seed
is erased. Primary local evidence is c-bsd-entry-emulation.json in
artifacts/mido-xnu-platform-v7, also preserved in its offline ZIP bundle.

This proves BSD entry only, not BSD initialization completion, root mounting,
user-space execution, actual IRQ delivery or phone boot. The transfer still
uses a clearly labeled synthetic 64 MiB RAM window at 0x20000000. Device RAM
ownership and loader lifetimes must be reconciled with the saved memory/LK2ND
evidence before any hardware-load candidate is appropriate. GIC/timer and
complete runtime support remain separate work; do not flash this image.
