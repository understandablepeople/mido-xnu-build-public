#include "mido_qup_v2.h"
#include "mido_input_state.h"
#include <string.h>

struct mock_qup {
    uint32_t registers[0x500 / 4];
    uint8_t input[257], output[12];
    unsigned input_length, consumed, output_length, writes, delays;
    unsigned block, mode, runtime_reads;
};

static uint32_t
mock_read(void *context, uint32_t offset)
{
    struct mock_qup *mock = context;
    if (offset == 0x30) {
        return mock->mode == 1 ? 0xffffffffU : 0x20070000U;
    }
    if (offset == 4) {
        return mock->mode == 2 ? 0 : (mock->registers[1] & 3U) | 0x14U;
    }
    if (offset == 8) {
        return mock->block == 32 ? 2U << 5 : 0;
    }
    if (offset == 0x404) {
        return mock->mode == 3 ? 8U : (mock->mode == 7 ? 0x100U : 0);
    }
    if (offset == 0x1c) {
        return mock->mode == 4 ? 4U : 0;
    }
    if (offset == 0x18) {
        mock->runtime_reads++;
        if (mock->mode == 5 || (mock->mode == 6 && mock->consumed >= 16)) {
            return 0;
        }
        if (mock->mode == 9 && mock->consumed >= 16) {
            return 0x2000U;
        }
        return mock->consumed < mock->input_length ? (mock->mode == 8 ? 0x2020U : 0x2320U) : 0x800U;
    }
    if (offset == 0x218) {
        uint32_t word = 0;
        for (unsigned byte = 0; byte < 4; byte++) {
            if (mock->consumed < mock->input_length) {
                word |= (uint32_t)mock->input[mock->consumed++] << (8 * byte);
            }
        }
        return word;
    }
    return mock->registers[offset / 4];
}

static void
mock_write(void *context, uint32_t offset, uint32_t value)
{
    struct mock_qup *mock = context;
    mock->writes++;
    if (offset == 0x0c) {
        mock->registers[1] = 0;
    } else if (offset == 0x110) {
        for (unsigned byte = 0; byte < 4 && mock->output_length < 12; byte++) {
            mock->output[mock->output_length++] = (uint8_t)(value >> (8 * byte));
        }
    } else if (offset == 0x1c || offset == 0x404 || offset == 0x18) {
        return;
    } else {
        mock->registers[offset / 4] = value;
    }
}

static void
mock_delay(void *context, unsigned microseconds)
{
    struct mock_qup *mock = context;
    mock->delays += microseconds;
}

int host_qup(unsigned mode, unsigned length, unsigned block, uint8_t *result,
    uint8_t *command, unsigned *writes, unsigned *delays, unsigned *consumed)
{
    struct mock_qup mock = {0};
    mock.mode = mode;
    mock.block = block;
    mock.input_length = length + 2;
    if (mock.input_length > sizeof(mock.input)) {
        mock.input_length = sizeof(mock.input);
    }
    mock.input[0] = 0x85;
    mock.input[1] = (uint8_t)length;
    for (unsigned index = 2; index < mock.input_length; index++) {
        mock.input[index] = (uint8_t)(index - 2);
    }
    struct mido_qup_io io = {&mock, mock_read, mock_write, mock_delay, 0, 0, 0, 0};
    int status = mido_qup_read(&io, 0x38, 0, result, length);
    memcpy(command, mock.output, sizeof(mock.output));
    *writes = mock.writes;
    *delays = mock.delays;
    *consumed = mock.consumed;
    return status;
}

struct mock_event {
    unsigned kind, slot, down, x, y;
};

struct mock_sink {
    struct mido_input_state state;
    struct mock_event events[256];
    unsigned count;
};

static void
mock_touch(void *context, unsigned slot, int down, unsigned x, unsigned y)
{
    struct mock_sink *mock = context;
    if (mock->count < 256) {
        mock->events[mock->count++] = (struct mock_event){0, slot, (unsigned)down, x, y};
    }
}

static void
mock_home(void *context, int down)
{
    struct mock_sink *mock = context;
    if (mock->count < 256) {
        mock->events[mock->count++] = (struct mock_event){1, 0, (unsigned)down, 0, 0};
    }
}

void host_state_reset(struct mock_sink *mock)
{
    memset(mock, 0, sizeof(*mock));
}

unsigned host_frame(struct mock_sink *mock, const uint8_t *report, size_t length)
{
    struct mido_ft_frame frame;
    struct mido_input_sink sink = {mock, mock_touch, mock_home};
    mock->count = 0;
    if (report == NULL) {
        mido_input_release(&mock->state, &sink);
        return 1;
    }
    if (!mido_ft_decode(report, length, &frame)) {
        return 0;
    }
    mido_input_frame(&mock->state, &sink, &frame);
    return 1;
}
