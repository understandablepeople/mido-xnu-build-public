#ifndef MIDO_CBCR_H
#define MIDO_CBCR_H

static inline bool
mido_cbcr_status_on(uint32_t value)
{
    uint32_t state = value & 0xf0000000U;
    return state == 0 || state == 0x20000000U;
}

static inline bool
mido_cbcr_branch_on(uint32_t value)
{
    return (value & 3U) == 1U && mido_cbcr_status_on(value);
}

#endif
