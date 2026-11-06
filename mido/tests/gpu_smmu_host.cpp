#include <cassert>
#include <cstdint>
#include <cstring>
#include <initializer_list>
static unsigned mode, calls, phase, scenario, delays;
static uint32_t identity = 0x20000008, control = 0x1c;
static void IOLog(const char *, ...) {}
static void IODelay(unsigned) { delays++; }
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midogpusmmu") && size == sizeof(mode));
    std::memcpy(output, &mode, size);
    return true;
}
struct mido_scm_registers;
static void invoke(mido_scm_registers *state);
#define MIDO_SCM_INVOKE(state) invoke(state)
#include "mido_gpu_smmu.h"
static void invoke(mido_scm_registers *state)
{
    calls++;
    if (scenario >= 20) {
        if (scenario == 20) { state->values[0] = 0xfffffff4U; return; }
        if (scenario == 21) { state->values[0] = 1; return; }
        if (calls == 1) {
            state->values[0] = 1; state->values[6] = 0x123456; state->values[3] = 0x987654;
        } else {
            assert(state->values[0] == 1 && state->values[6] == 0x123456 && state->values[3] == 0x987654);
            state->values[0] = 0; state->values[1] = 0x55;
        }
        return;
    }
    phase++;
    if (phase <= 2) {
        assert(state->values[0] == 0xc2000601U && state->values[1] == 1);
        assert(state->values[2] == (phase == 1 ? 0x02000501U : 0x02000502U));
        state->values[0] = 0; state->values[1] = scenario == phase ? 0 : 1;
        return;
    }
    assert(state->values[0] == (phase == 5 ? 0xc2000502U : 0xc2000501U));
    assert(state->values[1] == (phase == 5 ? 2 : 1));
    assert(state->values[2] == (phase == 3 ? 0x01c40024 : 0x01c46000));
    assert(state->values[3] == (phase == 5 ? (control & ~4U) : 0));
    if (scenario == phase) {
        state->values[0] = 0xfffffffeU;
        return;
    }
    state->values[0] = 0;
    state->values[1] = phase == 3 ? identity : phase == 6 ? (control & ~4U) : control;
    if (scenario == 7 && phase == 6) state->values[1] |= 4;
    if (scenario == 8 && phase == 4) state->values[1] = 1ULL << 32;
}
static void reset(unsigned selected = 0)
{
    scenario = selected; calls = phase = delays = 0; mode = 1;
    identity = 0x20000008; control = 0x1c;
}
int main()
{
    reset(); mode = 0; assert(!mido_gpu_smmu_resume(1) && !calls);
    reset(); mode = 2; assert(mido_gpu_smmu_resume(1) == -1 && !calls);
    reset(); assert(mido_gpu_smmu_resume(0) == -1 && !calls);
    assert(mido_gpu_smmu_resume(-1) == -1 && !calls);
    reset(); assert(mido_gpu_smmu_resume(1) == 1 && calls == 6 && !delays);
    for (unsigned selected = 1; selected <= 8; selected++) {
        reset(selected);
        assert(mido_gpu_smmu_resume(1) < 0);
        assert(phase == (selected <= 6 ? selected : selected == 7 ? 6 : 4));
    }
    for (uint32_t invalid : {0U, UINT32_MAX, 0xa0000008U, 0x10000008U,
            0x20000000U, 0x20000009U, 0x20090008U}) {
        reset(); identity = invalid;
        assert(mido_gpu_smmu_resume(1) < 0 && phase == 3);
    }
    uint64_t returned = 999;
    reset();
    assert(mido_gpu_smmu_atomic(0xc2000502U, 2, 0x01c46004, 0, &returned) == -101 && !calls);
    assert(mido_gpu_smmu_atomic(0xc2000501U, 1, 0x01c013d4, 0, &returned) == -101 && !calls);
    assert(mido_gpu_smmu_atomic(0xc2000502U, 2, 0x01c46000, 1ULL << 32, &returned) == -101 && !calls);
    reset(20); assert(mido_gpu_smmu_atomic(0xc2000502U, 2, 0x01c46000, 0, &returned) == -12);
    assert(calls == 1 && !delays && !returned);
    reset(21); assert(mido_gpu_smmu_atomic(0xc2000501U, 1, 0x01c40024, 0, &returned) == -100);
    assert(calls == 8 && !returned);
    reset(22); assert(!mido_gpu_smmu_atomic(0xc2000501U, 1, 0x01c40024, 0, &returned));
    assert(calls == 2 && returned == 0x55);
    return 0;
}
