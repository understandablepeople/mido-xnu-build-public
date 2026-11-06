#include <string.h>
#include "../gpu/mido_gpu_power.h"

static uint32_t host_values[MIDO_GPU_REGISTER_COUNT];
static unsigned host_reads;
static int host_failure;
static int host_bad_offset;

static int
host_read(void *context, uint32_t offset, uint32_t *value)
{
    static const uint32_t expected[] = {0x59000, 0x59004, 0x5904c, 0x5901c,
        0x59020, 0x59028, 0x59030, 0x59040, 0x59044, 0x5b00c, 0x5f01c, 0x5f028};
    (void)context;
    unsigned index = host_reads++;
    if (index >= MIDO_GPU_REGISTER_COUNT || offset != expected[index] ||
        offset < MIDO_GPU_AUDIT_OFFSET ||
        offset + 4 > MIDO_GPU_AUDIT_OFFSET + MIDO_GPU_AUDIT_SIZE) {
        host_bad_offset = 1;
        return 0;
    }
    if ((int)index == host_failure) {
        return 0;
    }
    *value = host_values[index];
    return 1;
}

int
host_plan(uint64_t enable, uint64_t voltages, unsigned corner, struct mido_gfx_corner *result)
{
    return mido_gfx_plan(enable, voltages, corner, result);
}

int
host_snapshot(const uint32_t *values, int failure, struct mido_gpu_snapshot *result)
{
    memcpy(host_values, values, sizeof(host_values));
    host_reads = 0;
    host_bad_offset = 0;
    host_failure = failure;
    struct mido_gpu_reader reader = {NULL, host_read};
    return mido_gpu_snapshot_read(&reader, result);
}

uint32_t host_blockers(const struct mido_gpu_snapshot *snapshot)
{
    return mido_gpu_snapshot_blockers(snapshot);
}

unsigned host_read_count(void) { return host_reads; }
int host_offset_error(void) { return host_bad_offset; }
