#include "input_host.c"
#include <assert.h>

int main(void)
{
    uint32_t random = 0x54358953;
    struct mock_sink sink;
    host_state_reset(&sink);
    for (unsigned iteration = 0; iteration < 10000; iteration++) {
        uint8_t output[289], command[12], report[63];
        memset(output, 0x5a, sizeof(output));
        random = random * 1664525U + 1013904223U;
        unsigned length = 1 + random % 255;
        unsigned writes, delays, consumed;
        int status = host_qup((iteration % 100) ? 0 : iteration % 8,
            length, (random & 256) ? 16 : 32, output + 16, command,
            &writes, &delays, &consumed);
        assert(delays <= 110000);
        for (unsigned index = 0; index < sizeof(output); index++) {
            if (status || index < 16 || index >= 16 + length) {
                assert(output[index] == 0x5a);
            } else {
                assert(output[index] == (uint8_t)(index - 16));
            }
        }
        for (unsigned index = 0; index < sizeof(report); index++) {
            random = random * 1664525U + 1013904223U;
            report[index] = (uint8_t)(random >> 24);
        }
        host_frame(&sink, report, sizeof(report));
    }
    return 0;
}
