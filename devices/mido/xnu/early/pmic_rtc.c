#include "pmic_rtc.h"

static int read_rtc_register(struct mido_pmic_rtc *state, mido_rtc_u32 address,
    mido_rtc_u32 count, mido_rtc_u32 *value)
{
    const struct mido_pmic_rtc_io *io = state->io;
    mido_rtc_u64 started;
    mido_rtc_u32 status;
    mido_rtc_u32 polls;
    if (!((address == 0x6005u && count == 1) || (address == 0x6046u && count == 1) ||
        (address == 0x6048u && (count == 1 || count == 4))))
        return MIDO_RTC_INVALID;
    started = io->counter(io->context);
    io->synchronize(io->context);
    if (io->read_command(io->context, state->observer_offset,
        (1u << 27) | ((address & 0xffu) << 4) | (count - 1u)) != 0)
        return MIDO_RTC_IO;
    io->synchronize(io->context);
    for (polls = 0; polls < 4096; polls++) {
        if (io->read32(io->context, MIDO_RTC_OBSERVER, state->observer_offset + 8u, &status) != 0)
            return MIDO_RTC_IO;
        if (status & 14u)
            return MIDO_RTC_IO;
        if (status & 1u) {
            io->synchronize(io->context);
            if (io->read32(io->context, MIDO_RTC_OBSERVER, state->observer_offset + 0x18u, value) != 0)
                return MIDO_RTC_IO;
            if (count == 1)
                *value &= 0xffu;
            return MIDO_RTC_OK;
        }
        if (io->counter(io->context) - started >= 1920u)
            return MIDO_RTC_TIMEOUT;
    }
    return MIDO_RTC_TIMEOUT;
}

int mido_pmic_rtc_discover(const struct mido_pmic_rtc_io *io, mido_rtc_u32 *observer_offset)
{
    mido_rtc_u32 version;
    mido_rtc_u32 channel;
    mido_rtc_u32 mapping;
    mido_rtc_u32 found = 512;
    if (!observer_offset || !io || !io->read32)
        return MIDO_RTC_INVALID;
    if (io->read32(io->context, MIDO_RTC_CORE, 0, &version) != 0)
        return MIDO_RTC_IO;
    if (version != 0x20010000u)
        return MIDO_RTC_UNSUPPORTED;
    for (channel = 0; channel < 512; channel++) {
        if (io->read32(io->context, MIDO_RTC_CORE, 0x800u + 4u * channel, &mapping) != 0)
            return MIDO_RTC_IO;
        if (mapping && ((mapping >> 8) & 0xfffu) == 0x60u) {
            if (found != 512 || channel >= 256)
                return MIDO_RTC_UNSUPPORTED;
            found = channel;
        }
    }
    if (found == 512)
        return MIDO_RTC_UNSUPPORTED;
    *observer_offset = found * 0x8000u;
    return MIDO_RTC_OK;
}

int mido_pmic_rtc_attach(struct mido_pmic_rtc *state, const struct mido_pmic_rtc_io *io)
{
    mido_rtc_u32 observer_offset;
    mido_rtc_u32 subtype;
    mido_rtc_u32 control;
    int status;
    if (!state)
        return MIDO_RTC_INVALID;
    state->ready = 0;
    state->io = 0;
    state->observer_offset = 0;
    if (!io || !io->read32 || !io->read_command || !io->counter || !io->synchronize)
        return MIDO_RTC_INVALID;
    status = mido_pmic_rtc_discover(io, &observer_offset);
    if (status != MIDO_RTC_OK)
        return status;
    state->io = io;
    state->observer_offset = observer_offset;
    status = read_rtc_register(state, 0x6005u, 1, &subtype);
    if (status != MIDO_RTC_OK)
        return status;
    if (subtype != 1)
        return MIDO_RTC_UNSUPPORTED;
    status = read_rtc_register(state, 0x6046u, 1, &control);
    if (status != MIDO_RTC_OK)
        return status;
    if (!(control & 0x80u))
        return MIDO_RTC_DISABLED;
    state->ready = 1;
    return MIDO_RTC_OK;
}

int mido_pmic_rtc_seconds(struct mido_pmic_rtc *state, mido_rtc_u32 *seconds)
{
    mido_rtc_u32 snapshot;
    mido_rtc_u32 low_byte;
    mido_rtc_u32 attempt;
    int status;
    if (!state || !state->ready || !state->io || !seconds)
        return MIDO_RTC_INVALID;
    status = read_rtc_register(state, 0x6046u, 1, &low_byte);
    if (status != MIDO_RTC_OK)
        return status;
    if (!(low_byte & 0x80u))
        return MIDO_RTC_DISABLED;
    for (attempt = 0; attempt < 3; attempt++) {
        status = read_rtc_register(state, 0x6048u, 4, &snapshot);
        if (status != MIDO_RTC_OK)
            return status;
        status = read_rtc_register(state, 0x6048u, 1, &low_byte);
        if (status != MIDO_RTC_OK)
            return status;
        if (low_byte >= (snapshot & 0xffu)) {
            *seconds = snapshot;
            return MIDO_RTC_OK;
        }
    }
    return MIDO_RTC_UNSTABLE;
}
