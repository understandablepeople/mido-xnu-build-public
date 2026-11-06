#ifndef MIDO_RPM_SMD_H
#define MIDO_RPM_SMD_H

#include <stddef.h>
#include <stdint.h>

/*
 * Minimal polled RPM SMD client for MSM8953, following lk2nd 23.1
 * platform/msm_shared/{smem,smd,rpm-smd}.c: reopen the apps->RPM channel
 * (left closed by the bootloader), send one active-set request, read one ack.
 * SMEM is touched only with aligned 32-bit accesses. Items with base_ext (the
 * SMD ports live in RPM message RAM at 0x60000) are accepted only for the one
 * caller-mapped window io->ext; any other base_ext is refused.
 */
#define MIDO_SMD_APPS_RPM      0x0f
#define MIDO_SMEM_CHANNEL_TBL  13
#define MIDO_SMEM_SMD_BASE     14
#define MIDO_SMEM_SMD_FIFO     338
#define MIDO_SMEM_LAST_ITEM    418
#define MIDO_RPM_REQ_MAGIC     0x00716572U
#define MIDO_RPM_LDOA          0x616f646cU
#define MIDO_RPM_KEY_ENABLE    0x6e657773U
#define MIDO_RPM_KEY_UV        0x7675U
#define MIDO_RPM_KEY_MA        0x616dU

#if defined(__aarch64__)
#define MIDO_RPM_BARRIER() __asm__ volatile("dsb sy" ::: "memory")
#else
#define MIDO_RPM_BARRIER() __asm__ volatile("" ::: "memory")
#endif

/* smd_shared_stream_info_type words; the remote (RPM) half follows ours. */
enum {
    MIDO_SS_STATE, MIDO_SS_DTR, MIDO_SS_CTS, MIDO_SS_CD, MIDO_SS_RI,
    MIDO_SS_WRITTEN, MIDO_SS_READ, MIDO_SS_UPDATED, MIDO_SS_MASK,
    MIDO_SS_RIDX, MIDO_SS_WIDX, MIDO_SS_WORDS
};

struct mido_rpm_io {
    volatile uint32_t *smem;
    uint32_t smem_size;
    volatile uint32_t *ext;
    uint32_t ext_phys, ext_size;
    void *context;
    void (*notify)(void *);
    void (*delay)(void *, unsigned);
    uint32_t ack[2];
};

static inline volatile uint32_t *
mido_smem_item(struct mido_rpm_io *io, unsigned item, uint32_t *size)
{
    /* proc_comm[4] + version_info[32] + heap_info = word 52 */
    volatile uint32_t *info = io->smem + 52 + 4 * item;
    if (item > MIDO_SMEM_LAST_ITEM || info[0] == 0) {
        return NULL;
    }
    /* base_ext != 0: item lives in the RPM message RAM window, not main SMEM. */
    volatile uint32_t *region = io->smem;
    uint32_t limit = io->smem_size;
    if (info[3] != 0) {
        if (io->ext == NULL || info[3] != io->ext_phys) {
            return NULL;
        }
        region = io->ext;
        limit = io->ext_size;
    }
    uint32_t offset = info[1], length = info[2];
    if ((offset & 3) || (length & 3) || offset > limit || length > limit - offset) {
        return NULL;
    }
    *size = length;
    return region + offset / 4;
}

static inline uint32_t
mido_fifo_used(uint32_t write, uint32_t read, uint32_t size)
{
    return (write + size - read) % size;
}

