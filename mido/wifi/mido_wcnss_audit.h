#ifndef MIDO_WCNSS_AUDIT_H
#define MIDO_WCNSS_AUDIT_H

#include "mido_wcnss_smem.h"

static void
mido_wcnss_audit(struct mido_rpm_io *io)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midowifiaudit", &mode, sizeof(mode));
    if (mode == 0) {
        return;
    }
    if (mode != 1 || io == NULL || io->smem == NULL ||
        io->smem_size < 4 * (52 + 4 * (MIDO_SMEM_LAST_ITEM + 1))) {
        IOLog("MIDO WIFI: rejected audit mode/mapping; no channel writes\n");
        return;
    }
    MIDO_RPM_BARRIER();
    if (io->smem[48] != 1) {
        IOLog("MIDO WIFI: unsupported legacy SMEM heap; no channel writes\n");
        return;
    }
    uint32_t bytes = 0;
    volatile uint32_t *table = mido_smem_item(io, MIDO_SMEM_CHANNEL_TBL, &bytes);
    struct mido_wcnss_channel channel = {0, 0, 0};
    int result = mido_wcnss_find_channel(table, bytes, &channel);
    IOLog("MIDO WIFI: read-only legacy WCNSS_CTRL edge6 discovery result=%d cid=%u type=%08x refs=%u\n",
        result, channel.cid, channel.type, channel.references);
    IOLog("MIDO WIFI: no channel open/IPC/PAS/firmware/NV/DXE writes; radio not started\n");
}

#endif
