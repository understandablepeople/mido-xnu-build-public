#ifndef MIDO_GPU_POWER_H
#define MIDO_GPU_POWER_H

#include <stddef.h>
#include <stdint.h>

#define MIDO_GPU_GCC_BASE 0x01800000U
#define MIDO_GPU_AUDIT_OFFSET 0x58000U
#define MIDO_GPU_AUDIT_SIZE 0x8000U

#define MIDO_GPU_BLOCK_CX 1U
#define MIDO_GPU_BLOCK_GX 2U
#define MIDO_GPU_BLOCK_CLOCKS 4U
#define MIDO_GPU_BLOCK_CLAMP 8U
#define MIDO_GPU_BLOCK_SUPPLY 16U
#define MIDO_GPU_BLOCK_UPDATE 32U

enum mido_gpu_register {
    MIDO_GPU_CMD, MIDO_GPU_CFG, MIDO_GPU_CX, MIDO_GPU_GX,
    MIDO_GPU_CORE, MIDO_GPU_AHB, MIDO_GPU_MEM, MIDO_GPU_TIMER,
    MIDO_GPU_AON, MIDO_GPU_CLAMP, MIDO_GPU_SUPPLY_CTL,
    MIDO_GPU_SUPPLY_STATUS, MIDO_GPU_REGISTER_COUNT
};

struct mido_gpu_snapshot {
    uint32_t values[MIDO_GPU_REGISTER_COUNT];
};

struct mido_gpu_reader {
    void *context;
    int (*read)(void *, uint32_t, uint32_t *);
};

struct mido_gfx_corner {
    uint32_t corner, ldo_mode, voltage_uv, vref, cx_level, mem_acc_corner;
};

static inline int
mido_gfx_plan(uint64_t enable_row, uint64_t voltage_row, unsigned corner,
    struct mido_gfx_corner *result)
{
    static const int32_t reference_uv[3] = {580000, 650000, 720000};
    static const int32_t adjustment_uv[3] = {35000, 25000, 0};
    static const int32_t floor_uv[3] = {510000, 510000, 600000};
    static const int32_t ceiling_uv[3] = {620000, 680000, 750000};
    static const unsigned shifts[3] = {42, 37, 32};
    static const uint32_t cx_levels[7] = {64, 64, 128, 192, 256, 320, 384};
    static const uint32_t mem_acc[7] = {1, 1, 1, 2, 2, 2, 2};
    if (result == NULL || corner < 1 || corner > 7) {
        return 0;
    }
    struct mido_gfx_corner next = {0, 0, 0, 0, 0, 0};
    next.corner = corner;
    next.cx_level = cx_levels[corner - 1];
    next.mem_acc_corner = mem_acc[corner - 1];
    next.ldo_mode = corner <= 3 && ((enable_row >> 11) & 1U);
    if (next.ldo_mode) {
        unsigned index = corner - 1;
        unsigned fuse = (unsigned)((voltage_row >> shifts[index]) & 31U);
        int32_t delta = (int32_t)(fuse & 15U) * 10000;
        int32_t voltage = reference_uv[index] + adjustment_uv[index] +
            ((fuse & 16U) ? -delta : delta);
        if (voltage < floor_uv[index]) {
            voltage = floor_uv[index];
        }
        if (voltage > ceiling_uv[index]) {
            voltage = ceiling_uv[index];
        }
        next.voltage_uv = (uint32_t)voltage;
        next.vref = (next.voltage_uv - 375000U + 4999U) / 5000U;
    }
    *result = next;
    return 1;
}

static inline int
mido_gpu_snapshot_read(const struct mido_gpu_reader *reader,
    struct mido_gpu_snapshot *result)
{
    static const uint32_t offsets[MIDO_GPU_REGISTER_COUNT] = {
        0x59000, 0x59004, 0x5904c, 0x5901c,
        0x59020, 0x59028, 0x59030, 0x59040,
        0x59044, 0x5b00c, 0x5f01c, 0x5f028
    };
    if (reader == NULL || reader->read == NULL || result == NULL) {
        return 0;
    }
    struct mido_gpu_snapshot next = {0};
    for (unsigned index = 0; index < MIDO_GPU_REGISTER_COUNT; index++) {
        if (!reader->read(reader->context, offsets[index], &next.values[index])) {
            return 0;
        }
    }
    *result = next;
    return 1;
}

static inline uint32_t
mido_gpu_snapshot_blockers(const struct mido_gpu_snapshot *snapshot)
{
    if (snapshot == NULL) {
        return 0x3fU;
    }
    const uint32_t *values = snapshot->values;
    uint32_t blockers = 0;
    if ((values[MIDO_GPU_CX] & 0x80000003U) != 0x80000000U) {
        blockers |= MIDO_GPU_BLOCK_CX;
    }
    if ((values[MIDO_GPU_GX] & 0x80000003U) != 0x80000000U) {
        blockers |= MIDO_GPU_BLOCK_GX;
    }
    for (unsigned index = MIDO_GPU_CORE; index <= MIDO_GPU_AON; index++) {
        if ((values[index] & 0x80000001U) != 1U) {
            blockers |= MIDO_GPU_BLOCK_CLOCKS;
        }
    }
    if ((values[MIDO_GPU_CLAMP] & 1U) ||
        (values[MIDO_GPU_SUPPLY_CTL] & 0x80000000U)) {
        blockers |= MIDO_GPU_BLOCK_CLAMP;
    }
    uint32_t ready_bit = (values[MIDO_GPU_SUPPLY_CTL] & (1U << 9)) ? 4U : 2U;
    if (!(values[MIDO_GPU_SUPPLY_STATUS] & ready_bit)) {
        blockers |= MIDO_GPU_BLOCK_SUPPLY;
    }
    if (values[MIDO_GPU_CMD] & 1U) {
        blockers |= MIDO_GPU_BLOCK_UPDATE;
    }
    return blockers;
}

#endif
