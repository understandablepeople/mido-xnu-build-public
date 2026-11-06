#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "mido_wcnss_smem.h"

int main(void)
{
    uint32_t table[64 * 8] = {0};
    uint32_t before[64 * 8];
    struct mido_wcnss_channel channel = {99, 99, 99};
    assert(mido_wcnss_find_channel(NULL, 32, &channel) == -1);
    assert(mido_wcnss_find_channel(table, sizeof(table), NULL) == -1);
    assert(mido_wcnss_find_channel(table, 31, &channel) == -1);
    assert(mido_wcnss_find_channel(table, sizeof(table) + 32, &channel) == -1);
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == 0 && channel.cid == 99);
    memcpy(table, "WCNSS_CTRL", 11);
    table[5] = 9;
    table[6] = 6;
    table[7] = 1;
    memcpy(before, table, sizeof(table));
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == 1);
    assert(channel.cid == 9 && channel.type == 6 && channel.references == 1);
    assert(!memcmp(before, table, sizeof(table)));
    table[6] = 15;
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == 0);
    table[6] = 6;
    table[7] = 0;
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == 0);
    table[7] = 1;
    table[5] = 64;
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == -1);
    table[5] = 9;
    memcpy(table + 8, table, 32);
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == -1);
    memset(table, 0xff, sizeof(table));
    assert(mido_wcnss_find_channel(table, sizeof(table), &channel) == 0);
    return 0;
}
