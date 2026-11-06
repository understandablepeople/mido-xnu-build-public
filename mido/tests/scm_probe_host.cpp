#include <cassert>
#include <cstdint>
#include <cstring>

static unsigned mode, calls, scenario, delays, pas6, pas13;
struct mido_scm_registers;
static void invoke(struct mido_scm_registers *state);
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 10); delays++; }
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midoscmprobe") && size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
#define MIDO_SCM_INVOKE(state) invoke(state)
#include "mido_scm_probe.h"
static void invoke(struct mido_scm_registers *state)
{
    calls++;
    if (state->values[0] == 1) {
        assert(scenario == 3 || scenario == 4);
        if (scenario == 3) {
            assert(calls == 2 && state->values[6] == 0x123456);
            assert(state->values[1] == 0x777);
        }
    } else {
        bool pas = state->values[0] == 0x42000207U || state->values[0] == 0x02000207U;
        assert(pas || state->values[0] == 0xc2000601U || state->values[0] == 0x82000601U);
        if (scenario == 2 && calls > 1) assert(state->values[0] == (pas ? 0x02000207U : 0x82000601U));
        assert(state->values[1] == 1);
        uint64_t query = state->values[2];
        if (pas) {
            assert(query == 6 || query == 13);
            if (query == 6) pas6++; else pas13++;
        }
        else assert(query == 0x82000601U || query == 0x02000201U || query == 0x02000202U ||
            query == 0x02000205U || query == 0x02000206U || query == 0x02000207U);
    }
    if (scenario == 1 || (scenario == 2 && calls == 1)) {
        state->values[0] = 0xffffffffU;
        state->values[1] = 0;
    } else if (scenario == 3 && calls == 1) {
        state->values[0] = 1; state->values[6] = 0x123456; state->values[1] = 0x777;
    } else if (scenario == 4) {
        state->values[0] = 1;
    } else if (scenario == 5) {
        state->values[0] = 0xfffffff4U;
    } else if (scenario == 6) {
        state->values[0] = 0; state->values[1] = 0;
    } else if (scenario == 7 && calls == 7) {
        state->values[0] = 0xfffffffeU; state->values[1] = 99;
    } else if (scenario == 9 && pas6 == 1 && pas13 == 0) {
        state->values[0] = 0; state->values[1] = 0;
    } else if (scenario == 10 && pas6 != 0) {
        state->values[0] = 0xfffffff4U;
    } else if (scenario == 8 && calls == 6) {
        state->values[0] = 0; state->values[1] = 0;
    } else {
        state->values[0] = 0; state->values[1] = 1;
    }
}
static void reset(unsigned selected = 0)
{
    scenario = selected; mode = 1; calls = delays = pas6 = pas13 = 0;
}
int main()
{
    reset(); mode = 0; mido_scm_probe(); assert(calls == 0);
    reset(); mode = 2; mido_scm_probe(); assert(calls == 0);
    reset(); mido_scm_probe(); assert(calls == 8);
    reset(1); mido_scm_probe(); assert(calls == 2);
    reset(2); mido_scm_probe(); assert(calls == 9);
    reset(3); mido_scm_probe(); assert(calls == 9);
    uint64_t available = 99;
    reset(4); assert(mido_scm_available(0x40000000, 0x02000201, &available) == -100);
    assert(calls == 8 && available == 0);
    reset(5); assert(mido_scm_available(0, 0x02000201, &available) == -12);
    assert(calls == 4 && delays == 4 && available == 0);
    reset(4); mido_scm_probe(); assert(calls == 8);
    reset(5); mido_scm_probe(); assert(calls == 4);
    reset(6); mido_scm_probe(); assert(calls == 2);
    reset(7); mido_scm_probe(); assert(calls == 7);
    reset(8); mido_scm_probe(); assert(calls == 6);
    reset(9); mido_scm_probe(); assert(calls == 8 && pas6 == 1 && pas13 == 1);
    reset(10); mido_scm_probe(); assert(calls == 10 && pas6 == 4 && pas13 == 0 && delays == 4);
    reset(4); assert(mido_scm_query(0x42000207U, 6, &available) == -100 && calls == 8);
    reset(7); calls = 6; available = 99;
    assert(mido_scm_query(0x42000207U, 6, &available) == -2 && available == 0);
    return 0;
}
