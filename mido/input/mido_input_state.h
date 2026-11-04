#ifndef MIDO_INPUT_STATE_H
#define MIDO_INPUT_STATE_H

#include "mido_ft5435.h"

struct mido_input_slot {
    uint16_t x, y;
    uint8_t identity, down;
};

struct mido_input_state {
    struct mido_input_slot slots[MIDO_FT_CONTACTS];
    uint8_t home;
};

struct mido_input_sink {
    void *context;
    void (*touch)(void *, unsigned, int, unsigned, unsigned);
    void (*home)(void *, int);
};

static inline void
mido_input_release(struct mido_input_state *state, struct mido_input_sink *sink)
{
    for (unsigned slot = 0; slot < MIDO_FT_CONTACTS; slot++) {
        if (state->slots[slot].down) {
            sink->touch(sink->context, slot, 0, state->slots[slot].x, state->slots[slot].y);
            state->slots[slot].down = 0;
        }
    }
    if (state->home) {
        sink->home(sink->context, 0);
        state->home = 0;
    }
}

static inline void
mido_input_frame(struct mido_input_state *state, struct mido_input_sink *sink,
    const struct mido_ft_frame *frame)
{
    uint16_t present = 0;
    unsigned home = 0;
    for (unsigned index = 0; index < frame->count; index++) {
        const struct mido_ft_contact *contact = &frame->contacts[index];
        if (contact->down && contact->kind == MIDO_FT_KIND_SCREEN) {
            present |= (uint16_t)(1U << contact->identity);
        }
        home |= contact->down && contact->kind == MIDO_FT_KIND_HOME;
    }
    for (unsigned slot = 0; slot < MIDO_FT_CONTACTS; slot++) {
        struct mido_input_slot *previous = &state->slots[slot];
        if (previous->down && (present & (1U << previous->identity)) == 0) {
            sink->touch(sink->context, slot, 0, previous->x, previous->y);
            previous->down = 0;
        }
    }
    for (unsigned index = 0; index < frame->count; index++) {
        const struct mido_ft_contact *contact = &frame->contacts[index];
        if (!contact->down || contact->kind != MIDO_FT_KIND_SCREEN) {
            continue;
        }
        unsigned slot = 0;
        for (; slot < MIDO_FT_CONTACTS; slot++) {
            if (state->slots[slot].down && state->slots[slot].identity == contact->identity) {
                break;
            }
        }
        if (slot == MIDO_FT_CONTACTS) {
            for (slot = 0; slot < MIDO_FT_CONTACTS && state->slots[slot].down; slot++) {
            }
        }
        if (slot == MIDO_FT_CONTACTS) {
            continue;
        }
        struct mido_input_slot *previous = &state->slots[slot];
        if (!previous->down || previous->x != contact->x || previous->y != contact->y) {
            sink->touch(sink->context, slot, 1, contact->x, contact->y);
        }
        previous->identity = contact->identity;
        previous->down = 1;
        previous->x = contact->x;
        previous->y = contact->y;
    }
    if (home != state->home) {
        sink->home(sink->context, home);
        state->home = (uint8_t)home;
    }
}

#endif
