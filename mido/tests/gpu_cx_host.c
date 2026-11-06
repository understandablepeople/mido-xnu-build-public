#include <string.h>
#include "mido_rpm_smd.h"

static struct mido_rpm_io *expected;
static unsigned calls;
static int response;
static uint32_t captured[10];

static int
capture(struct mido_rpm_io *rpm, uint32_t type, uint32_t resource,
    const uint32_t *kvp, unsigned count, uint32_t message)
{
    calls++;
    captured[0] = type;
    captured[1] = resource;
    captured[2] = count;
    captured[3] = message;
    if (rpm != expected || count != 6) {
        return -99;
    }
    memcpy(captured + 4, kvp, 6 * sizeof(uint32_t));
    return response;
}

#define mido_rpm_request capture
#include "mido_gpu_cx.h"

int
host_vote(int result, uint32_t *output)
{
    struct mido_rpm_io rpm = {0};
    expected = &rpm;
    calls = 0;
    response = result;
    int actual = mido_gpu_cx_vote(&rpm);
    memcpy(output, captured, sizeof(captured));
    output[10] = calls;
    return actual;
}
