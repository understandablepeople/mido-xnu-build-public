#ifndef MIDO_FT5435_H
#define MIDO_FT5435_H

#include <stdint.h>
#include <stddef.h>

#define MIDO_FT_CONTACTS 10U
#define MIDO_FT_REPORT_BYTES 63U
#define MIDO_FT_PANEL_WIDTH 1080U
#define MIDO_FT_PANEL_HEIGHT 1920U
#define MIDO_FT_KIND_SCREEN 0U
#define MIDO_FT_KIND_HOME 1U
#define MIDO_FT_KIND_MENU 2U
#define MIDO_FT_KIND_BACK 3U
#define MIDO_FT_KIND_OUTSIDE 4U
#define MIDO_FT_READ_COMMAND_BYTES 9U

struct mido_ft_contact {
    uint16_t x, y;
    uint8_t identity, down, kind;
};

struct mido_ft_frame {
    uint8_t count, active;
    struct mido_ft_contact contacts[MIDO_FT_CONTACTS];
};

static inline uint8_t
mido_ft_contact_kind(uint16_t x, uint16_t y)
{
    if (x < MIDO_FT_PANEL_WIDTH && y < MIDO_FT_PANEL_HEIGHT) {
        return MIDO_FT_KIND_SCREEN;
    }
    if (y == 2040) {
        if (x == 500) {
            return MIDO_FT_KIND_HOME;
        }
        if (x == 200) {
            return MIDO_FT_KIND_MENU;
        }
        if (x == 800) {
            return MIDO_FT_KIND_BACK;
        }
    }
    return MIDO_FT_KIND_OUTSIDE;
}

static inline int
mido_ft_decode(const uint8_t *report, size_t length, struct mido_ft_frame *frame)
{
    if (report == NULL || frame == NULL || length != MIDO_FT_REPORT_BYTES ||
        ((report[0] & 0x70U) != 0 &&
        !(report[0] == 0xff && report[1] == 0 && (report[2] & 0xf0U) == 0)) ||
        (report[2] & 0xfU) > MIDO_FT_CONTACTS) {
        return 0;
    }
    struct mido_ft_frame next = {0};
    next.active = report[2] & 0xfU;
    if (next.active == 0) {
        *frame = next;
        return 1;
    }
    uint16_t identities = 0;
    unsigned active = 0;
    for (unsigned index = 0; index < MIDO_FT_CONTACTS; index++) {
        const uint8_t *record = report + 3 + 6 * index;
        uint8_t identity = record[2] >> 4;
        if (identity == 15) {
            break;
        }
        uint8_t event = record[0] >> 6;
        uint16_t mask = (uint16_t)(1U << identity);
        if (event == 3 || (identities & mask) != 0) {
            return 0;
        }
        identities |= mask;
        struct mido_ft_contact *contact = &next.contacts[next.count++];
        contact->x = (uint16_t)(((record[0] & 0xfU) << 8) | record[1]);
        contact->y = (uint16_t)(((record[2] & 0xfU) << 8) | record[3]);
        contact->identity = identity;
        contact->down = event != 1;
        contact->kind = mido_ft_contact_kind(contact->x, contact->y);
        active += contact->down;
    }
    if (active != next.active) {
        return 0;
    }
    *frame = next;
    return 1;
}

static inline size_t
mido_ft_read_command(uint8_t address, uint8_t reg, unsigned length,
    uint8_t *command, size_t capacity)
{
    if (address > 0x7f || length == 0 || length > 255 || command == NULL ||
        capacity < MIDO_FT_READ_COMMAND_BYTES) {
        return 0;
    }
    command[0] = 0x81;
    command[1] = (uint8_t)(address << 1);
    command[2] = 0x82;
    command[3] = 1;
    command[4] = reg;
    command[5] = 0x81;
    command[6] = (uint8_t)((address << 1) | 1U);
    command[7] = 0x87;
    command[8] = (uint8_t)length;
    return MIDO_FT_READ_COMMAND_BYTES;
}

#endif
