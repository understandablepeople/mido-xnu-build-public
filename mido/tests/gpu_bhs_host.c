#include <assert.h>
#include <string.h>
#include "mido_gpu_bhs.h"

int
main(void)
{
    struct mido_gpu_bhs_step steps[MIDO_GPU_BHS_STEPS];
    memset(steps, 0xa5, sizeof(steps));
    struct mido_gpu_bhs_step saved[MIDO_GPU_BHS_STEPS];
    memcpy(saved, steps, sizeof(steps));
    assert(!mido_gpu_bhs_plan(0, 0, 1, steps, 12));
    assert(!mido_gpu_bhs_plan(0, 1, 0, steps, 12));
    assert(!mido_gpu_bhs_plan(0, 1, 1, steps, 11));
    assert(!mido_gpu_bhs_plan(0, 1, 1, NULL, 12));
    assert(!memcmp(saved, steps, sizeof(steps)));
    assert(mido_gpu_bhs_plan(0x80000038, 1, 1, steps, 12));
    assert(steps[0].value == 0x20000038);
    assert(steps[11].value == 0x20000038);
    assert(steps[2].offset == 0x5f004 && steps[2].value == 0x05008600);
    assert(steps[5].offset == 0x5f014 && steps[5].value == 0x004b1102);
    for (uint32_t seed = 0; seed < 65536; seed++) {
        uint32_t control = seed * 65537U;
        assert(mido_gpu_bhs_plan(control, 1, 1, steps, 12));
        uint32_t changed = (1U << 31) | (1U << 30) | (1U << 29) | (1U << 9) | 0x17U;
        assert((steps[11].value & ~changed) == (control & ~changed));
        assert((steps[11].value & changed) == ((1U << 29) | (1U << 4)));
    }
    return 0;
}
