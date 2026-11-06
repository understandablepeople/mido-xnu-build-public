#include "mido_rpm_smd.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* Fake SMEM with an RPM that opens the channel and acks one request. */
static uint32_t smem[0x4000], window[0x2000];
static uint32_t *port, *fifo;
static unsigned notifies, requests;
static unsigned wrong_message;
#define FIFO_WORDS 512 /* 2 KiB per direction */

static void
rpm_side(void *context)
{
    (void)context;
    notifies++;
    uint32_t *local = port, *remote = port + MIDO_SS_WORDS; /* RPM owns "remote" */
    if (local[MIDO_SS_STATE] == 1 && remote[MIDO_SS_STATE] != 2) {
        remote[MIDO_SS_STATE] = 2;
        remote[MIDO_SS_DTR] = 1;
    }
    if (local[MIDO_SS_WRITTEN]) {
        uint32_t *tx = fifo, *rx = fifo + FIFO_WORDS;
        uint32_t length = tx[0];
        assert(length >= 4 * 7 && length <= 4 * 19);
        assert(tx[5] == MIDO_RPM_REQ_MAGIC);
        assert(tx[9] == MIDO_RPM_LDOA);
        requests++;
        uint32_t ack[10] = {20, 0, 0, 0, 0, MIDO_RPM_REQ_MAGIC, 12,
            0x2367736dU, 4, tx[7]};
        if (wrong_message) {
            ack[9] ^= 1U;
        }
        memcpy(rx, ack, sizeof(ack));
        remote[MIDO_SS_WIDX] = sizeof(ack);
        local[MIDO_SS_WRITTEN] = 0;
    }
}

static void
no_delay(void *context, unsigned microseconds)
{
    (void)context;
    (void)microseconds;
}

int
main(void)
{
    uint32_t valid_ack[5] = {MIDO_RPM_REQ_MAGIC, 12, 0x2367736dU, 4, 0x475001};
    assert(mido_rpm_ack_valid(valid_ack, 5, 0x475001));
    assert(!mido_rpm_ack_valid(NULL, 5, 0x475001));
    for (unsigned count = 0; count < 5; count++) {
        assert(!mido_rpm_ack_valid(valid_ack, count, 0x475001));
    }
    assert(!mido_rpm_ack_valid(valid_ack, 6, 0x475001));
    for (unsigned field = 0; field < 5; field++) {
        valid_ack[field] ^= 1U;
        assert(!mido_rpm_ack_valid(valid_ack, 5, 0x475001));
        valid_ack[field] ^= 1U;
    }
    uint32_t words = sizeof(smem) / 4;
    smem[48] = 1;
    uint32_t *info = smem + 52;
    uint32_t table_off = 0x1000 / 4, port_off = 0x1400 / 4, fifo_off = 0x1800 / 4;
    info[4 * MIDO_SMEM_CHANNEL_TBL + 0] = 1;
    info[4 * MIDO_SMEM_CHANNEL_TBL + 1] = table_off * 4;
    info[4 * MIDO_SMEM_CHANNEL_TBL + 2] = 64 * 32;
    info[4 * (MIDO_SMEM_SMD_BASE + 3) + 0] = 1;
    info[4 * (MIDO_SMEM_SMD_BASE + 3) + 1] = port_off * 4;
    info[4 * (MIDO_SMEM_SMD_BASE + 3) + 2] = 8 * MIDO_SS_WORDS;
    info[4 * (MIDO_SMEM_SMD_FIFO + 3) + 0] = 1;
    info[4 * (MIDO_SMEM_SMD_FIFO + 3) + 1] = fifo_off * 4;
    info[4 * (MIDO_SMEM_SMD_FIFO + 3) + 2] = 2 * FIFO_WORDS * 4;
    smem[table_off + 5] = 3;
    smem[table_off + 6] = MIDO_SMD_APPS_RPM;
    port = smem + port_off;
    fifo = smem + fifo_off;

    struct mido_rpm_io io = {};
    io.smem = smem;
    io.smem_size = words * 4;
    io.notify = rpm_side;
    io.delay = no_delay;
    const uint32_t kvp[9] = {MIDO_RPM_KEY_ENABLE, 4, 1, MIDO_RPM_KEY_UV, 4, 1800000,
        MIDO_RPM_KEY_MA, 4, 100};
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 6, kvp, 9, 1) == 0);
    assert(requests == 1 && io.ack[0] == MIDO_RPM_REQ_MAGIC && io.ack[1] == 12);
    memset(port, 0, 8 * MIDO_SS_WORDS);
    memset(fifo, 0, 2 * FIFO_WORDS * sizeof(uint32_t));
    wrong_message = 1;
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 6, kvp, 9, 0x475001) == -9);
    wrong_message = 0;
    /* Refusals: SMEM not initialised, external-base entry, bad length. */
    smem[48] = 0;
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 6, kvp, 9, 2) == -1);
    smem[48] = 1;
    info[4 * MIDO_SMEM_CHANNEL_TBL + 3] = 1;
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 6, kvp, 9, 3) == -2);
    info[4 * MIDO_SMEM_CHANNEL_TBL + 3] = 0;
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 6, kvp, 13, 4) == -1);

    /* Real layout seen on mido: ports/FIFOs have base_ext = RPM message RAM. */
    memset(window, 0, sizeof(window));
    port = window + 0x400 / 4;
    fifo = window + 0x800 / 4;
    info[4 * (MIDO_SMEM_SMD_BASE + 3) + 1] = 0x400;
    info[4 * (MIDO_SMEM_SMD_BASE + 3) + 3] = 0x60000;
    info[4 * (MIDO_SMEM_SMD_FIFO + 3) + 1] = 0x800;
    info[4 * (MIDO_SMEM_SMD_FIFO + 3) + 3] = 0x60000;
    io.ext = window;
    io.ext_phys = 0x60000;
    io.ext_size = sizeof(window);
    requests = 0;
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 10, kvp, 9, 5) == 0 && requests == 1);
    io.ext_phys = 0x70000; /* unexpected base_ext must be refused */
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 10, kvp, 9, 6) == -3);
    io.ext = NULL;
    assert(mido_rpm_request(&io, MIDO_RPM_LDOA, 10, kvp, 9, 7) == -3);
    puts("rpm_host ok");
    return 0;
}
