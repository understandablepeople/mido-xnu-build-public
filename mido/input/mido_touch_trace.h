#ifndef MIDO_TOUCH_TRACE_H
#define MIDO_TOUCH_TRACE_H

#include <stdint.h>

struct mido_touch_trace {
    uint64_t started_ns, ended_ns, max_gap_ns;
    uint32_t events;
    int32_t start_x, start_y, end_x, end_y, min_y, max_y;
};

static inline void
mido_touch_trace_update(struct mido_touch_trace *trace, int was_down,
    int down, int32_t x, int32_t y, uint64_t now_ns)
{
    if (!was_down && down) {
        trace->events = 0;
        trace->started_ns = now_ns;
        trace->ended_ns = now_ns;
        trace->max_gap_ns = 0;
        trace->start_x = x;
        trace->start_y = y;
        trace->min_y = y;
        trace->max_y = y;
    }
    if (now_ns >= trace->ended_ns && now_ns - trace->ended_ns > trace->max_gap_ns) {
        trace->max_gap_ns = now_ns - trace->ended_ns;
    }
    trace->ended_ns = now_ns;
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
