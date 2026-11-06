#ifndef MIDO_QUP_V2_H
#define MIDO_QUP_V2_H

#include "mido_ft5435.h"

struct mido_qup_io {
    void *context;
    uint32_t (*read)(void *, uint32_t);
    void (*write)(void *, uint32_t, uint32_t);
    void (*delay)(void *, unsigned);
    uint32_t last_status, last_errors, last_operational, last_position;
};

static inline int
mido_qup_wait(struct mido_qup_io *io, uint32_t offset, uint32_t mask,
    uint32_t value, unsigned limit)
{
    for (unsigned attempt = 0; attempt < limit; attempt++) {
        if ((io->read(io->context, offset) & mask) == value) {
            return 1;
        }
        io->delay(io->context, 5);
    }
    return 0;
}

static inline int
mido_qup_state(struct mido_qup_io *io, uint32_t state)
{
    if (!mido_qup_wait(io, 4, 4, 4, 2000)) {
        return 0;
    }
    io->write(io->context, 4, state);
    return mido_qup_wait(io, 4, 7, state | 4, 2000);
}

static inline int
mido_qup_read(struct mido_qup_io *io, uint8_t address, uint8_t reg,
    uint8_t *data, unsigned length)
{
    uint8_t command[MIDO_FT_READ_COMMAND_BYTES];
    uint8_t received[257];
    if (io == NULL || io->read == NULL || io->write == NULL ||
        io->delay == NULL || data == NULL ||
        mido_ft_read_command(address, reg, length, command, sizeof(command)) == 0) {
        return -1;
    }
    uint32_t version = io->read(io->context, 0x30);
    if (version == 0 || version == UINT32_MAX || (version >> 28) != 2) {
        return -2;
    }
    io->last_status = io->last_errors = io->last_operational = io->last_position = 0;
    io->write(io->context, 0x0c, 1);
    if (!mido_qup_wait(io, 4, 7, 4, 2000)) {
        io->write(io->context, 0x0c, 1);
        return -3;
    }
    uint32_t modes = io->read(io->context, 8);
    unsigned input_code = (modes >> 5) & 3;
    unsigned output_code = modes & 3;
    static const unsigned block_sizes[3] = {16, 16, 32};
    if (input_code > 2 || output_code > 2 ||
        (io->read(io->context, 4) & 16) == 0) {
        return -4;
    }
    unsigned block = block_sizes[input_code];
    io->write(io->context, 0, 0x207);
    io->write(io->context, 0x20, 0x3c);
    io->write(io->context, 0x1c, 0x3c);
    io->write(io->context, 0x404, 0x380003c);
    io->write(io->context, 0x28, 0x300);
    io->write(io->context, 0x408, 1);
    io->write(io->context, 8, 0xd000);
    io->write(io->context, 0x100, 0);
    io->write(io->context, 0x150, sizeof(command));
    io->write(io->context, 0x208, 0);
    io->write(io->context, 0x200, length + 2);
    if (!mido_qup_state(io, 1)) {
        io->write(io->context, 0x0c, 1);
        return -5;
    }
    io->write(io->context, 0x400, (62U << 16) | 124U);
    if (!mido_qup_state(io, 3)) {
        io->write(io->context, 0x0c, 1);
        return -5;
    }
    for (unsigned position = 0; position < sizeof(command); position += 4) {
        uint32_t word = 0;
        for (unsigned byte = 0; byte < 4 && position + byte < sizeof(command); byte++) {
            word |= (uint32_t)command[position + byte] << (8 * byte);
        }
        io->write(io->context, 0x110, word);
    }
    if (!mido_qup_state(io, 1)) {
        io->write(io->context, 0x0c, 1);
        return -5;
    }
    unsigned position = 0;
    int result = -6;
    for (unsigned attempt = 0; attempt < 20000; attempt++) {
        uint32_t status = io->read(io->context, 0x404);
        uint32_t errors = io->read(io->context, 0x1c);
        uint32_t operational = io->read(io->context, 0x18);
        io->last_status = status;
        io->last_errors = errors;
        io->last_operational = operational;
        io->last_position = position;
        if ((status & 0x380003c) != 0 || (errors & 0x3c) != 0) {
            result = -7;
            break;
        }
        /* 0x200 service flag or 0x2000 block-read request: 0109 hardware showed only the latter. */
        if ((operational & 0x2200) != 0) {
            io->write(io->context, 0x18, 0x200);
            unsigned available = length + 2 - position;
            if (available > block) {
                available = block;
            }
            for (unsigned offset = 0; offset < available; offset += 4) {
                if (!mido_qup_wait(io, 0x18, 0x20, 0x20, 2000)) {
                    result = -9;
                    break;
                }
                uint32_t word = io->read(io->context, 0x218);
                for (unsigned byte = 0; byte < 4 && offset + byte < available; byte++) {
                    received[position++] = (uint8_t)(word >> (8 * byte));
                }
            }
            if (result == -9) {
                break;
            }
        }
        if ((operational & 0x100) != 0) {
            io->write(io->context, 0x18, 0x100);
        }
        if (position == length + 2 && (operational & 0x800) != 0 &&
            (status & 0x100) == 0) {
            result = 0;
            break;
        }
        io->delay(io->context, 5);
    }
    if (!mido_qup_state(io, 0)) {
        io->write(io->context, 0x0c, 1);
        return -8;
    }
    if (result == 0) {
        for (unsigned index = 0; index < length; index++) {
            data[index] = received[index + 2];
        }
    }
    return result;
}

#endif
