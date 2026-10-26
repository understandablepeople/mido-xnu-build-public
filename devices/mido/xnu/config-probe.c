#include <pexpert/arm64/board_config.h>
#include <arm64/proc_reg.h>

#if !defined(MIDO) || !defined(ARM64_BOARD_CONFIG_MIDO)
#error Expected the dedicated MIDO configuration
#endif
#if defined(BCM2837) || defined(PI3_UART) || defined(USE_APPLEARMSMP)
#error A foreign platform configuration leaked into MIDO
#endif
#if HAS_APPLE_PAC || XNU_MONITOR || PMAP_CS
#error Apple platform features must not be enabled in this scaffold
#endif

_Static_assert(sizeof(void *) == 8, "AArch64 pointers");
_Static_assert(__ARM_ARCH__ == 8, "ARMv8 baseline");
_Static_assert(MAX_CPUS == 1, "single CPU bring-up limit");
_Static_assert(MAX_CPU_CLUSTERS == 1, "single cluster bring-up limit");
_Static_assert(MAX_L2_CLINE == 6, "64-byte cache line");
_Static_assert(MMU_I_CLINE == 6 && MMU_CLINE == 6, "cache line definitions");
_Static_assert(CORE_NCTRS == 0, "PMU backend not implemented");
_Static_assert(NO_MONITOR == 1, "no Apple monitor");
_Static_assert(TCR_TG0_GRANULE_SIZE == TCR_TG0_GRANULE_4KB, "4KB TTBR0 granule");
_Static_assert(TCR_TG1_GRANULE_SIZE == TCR_TG1_GRANULE_4KB, "4KB TTBR1 granule");

int mido_config_probe(void)
{
    return MAX_CPUS;
}
