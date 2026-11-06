#ifndef MIDO_WCNSS_CLOCKS_H
#define MIDO_WCNSS_CLOCKS_H

#include "mido_cbcr.h"

static int
mido_wcnss_clocks(void)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midowificlocks", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1) {
        IOLog("MIDO WIFI CLOCKS: unsupported mode=%u; no hardware access\n", mode);
        return -1;
    }
    vm_offset_t crypto = ml_io_map_unmappable(0x01816000, 0x1000, VM_WIMG_IO);
    vm_offset_t votes = ml_io_map_unmappable(0x01845000, 0x1000, VM_WIMG_IO);
    vm_offset_t pll = ml_io_map_unmappable(0x01821000, 0x1000, VM_WIMG_IO);
    if (!crypto || !votes || !pll) {
        if (crypto) ml_io_unmap(crypto, 0x1000);
        if (votes) ml_io_unmap(votes, 0x1000);
        if (pll) ml_io_unmap(pll, 0x1000);
        return -2;
    }
    volatile uint32_t *registers = (volatile uint32_t *)crypto;
    uint32_t command = MIDO_GPU_GX_LOAD(registers + 4 / 4);
    uint32_t config = MIDO_GPU_GX_LOAD(registers + 8 / 4);
    uint32_t core = MIDO_GPU_GX_LOAD(registers + 0x1c / 4);
    uint32_t bus = MIDO_GPU_GX_LOAD(registers + 0x20 / 4);
    uint32_t iface = MIDO_GPU_GX_LOAD(registers + 0x24 / 4);
    uint32_t pll_vote = MIDO_GPU_GX_LOAD((volatile uint32_t *)votes);
    uint32_t branch_vote = MIDO_GPU_GX_LOAD((volatile uint32_t *)(votes + 4));
    uint32_t pll_mode = MIDO_GPU_GX_LOAD((volatile uint32_t *)pll);
    ml_io_unmap(crypto, 0x1000);
    ml_io_unmap(votes, 0x1000);
    ml_io_unmap(pll, 0x1000);
    IOLog("MIDO WIFI CLOCKS: crypto-root=%08x cfg=%08x core=%08x bus=%08x iface=%08x\n",
        command, config, core, bus, iface);
    IOLog("MIDO WIFI CLOCKS: gpll0=%08x pll-vote=%08x branch-vote=%08x; target80MHz not programmed\n",
        pll_mode, pll_vote, branch_vote);
    IOLog("MIDO WIFI CLOCKS: core-on=%u bus-on=%u iface-on=%u gpll0-locked=%u apcs-crypto-votes=%u; shared state not reprogrammed\n",
        mido_cbcr_status_on(core) ? 1U : 0U, mido_cbcr_status_on(bus) ? 1U : 0U,
        mido_cbcr_status_on(iface) ? 1U : 0U, (pll_mode >> 30) & 1U, branch_vote & 7U);
    IOLog("MIDO WIFI CLOCKS: GCC read-only; XO RPM vote/supplies/PAS firmware/radio not requested\n");
    return 1;
}

#endif
