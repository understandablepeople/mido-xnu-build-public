#ifndef MIDO_TOUCH_TRACE_H
#define MIDO_TOUCH_TRACE_H

#include <stdint.h>

struct mido_touch_trace {
    uint32_t events;
    int32_t start_x, start_y, end_x, end_y, min_y, max_y;
};

static inline void
mido_touch_trace_update(struct mido_touch_trace *trace, int was_down,
    int down, int32_t x, int32_t y)
{
    if (!was_down && down) {
        trace->events = 0;
        trace->start_x = x;
        trace->start_y = y;
        trace->min_y = y;
        trace->max_y = y;
    }
    if (trace->events != UINT32_MAX) {
        trace->events++;
    }
    trace->end_x = x;
    trace->end_y = y;
    if (y < trace->min_y) {
        trace->min_y = y;
    }
    if (y > trace->max_y) {
        trace->max_y = y;
    }
}

#endif
