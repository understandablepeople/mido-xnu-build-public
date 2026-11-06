#include <cassert>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include "mido_rpm_smd.h"

static unsigned mode, calls, fail_at, delayed, gpu_calls;
static uint32_t initial_floor, gpu_level;
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 1000); delayed++; }
static bool PE_parse_boot_argn(const char *name, void *output, int bytes)
{
    assert(!std::strcmp(name, "midowifipower") && bytes == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static int capture_gpu(struct mido_rpm_io *rpm, uint32_t type, uint32_t id,
    const uint32_t *kvp, unsigned count, uint32_t message)
{
    assert(rpm && type == 0x61706d73U && id == 2 && count == 6 && message == 0x475001);
    assert(kvp[0] == MIDO_RPM_KEY_ENABLE && kvp[1] == 4 && kvp[2] == 1);
    assert(kvp[3] == 0x6c766c76U && kvp[4] == 4);
    gpu_level = kvp[5]; gpu_calls++;
    return 0;
}
#define mido_rpm_request capture_gpu
#include "mido_gpu_cx.h"

static int capture_power(struct mido_rpm_io *rpm, uint32_t type, uint32_t id,
    const uint32_t *kvp, unsigned count, uint32_t message, unsigned selected)
{
    static const uint32_t expected[][7] = {
        {0x61706d73U, 7, 0x6c766c76U, 384, 0, 0, 6},
        {0x61706d73U, 2, 0x6c766c76U, 256, 0, 0, 6},
        {0x61706d73U, 2, 0x6c766c76U, 256, 0, 1, 6},
        {MIDO_RPM_LDOA, 5, MIDO_RPM_KEY_UV, 1800000, 10, 0, 9},
        {MIDO_RPM_LDOA, 5, MIDO_RPM_KEY_UV, 1800000, 10, 1, 9},
        {MIDO_RPM_LDOA, 7, MIDO_RPM_KEY_UV, 1800000, 28, 0, 9},
        {MIDO_RPM_LDOA, 7, MIDO_RPM_KEY_UV, 1800000, 28, 1, 9},
        {MIDO_RPM_LDOA, 19, MIDO_RPM_KEY_UV, 1300000, 100, 0, 9},
        {MIDO_RPM_LDOA, 19, MIDO_RPM_KEY_UV, 1300000, 100, 1, 9},
        {MIDO_RPM_LDOA, 9, MIDO_RPM_KEY_UV, 3300000, 515, 0, 9},
        {MIDO_RPM_LDOA, 9, MIDO_RPM_KEY_UV, 3300000, 515, 1, 9},
        {0x306b6c63U, 0, 0x62616e45U, 1, 0, 0, 3},
        {0x306b6c63U, 0, 0x62616e45U, 1, 0, 1, 3},
    };
    assert(rpm && calls < 13);
    const uint32_t *expect = expected[calls];
    assert(type == expect[0] && id == expect[1] && selected == expect[5] && count == expect[6]);
    assert(message == 0x574600U + calls);
    uint32_t value = expect[3];
    if (type == 0x61706d73U && id == 2 && initial_floor > value) value = initial_floor;
    if (count == 3) {
        assert(kvp[0] == expect[2] && kvp[1] == 4 && kvp[2] == value);
    } else {
        assert(kvp[0] == MIDO_RPM_KEY_ENABLE && kvp[1] == 4 && kvp[2] == 1);
        assert(kvp[3] == expect[2] && kvp[4] == 4 && kvp[5] == value);
        if (count == 9) assert(kvp[6] == MIDO_RPM_KEY_MA && kvp[7] == 4 && kvp[8] == expect[4]);
    }
    calls++;
    return calls == fail_at ? -9 : 0;
}
#define mido_rpm_request_set capture_power
#include "mido_wcnss_power.h"

static mido_rpm_io reset(uint32_t floor = 0)
{
    mode = 1; calls = fail_at = delayed = gpu_calls = gpu_level = 0;
    initial_floor = floor;
    mido_rpm_io rpm = {};
    rpm.cx_level_floor = floor;
    return rpm;
}
int main()
{
    auto rpm = reset(); mode = 0;
    assert(mido_wcnss_power(&rpm, true) == 0 && calls == 0 && delayed == 0);
    rpm = reset(); mode = 2;
    assert(mido_wcnss_power(&rpm, true) == -1 && calls == 0);
    rpm = reset();
    assert(mido_wcnss_power(&rpm, false) == -1 && calls == 0);
    assert(mido_wcnss_power(nullptr, true) == -1 && calls == 0);
    for (unsigned failure = 1; failure <= 13; failure++) {
        rpm = reset(); fail_at = failure;
        assert(mido_wcnss_power(&rpm, true) == (failure <= 11 ? -2 : -3));
        assert(calls == failure && delayed == 0);
        assert(rpm.cx_level_floor == (failure >= 2 ? 256U : 0U));
        assert(mido_gpu_cx_vote(&rpm) == 0 && gpu_calls == 1);
        assert(gpu_level == (failure >= 2 ? 256U : 192U));
    }
    for (uint32_t floor : {0U, 192U, 256U, 320U, 384U}) {
        rpm = reset(floor);
        assert(mido_wcnss_power(&rpm, true) == 1 && calls == 13 && delayed == 1);
        assert(rpm.cx_level_floor == (floor > 256 ? floor : 256));
        assert(mido_gpu_cx_vote(&rpm) == 0 && gpu_level == rpm.cx_level_floor);
    }
    rpm = reset(385);
    assert(mido_wcnss_power(&rpm, true) == -1 && calls == 0);
    assert(mido_gpu_cx_vote(&rpm) == -1 && gpu_calls == 0);
    return 0;
}
