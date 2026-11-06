#ifndef MIDO_SCM_PROBE_H
#define MIDO_SCM_PROBE_H

struct mido_scm_registers {
    uint64_t values[7];
};

#ifndef MIDO_SCM_INVOKE
static void
mido_scm_invoke(struct mido_scm_registers *state)
{
    register uint64_t first __asm__("x0") = state->values[0];
    register uint64_t info __asm__("x1") = state->values[1];
    register uint64_t argument __asm__("x2") = state->values[2];
    register uint64_t third __asm__("x3") = state->values[3];
    register uint64_t fourth __asm__("x4") = state->values[4];
    register uint64_t fifth __asm__("x5") = state->values[5];
    register uint64_t context __asm__("x6") = state->values[6];
    __asm__ volatile("smc #0"
        : "+r"(first), "+r"(info), "+r"(argument), "+r"(third),
          "+r"(fourth), "+r"(fifth), "+r"(context)
        :
        : "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    state->values[0] = first;
    state->values[1] = info;
    state->values[2] = argument;
    state->values[3] = third;
    state->values[4] = fourth;
    state->values[5] = fifth;
    state->values[6] = context;
}
#define MIDO_SCM_INVOKE(state) mido_scm_invoke(state)
#endif

static int64_t
mido_scm_query(uint32_t function, uint32_t argument, uint64_t *available)
{
    *available = 0;
    for (unsigned busy = 0; busy < 4; busy++) {
        struct mido_scm_registers state = {{function, 1, argument, 0, 0, 0, 0}};
        for (unsigned interrupted = 0; interrupted < 8; interrupted++) {
            MIDO_SCM_INVOKE(&state);
            int64_t result = (int32_t)state.values[0];
            if (result == 1) {
                state.values[0] = 1;
                continue;
            }
            if (result != -12) {
                if (result == 0) {
                    *available = state.values[1];
                }
                return result;
            }
            break;
        }
        if ((int32_t)state.values[0] != -12) {
            return -100;
        }
        IODelay(10);
    }
    return -12;
}

static int64_t
mido_scm_available(uint32_t convention, uint32_t query, uint64_t *available)
{
    return mido_scm_query(0x82000601U | convention, query, available);
}

static void
mido_scm_probe(void)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midoscmprobe", &mode, sizeof(mode));
    if (mode == 0) {
        return;
    }
    if (mode != 1) {
        IOLog("MIDO SCM: unsupported probe mode=%u; no SMC\n", mode);
        return;
    }
    uint32_t convention = 0x40000000U;
    uint64_t available = 0;
    int64_t result = mido_scm_available(convention, 0x82000601U, &available);
    IOLog("MIDO SCM: SMC64 info-availability result=%lld available=%llu\n", result, available);
    if (result != 0 && result != -1) {
        IOLog("MIDO SCM: stopped on transport error; no convention fallback\n");
        return;
    }
    if (result != 0 || available == 0) {
        convention = 0;
        result = mido_scm_available(convention, 0x82000601U, &available);
        IOLog("MIDO SCM: SMC32 info-availability result=%lld available=%llu\n", result, available);
    }
    if (result != 0 || available == 0) {
        IOLog("MIDO SCM: no supported ARMv8 convention; no PAS requests\n");
        return;
    }
    static const uint32_t commands[] = {1, 2, 5, 6, 7};
    for (unsigned index = 0; index < sizeof(commands) / sizeof(commands[0]); index++) {
        uint32_t query = 0x02000200U | commands[index];
        result = mido_scm_available(convention, query, &available);
        IOLog("MIDO SCM: PAS command=%u availability result=%lld available=%llu smc64=%u\n",
            commands[index], result, available, convention != 0);
        if (result != 0) {
            return;
        }
        if (commands[index] == 7 && available != 0) {
            static const uint32_t peripherals[] = {6, 13};
            for (unsigned peripheral : peripherals) {
                result = mido_scm_query(0x02000207U | convention, peripheral, &available);
                IOLog("MIDO SCM: PAS supported peripheral=%u result=%lld supported=%llu smc64=%u\n",
                    peripheral, result, available, convention != 0);
                if (result != 0) {
                    return;
                }
            }
        }
    }
    IOLog("MIDO SCM: INFO/PAS supported queries only; no init/mem/auth/reset/shutdown or firmware writes\n");
}

#endif
