#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "../gpu/mido_gpu_power.h"

int host_snapshot(const uint32_t *, int, struct mido_gpu_snapshot *);
unsigned host_read_count(void);

int
main(void)
{
    uint64_t random_bits = 0x8953;
    for (unsigned corner = 0; corner <= 8; corner++) {
        for (unsigned sample = 0; sample < 4096; sample++) {
            random_bits ^= random_bits << 13;
            random_bits ^= random_bits >> 7;
            random_bits ^= random_bits << 17;
            struct mido_gfx_corner plan = {0, 0, 0, 0, 0, 0};
            int valid = mido_gfx_plan(random_bits, ~random_bits, corner, &plan);
            assert(valid == (corner >= 1 && corner <= 7));
            if (valid && plan.ldo_mode) {
                assert(plan.voltage_uv >= 510000 && plan.voltage_uv <= 750000);
                assert(plan.vref <= 127);
            }
        }
    }
    struct mido_gpu_snapshot state;
    memset(&state, 0xa5, sizeof(state));
    struct mido_gpu_snapshot before = state;
    uint32_t values[MIDO_GPU_REGISTER_COUNT] = {0};
    for (int failure = 0; failure < MIDO_GPU_REGISTER_COUNT; failure++) {
        assert(!host_snapshot(values, failure, &state));
        assert(!memcmp(&state, &before, sizeof(state)));
        assert(host_read_count() == (unsigned)failure + 1);
    }
    assert(!mido_gpu_snapshot_read(NULL, &state));
    struct mido_gpu_reader invalid = {NULL, NULL};
    assert(!mido_gpu_snapshot_read(&invalid, &state));
    assert(!mido_gfx_plan(0, 0, 1, NULL));
    assert(mido_gpu_snapshot_blockers(NULL) == 63);
    return 0;
}
