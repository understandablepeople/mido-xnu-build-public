#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdarg>
#include <cstdio>
#include "mido_rpm_smd.h"

static unsigned mode, reports;
static int discovery;
static uint32_t memory[4096];
static uint32_t before[4096];
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midowifiaudit") && size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static void IOLog(const char *format, ...)
{
    char text[256];
    va_list arguments;
    va_start(arguments, format);
    std::vsnprintf(text, sizeof(text), format, arguments);
    va_end(arguments);
    reports++;
    const char *result = std::strstr(text, "discovery result=");
    if (result) {
        assert(std::sscanf(result, "discovery result=%d", &discovery) == 1);
    }
}
#include "mido_wcnss_audit.h"

static void check(struct mido_rpm_io *io)
{
    std::memcpy(before, memory, sizeof(memory));
    mido_wcnss_audit(io);
    assert(!std::memcmp(before, memory, sizeof(memory)));
}
int main()
{
    struct mido_rpm_io io = {};
    mode = 0;
    mido_wcnss_audit((struct mido_rpm_io *)1);
    assert(reports == 0);
    mode = 2;
    mido_wcnss_audit((struct mido_rpm_io *)1);
    mode = 1;
    mido_wcnss_audit(nullptr);
    check(&io);
    io.smem = memory;
    io.smem_size = 4;
    check(&io);
    io.smem_size = sizeof(memory);
    check(&io);
    memory[48] = 1;
    discovery = 99;
    check(&io);
    assert(discovery == -1);
    uint32_t *allocation = memory + 52 + 4 * MIDO_SMEM_CHANNEL_TBL;
    allocation[0] = 1;
    allocation[1] = 8192;
    allocation[2] = 32;
    uint32_t *table = memory + 8192 / 4;
    std::memcpy(table, "WCNSS_CTRL", 11);
    table[5] = 9;
    table[6] = 6;
    table[7] = 1;
    check(&io);
    assert(discovery == 1);
    allocation[2] = 31;
    check(&io);
    assert(discovery == -1);
    allocation[2] = 32;
    allocation[3] = 0xdead0000;
    check(&io);
    assert(discovery == -1);
    allocation[3] = 0;
    allocation[1] = sizeof(memory) - 16;
    check(&io);
    assert(discovery == -1);
    return 0;
}
