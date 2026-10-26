#ifndef MIDO_PMIC_RTC_H
#define MIDO_PMIC_RTC_H

typedef __UINT8_TYPE__ mido_rtc_u8;
typedef __UINT32_TYPE__ mido_rtc_u32;
typedef __UINT64_TYPE__ mido_rtc_u64;

enum mido_rtc_status {
    MIDO_RTC_OK = 0,
    MIDO_RTC_INVALID = -1,
    MIDO_RTC_UNSUPPORTED = -2,
    MIDO_RTC_IO = -3,
    MIDO_RTC_TIMEOUT = -4,
    MIDO_RTC_UNSTABLE = -5,
    MIDO_RTC_DISABLED = -6
};

enum mido_rtc_region { MIDO_RTC_CORE = 0, MIDO_RTC_OBSERVER = 1 };

struct mido_pmic_rtc_io {
    void *context;
    int (*read32)(void *context, mido_rtc_u32 region, mido_rtc_u32 offset, mido_rtc_u32 *value);
    int (*read_command)(void *context, mido_rtc_u32 offset, mido_rtc_u32 command);
    mido_rtc_u64 (*counter)(void *context);
    void (*synchronize)(void *context);
};

struct mido_pmic_rtc {
    const struct mido_pmic_rtc_io *io;
    mido_rtc_u32 observer_offset;
    mido_rtc_u32 ready;
};

int mido_pmic_rtc_attach(struct mido_pmic_rtc *state, const struct mido_pmic_rtc_io *io);
int mido_pmic_rtc_discover(const struct mido_pmic_rtc_io *io, mido_rtc_u32 *observer_offset);
int mido_pmic_rtc_seconds(struct mido_pmic_rtc *state, mido_rtc_u32 *seconds);

#endif
