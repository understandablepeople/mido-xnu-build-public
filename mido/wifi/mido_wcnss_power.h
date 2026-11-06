#ifndef MIDO_WCNSS_POWER_H
#define MIDO_WCNSS_POWER_H

#include "mido_gpu_cx.h"

static int
mido_wcnss_power(struct mido_rpm_io *rpm, bool touch_rails_ready)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midowifipower", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || !touch_rails_ready || rpm == NULL || rpm->cx_level_floor > 384U) {
        return -1;
    }
    static const struct {
        uint32_t type, id, key, value, milliamp, sets;
    } supplies[] = {
        {MIDO_GPU_CX_RESOURCE, 7, MIDO_GPU_CX_LEVEL_KEY, 384, 0, 1},
        {MIDO_GPU_CX_RESOURCE, 2, MIDO_GPU_CX_LEVEL_KEY, 256, 0, 3},
        {MIDO_RPM_LDOA, 5, MIDO_RPM_KEY_UV, 1800000, 10, 3},
        {MIDO_RPM_LDOA, 7, MIDO_RPM_KEY_UV, 1800000, 28, 3},
        {MIDO_RPM_LDOA, 19, MIDO_RPM_KEY_UV, 1300000, 100, 3},
        {MIDO_RPM_LDOA, 9, MIDO_RPM_KEY_UV, 3300000, 515, 3},
    };
    uint32_t message = 0x574600;
    for (unsigned index = 0; index < sizeof(supplies) / sizeof(supplies[0]); index++) {
        const auto &supply = supplies[index];
        uint32_t value = supply.value;
        if (supply.type == MIDO_GPU_CX_RESOURCE && supply.id == 2 && rpm->cx_level_floor > value) {
            value = rpm->cx_level_floor;
        }
        const uint32_t kvp[9] = {MIDO_RPM_KEY_ENABLE, 4, 1,
            supply.key, 4, value, MIDO_RPM_KEY_MA, 4, supply.milliamp};
        for (unsigned selected = 0; selected < 2; selected++) {
            if (!(supply.sets & (1U << selected))) {
                continue;
            }
            if (selected == 0 && supply.type == MIDO_GPU_CX_RESOURCE && supply.id == 2) {
                rpm->cx_level_floor = value;
            }
            int result = mido_rpm_request_set(rpm, supply.type, supply.id, kvp,
                supply.type == MIDO_GPU_CX_RESOURCE ? 6 : 9, message++, selected);
            IOLog("MIDO WIFI POWER: supply=%u id=%u set=%u value=%u result=%d\n",
                index, supply.id, selected, value, result);
            if (result != 0) {
                return -2;
            }
        }
    }
    const uint32_t xo[3] = {0x62616e45U, 4, 1};
    for (unsigned selected = 0; selected < 2; selected++) {
        int result = mido_rpm_request_set(rpm, 0x306b6c63U, 0, xo, 3, message++, selected);
        if (result != 0) {
            IOLog("MIDO WIFI POWER: XO set=%u result=%d; no firmware startup\n", selected, result);
            return -3;
        }
    }
    IODelay(1000);
    IOLog("MIDO WIFI POWER: supplies/XO acknowledged; SCM clocks/IRIS/PAS/SMD/DXE not started\n");
    return 1;
}

#endif
