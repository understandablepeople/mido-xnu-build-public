#include <cassert>
#include <cstdint>
#include <cstring>
static unsigned mode, calls, scenario;
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 10); }
static bool PE_parse_boot_argn(const char *name, void *output, int bytes)
{
    if (std::strcmp(name, "midogpusecure")) return false;
    assert(bytes == sizeof(mode));
    std::memcpy(output, &mode, bytes);
    return true;
}
struct mido_scm_registers;
static void invoke(mido_scm_registers *state);
#define MIDO_SCM_INVOKE(state) invoke(state)
#include "mido_gpu_secure.h"
static void invoke(mido_scm_registers *state)
{
    calls++;
    if (calls <= 2) {
        assert(state->values[0] == 0xc2000601U && state->values[1] == 1);
        assert(state->values[2] == (calls == 1 ? 0x82000601U : 0x02000c02U));
        state->values[0] = 0;
        state->values[1] = scenario == calls ? 0 : 1;
        return;
    }
    assert(state->values[0] == 0x42000c02U && state->values[1] == 2);
    assert(state->values[2] == 18 && !state->values[3] && !state->values[4]);
    state->values[0] = scenario == 3 ? 0xfffffffeU : 0;
    state->values[1] = scenario == 4 ? 7 : 0;
}
int main()
{
    mode = 0; assert(mido_gpu_secure_restore(1) == 0 && !calls);
    mode = 2; assert(mido_gpu_secure_restore(1) == -1 && !calls);
    mode = 1; assert(mido_gpu_secure_restore(0) == -1 && !calls);
    assert(mido_gpu_secure_restore(-1) == -1 && !calls);
    assert(mido_gpu_secure_restore(1) == 1 && calls == 3);
    for (unsigned selected = 1; selected <= 4; selected++) {
        calls = 0; scenario = selected;
        assert(mido_gpu_secure_restore(1) == -int(selected + 1));
        assert(calls == (selected < 3 ? selected : 3));
    }
    return 0;
}