static inline int
mido_rpm_request(struct mido_rpm_io *io, uint32_t type, uint32_t id,
    const uint32_t *kvp, unsigned kvp_words, uint32_t msg_id)
{
    if (io == NULL || io->smem == NULL || io->notify == NULL || io->delay == NULL ||
        kvp == NULL || kvp_words == 0 || kvp_words > 12 ||
        io->smem_size < 4 * (52 + 4 * (MIDO_SMEM_LAST_ITEM + 1)) ||
        io->smem[48] != 1) {
        return -1;
    }
    uint32_t size = 0, port_size = 0, fifo_size = 0;
    volatile uint32_t *table = mido_smem_item(io, MIDO_SMEM_CHANNEL_TBL, &size);
    if (table == NULL) {
        return -2;
    }
    volatile uint32_t *port = NULL, *fifo = NULL;
    /* smd_channel_alloc_entry_t: name[20], cid, ctype, ref_count */
    for (uint32_t entry = 0; entry + 8 <= size / 4 && entry < 64 * 8; entry += 8) {
        if ((table[entry + 6] & 0xff) == MIDO_SMD_APPS_RPM) {
            uint32_t cid = table[entry + 5];
            if (cid <= MIDO_SMEM_LAST_ITEM - MIDO_SMEM_SMD_FIFO) {
                port = mido_smem_item(io, MIDO_SMEM_SMD_BASE + cid, &port_size);
                fifo = mido_smem_item(io, MIDO_SMEM_SMD_FIFO + cid, &fifo_size);
            }
            break;
        }
    }
    if (port == NULL || port_size < 8 * MIDO_SS_WORDS || fifo == NULL ||
        fifo_size < 128 || (fifo_size & 7)) {
        return -3;
    }
    fifo_size /= 2;
    volatile uint32_t *local = port, *remote = port + MIDO_SS_WORDS;
    volatile uint32_t *tx = fifo, *rx = fifo + fifo_size / 4;

    uint32_t remote_state = remote[MIDO_SS_STATE];
    if (local[MIDO_SS_STATE] != 2 || (remote_state != 2 && remote_state != 3)) {
        uint32_t state = local[MIDO_SS_STATE];
        if (state != 0 && state != 4) {
            return -4;
        }
        local[MIDO_SS_DTR] = local[MIDO_SS_CTS] = local[MIDO_SS_CD] = 0;
        local[MIDO_SS_STATE] = 1;
        remote[MIDO_SS_RIDX] = 0;
        local[MIDO_SS_WIDX] = 0;
        local[MIDO_SS_MASK] = 0;
        local[MIDO_SS_UPDATED] = 1;
        MIDO_RPM_BARRIER();
        io->notify(io->context);
        unsigned attempt = 0;
        for (; attempt < 20000 && remote[MIDO_SS_STATE] != 2; attempt++) {
            io->delay(io->context, 10);
        }
        if (attempt == 20000) {
            return -5;
        }
        remote[MIDO_SS_UPDATED] = 0;
        local[MIDO_SS_DTR] = local[MIDO_SS_CTS] = local[MIDO_SS_CD] = 1;
        local[MIDO_SS_STATE] = 2;
        local[MIDO_SS_UPDATED] = 0;
        MIDO_RPM_BARRIER();
        io->notify(io->context);
    }
    if (!local[MIDO_SS_DTR]) {
        return -5;
    }

    /* smd_pkt_hdr, rpm_gen_hdr, rpm_req_hdr (active set), key/length/value data */
    uint32_t message[12 + 12];
    unsigned words = 12 + kvp_words;
    message[0] = 4 * (words - 5);
    message[1] = message[2] = message[3] = message[4] = 0;
    message[5] = MIDO_RPM_REQ_MAGIC;
    message[6] = 4 * (words - 7);
    message[7] = msg_id;
    message[8] = 0;
    message[9] = type;
    message[10] = id;
    message[11] = 4 * kvp_words;
    for (unsigned index = 0; index < kvp_words; index++) {
        message[12 + index] = kvp[index];
    }
    uint32_t write = local[MIDO_SS_WIDX], read = local[MIDO_SS_RIDX];
    if (write >= fifo_size || read >= fifo_size || ((write | read) & 3) ||
        mido_fifo_used(write, read, fifo_size) + 4 * words >= fifo_size) {
        return -6;
    }
    remote[MIDO_SS_READ] = 0;
    for (unsigned index = 0; index < words; index++) {
        tx[write / 4] = message[index];
        write = (write + 4) % fifo_size;
    }
    local[MIDO_SS_WIDX] = write;
    MIDO_RPM_BARRIER();
    local[MIDO_SS_WRITTEN] = 1;
    local[MIDO_SS_MASK] = 0;
    MIDO_RPM_BARRIER();
    io->notify(io->context);

    uint32_t response[5 + 16], need = 20, length = 0;
    for (unsigned attempt = 0;; attempt++) {
        write = remote[MIDO_SS_WIDX];
        read = remote[MIDO_SS_RIDX];
        if (write >= fifo_size || read >= fifo_size || ((write | read) & 3)) {
            return -7;
        }
        if (mido_fifo_used(write, read, fifo_size) >= need) {
            if (need == 20) {
                length = rx[read / 4];
                if (length < 12 || length > 64 || (length & 3)) {
                    return -8;
                }
                need += length;
                continue;
            }
            break;
        }
        if (attempt == 20000) {
            return -7;
        }
        io->delay(io->context, 10);
    }
    for (unsigned index = 0; index < need / 4; index++) {
        response[index] = rx[read / 4];
        read = (read + 4) % fifo_size;
    }
    remote[MIDO_SS_RIDX] = read;
    remote[MIDO_SS_WRITTEN] = 0;
    local[MIDO_SS_READ] = 1;
    local[MIDO_SS_MASK] = 1;
    MIDO_RPM_BARRIER();
    io->notify(io->context);
    io->ack[0] = response[5];
    io->ack[1] = response[6];
    /* Success ack carries only the msg_id pair (lk2nd ACK_MSG_LENGTH). */
    return length == 12 && response[5] == MIDO_RPM_REQ_MAGIC &&
        response[6] == 12 && response[7] == msg_id ? 0 : -9;
}

#endif
