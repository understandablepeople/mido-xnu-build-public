#include <assert.h>
#include "mido_touch_trace.h"
#include "mido_touch_edge.h"

int
main(void)
{
    assert(mido_touch_starts_at_edge(500, 1919));
    assert(mido_touch_starts_at_edge(500, 1872));
    assert(!mido_touch_starts_at_edge(500, 1871));
    assert(mido_touch_starts_at_edge(47, 500));
    assert(!mido_touch_starts_at_edge(48, 500));
    assert(!mido_touch_starts_at_edge(-1, 500));
    assert(!mido_touch_starts_at_edge(500, 1920));
    assert(!mido_touch_starts_at_edge(1080, 500));
    assert(mido_touch_starts_at_edge(1032, 500));
    assert(!mido_touch_starts_at_edge(1031, 500));
    struct mido_touch_trace trace = {0};
    mido_touch_trace_update(&trace, 0, 1, 500, 1919, 1000000);
    mido_touch_trace_update(&trace, 1, 1, 510, 1600, 2000000);
    mido_touch_trace_update(&trace, 1, 1, 520, 900, 5000000);
    mido_touch_trace_update(&trace, 1, 0, 520, 900, 6000000);
    assert(trace.events == 4 && trace.start_y == 1919);
    assert(trace.end_y == 900 && trace.min_y == 900 && trace.max_y == 1919);
    assert(trace.ended_ns - trace.started_ns == 5000000 && trace.max_gap_ns == 3000000);
    mido_touch_trace_update(&trace, 0, 1, 10, 20, 10000000);
    assert(trace.events == 1 && trace.min_y == 20 && trace.max_y == 20);
    trace.events = UINT32_MAX;
    assert(trace.started_ns == 10000000 && trace.max_gap_ns == 0);
    mido_touch_trace_update(&trace, 1, 1, 10, 30, 11000000);
    assert(trace.events == UINT32_MAX && trace.max_y == 30);
    return 0;
}
