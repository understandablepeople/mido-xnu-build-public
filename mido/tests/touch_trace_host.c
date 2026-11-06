#include <assert.h>
#include "mido_touch_trace.h"

int
main(void)
{
    struct mido_touch_trace trace = {0};
    mido_touch_trace_update(&trace, 0, 1, 500, 1919);
    mido_touch_trace_update(&trace, 1, 1, 510, 1600);
    mido_touch_trace_update(&trace, 1, 1, 520, 900);
    mido_touch_trace_update(&trace, 1, 0, 520, 900);
    assert(trace.events == 4 && trace.start_y == 1919);
    assert(trace.end_y == 900 && trace.min_y == 900 && trace.max_y == 1919);
    mido_touch_trace_update(&trace, 0, 1, 10, 20);
    assert(trace.events == 1 && trace.min_y == 20 && trace.max_y == 20);
    trace.events = UINT32_MAX;
    mido_touch_trace_update(&trace, 1, 1, 10, 30);
    assert(trace.events == UINT32_MAX && trace.max_y == 30);
    return 0;
}
