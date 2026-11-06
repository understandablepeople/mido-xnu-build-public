#ifndef MIDO_TOUCH_EDGE_H
#define MIDO_TOUCH_EDGE_H

#include <stdint.h>

static inline int
mido_touch_starts_at_edge(int32_t x, int32_t y)
{
    return x >= 0 && x < 1080 && y >= 0 && y < 1920 &&
        (x < 48 || x >= 1032 || y < 48 || y >= 1872);
}

#endif
