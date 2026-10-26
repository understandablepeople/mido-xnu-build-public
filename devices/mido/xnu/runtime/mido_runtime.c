#include <pexpert/arm64/board_config.h>
#include <kpc.h>
#include <kperf.h>
#include <kern/debug.h>
#include <kern/processor.h>
#include <kern/kpc.h>
#include <kperf/kperf.h>
#include <machine/machine_routines.h>
#include <arm/caches_internal.h>
#include <vm/pmap.h>
#include <firehose/tracepoint_private.h>
#include <os/firehose_buffer_private.h>

#if !defined(MIDO) || !NO_MONITOR || XNU_MONITOR || KPC || KPERF || NKPC || NKPERF
#error MIDO runtime requires disabled Apple monitor, KPC and KPERF
#endif
#if defined(APPLE_ARM64_ARCH_FAMILY) || defined(KERNEL_INTEGRITY_KTRR) || defined(KERNEL_INTEGRITY_CTRR)
#error MIDO runtime must not replace Apple cache or memory protection implementations
#endif

boolean_t kpc_off_cpu_active = FALSE;

void
kpc_off_cpu_internal(thread_t thread)
{
    (void)thread;
    if (kpc_off_cpu_active) {
        panic("MIDO: KPC activated without a hardware backend");
    }
}

bool
kperf_is_sampling(void)
{
    return false;
}

int
kperf_disable_sampling(void)
{
    return 0;
}

void
kperf_reset(void)
{
}

void kptimer_running_setup(processor_t processor, uint64_t now);

void
kptimer_running_setup(processor_t processor, uint64_t now)
{
    (void)processor;
    (void)now;
}

void
ml_enable_monitor(void)
{
}

void
CleanPoC_DcacheRegion_Force_nopreempt_nohid(vm_offset_t address, size_t length)
{
    if (length == 0) {
        return;
    }
    if (length > ~(vm_offset_t)0 - address) {
        panic("MIDO: cache maintenance range overflow");
    }
    CleanPoC_DcacheRegion_Force(address, length);
}

firehose_tracepoint_t
__firehose_buffer_tracepoint_reserve(uint64_t stamp, firehose_stream_t stream,
    uint16_t public_size, uint16_t private_size, uint8_t **private_pointer)
{
    (void)stamp;
    (void)stream;
    (void)public_size;
    (void)private_size;
    if (private_pointer != NULL) {
        *private_pointer = NULL;
    }
    return NULL;
}

void
__firehose_buffer_tracepoint_flush(firehose_tracepoint_t tracepoint,
    firehose_tracepoint_id_u identifier)
{
    (void)identifier;
    if (tracepoint != NULL) {
        panic("MIDO: Firehose flush without an allocated tracepoint");
    }
}

firehose_buffer_t
__firehose_buffer_create(size_t *size)
{
    (void)size;
    panic("MIDO: Firehose transport is unavailable");
}

bool
__firehose_merge_updates(firehose_push_reply_t update)
{
    (void)update;
    return false;
}

int
__firehose_kernel_configuration_valid(uint8_t chunk_count, uint8_t io_pages)
{
    (void)chunk_count;
    (void)io_pages;
    return 0;
}
