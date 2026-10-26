#include <stdint.h>
#include <stddef.h>

void *memset(void *destination, int value, size_t length)
{
    volatile unsigned char *target = destination;
    for (size_t index = 0; index < length; ++index)
        target[index] = (unsigned char)value;
    return destination;
}

void *memcpy(void *destination, const void *source, size_t length)
{
    volatile unsigned char *target = destination;
    const volatile unsigned char *input = source;
    for (size_t index = 0; index < length; ++index)
        target[index] = input[index];
    return destination;
}

struct node_state {
    uint32_t handle;
    uint32_t reference;
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint64_t base;
    uint64_t size;
    unsigned int simple;
    unsigned int format;
    unsigned int chosen;
    unsigned int reserved;
    unsigned int root_marker;
};

struct region {
    uint32_t handle;
    uint64_t base;
    uint64_t size;
};

static uint32_t read_be32(const unsigned char *data)
{
    return ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16)
        | ((uint32_t)data[2] << 8) | data[3];
}

static uint64_t read_be64(const unsigned char *data)
{
    return ((uint64_t)read_be32(data) << 32) | read_be32(data + 4);
}

static int equal(const unsigned char *data, size_t length, const char *text)
{
    size_t index = 0;
    while (index < length && text[index] && data[index] == (unsigned char)text[index])
        ++index;
    return index < length && data[index] == 0 && text[index] == 0 && index + 1 == length;
}

static int find_zero(const unsigned char *data, uint32_t start, uint32_t end, uint32_t *after)
{
    while (start < end) {
        if (data[start++] == 0) {
            *after = start;
            return 1;
        }
    }
    return 0;
}

static int framebuffer(const unsigned char *dtb, struct node_state *result)
{
    struct node_state stack[16] = {0};
    struct region regions[8] = {0};
    uint32_t total, position, end, strings, strings_end, depth = 0, region_count = 0;
    unsigned int marker = 0, found = 0, ended = 0, root_seen = 0;
    if (read_be32(dtb) != 0xd00dfeed || read_be32(dtb + 20) != 17)
        return 0;
    total = read_be32(dtb + 4);
    position = read_be32(dtb + 8);
    strings = read_be32(dtb + 12);
    if (total < 56 || total > 65536 || position < 40 || position % 4 || strings < 40)
        return 0;
    if (position > total || read_be32(dtb + 36) > total - position
        || strings > total || read_be32(dtb + 32) > total - strings)
        return 0;
    end = position + read_be32(dtb + 36);
    strings_end = strings + read_be32(dtb + 32);
    while (position + 4 <= end) {
        uint32_t token = read_be32(dtb + position);
        position += 4;
        if (token == 1) {
            uint32_t after;
            if (depth == 16 || !find_zero(dtb, position, end, &after))
                return 0;
            if (depth == 0 && (root_seen++ || after != position + 1))
                return 0;
            stack[depth] = (struct node_state){0};
            stack[depth].chosen = depth == 1 && equal(dtb + position, after - position, "chosen");
            stack[depth].reserved = depth == 1 && equal(dtb + position, after - position, "reserved-memory");
            ++depth;
            position = (after + 3) & ~3U;
        } else if (token == 2) {
            struct node_state *node;
            if (!depth)
                return 0;
            node = &stack[--depth];
            if (depth == 0)
                marker = node->root_marker;
            if (depth == 2 && stack[1].chosen && node->simple) {
                if (found++)
                    return 0;
                *result = *node;
            }
            if (depth == 2 && stack[1].reserved && node->handle && node->size) {
                if (region_count == 8)
                    return 0;
                regions[region_count++] = (struct region){node->handle, node->base, node->size};
            }
        } else if (token == 3) {
            uint32_t length, name_offset, after;
            const unsigned char *name, *value;
            struct node_state *node;
            if (!depth || end - position < 8)
                return 0;
            length = read_be32(dtb + position);
            name_offset = read_be32(dtb + position + 4);
            position += 8;
            if (length > end - position || name_offset >= strings_end - strings
                || !find_zero(dtb, strings + name_offset, strings_end, &after))
                return 0;
            name = dtb + strings + name_offset;
            name_offset = after - strings - name_offset;
            value = dtb + position;
            node = &stack[depth - 1];
            if (equal(name, name_offset, "compatible")) {
                node->simple = equal(value, length, "simple-framebuffer");
                node->root_marker = equal(value, length, "mido,arm64-screen-test");
            } else if (equal(name, name_offset, "format")) {
                node->format = equal(value, length, "r8g8b8");
            } else if (length == 4) {
                uint32_t number = read_be32(value);
                if (equal(name, name_offset, "phandle")) node->handle = number;
                if (equal(name, name_offset, "memory-region")) node->reference = number;
                if (equal(name, name_offset, "width")) node->width = number;
                if (equal(name, name_offset, "height")) node->height = number;
                if (equal(name, name_offset, "stride")) node->stride = number;
            } else if (length == 16 && equal(name, name_offset, "reg")) {
                node->base = read_be64(value);
                node->size = read_be64(value + 8);
            }
            position = (position + length + 3) & ~3U;
        } else if (token == 9) {
            ended = depth == 0;
            break;
        } else if (token != 4) {
            return 0;
        }
    }
    if (!ended || !marker || found != 1 || !result->reference || !result->format
        || result->width != 1080 || result->height != 1920 || result->stride != 3240)
        return 0;
    found = 0;
    for (uint32_t index = 0; index < region_count; ++index) {
        if (regions[index].handle == result->reference) {
            result->base = regions[index].base;
            result->size = regions[index].size;
            ++found;
        }
    }
    return found == 1 && result->base == 0x90001000
        && result->size >= 3240U * 1920U && result->size <= 0x013ff000;
}

static const unsigned char glyphs[26][7] = {
    {14,17,17,31,17,17,17}, {30,17,17,30,17,17,30},
    {14,17,16,16,16,17,14}, {30,17,17,17,17,17,30},
    {31,16,16,30,16,16,31}, {31,16,16,30,16,16,16},
    {14,17,16,23,17,17,14}, {17,17,17,31,17,17,17},
    {31,4,4,4,4,4,31}, {7,2,2,2,2,18,12},
    {17,18,20,24,20,18,17}, {16,16,16,16,16,16,31},
    {17,27,21,21,17,17,17}, {17,25,21,19,17,17,17},
    {14,17,17,17,17,17,14}, {30,17,17,30,16,16,16},
    {14,17,17,17,21,18,13}, {30,17,17,30,20,18,17},
    {15,16,16,14,1,1,30}, {31,4,4,4,4,4,4},
    {17,17,17,17,17,17,14}, {17,17,17,17,17,10,4},
    {17,17,17,21,21,21,10}, {17,17,10,4,10,17,17},
    {17,17,10,4,4,4,4}, {31,1,2,4,8,16,31}
};

static const unsigned char digits[10][7] = {
    {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14},
    {14,17,1,2,4,8,31}, {30,1,1,14,1,1,30},
    {2,6,10,18,31,2,2}, {31,16,16,30,1,1,30},
    {14,16,16,30,17,17,14}, {31,1,2,4,8,8,8},
    {14,17,17,14,17,17,14}, {14,17,17,15,1,1,14}
};

static void pixel(volatile unsigned char *base, unsigned int column, unsigned int row, unsigned char value)
{
    size_t offset = (size_t)row * 3240 + column * 3;
    base[offset] = value;
    base[offset + 1] = value;
    base[offset + 2] = value;
}

static void text(volatile unsigned char *base, unsigned int row, const char *message)
{
    unsigned int column = 60;
    while (*message && column + 40 < 1080) {
        const unsigned char *glyph = NULL;
        if (*message >= 'A' && *message <= 'Z') glyph = glyphs[*message - 'A'];
        if (*message >= '0' && *message <= '9') glyph = digits[*message - '0'];
        if (glyph) {
            for (unsigned int vertical = 0; vertical < 56; ++vertical)
                for (unsigned int horizontal = 0; horizontal < 40; ++horizontal)
                    if (glyph[vertical / 8] & (16U >> (horizontal / 8)))
                        pixel(base, column + horizontal, row + vertical, 255);
        }
        column += 48;
        ++message;
    }
}

#if defined(MIDO_DIAGNOSTICS)
__attribute__((visibility("hidden")))
void screen_message(uintptr_t address, unsigned int row, const char *message)
{
    volatile unsigned char *base = (volatile unsigned char *)address;
    if (address != 0x90001000 || row > 580)
        return;
    for (unsigned int vertical = row; vertical < row + 64; ++vertical)
        for (unsigned int horizontal = 0; horizontal < 1080; ++horizontal)
            pixel(base, horizontal, vertical, 0);
    text(base, row, message);
    __asm__ volatile("dsb sy" ::: "memory");
}

extern void diagnostics_main(uintptr_t base, unsigned long level);
#endif

__attribute__((visibility("hidden")))
void screen_main(uintptr_t dtb_address, unsigned long level)
{
    struct node_state fb = {0};
    volatile unsigned char *base;
    if (dtb_address < 0x10000000 || dtb_address > 0x849f0000 || (dtb_address & 7))
        return;
    if (!framebuffer((const unsigned char *)dtb_address, &fb))
        return;
    base = (volatile unsigned char *)(uintptr_t)fb.base;
    for (unsigned int row = 0; row < 720; ++row)
        for (unsigned int column = 0; column < 1080; ++column)
            pixel(base, column, row, row >= 640 ? (unsigned char)(((column / 90) & 1) * 255) : 0);
#if defined(MIDO_DIAGNOSTICS)
    diagnostics_main((uintptr_t)base, level);
#else
    text(base, 60, "MIDO ARM64");
    text(base, 160, level == 1 ? "EL1" : "EL2");
    text(base, 260, "DTB OK");
    text(base, 360, "RAM ONLY");
    text(base, 460, "NOT IOS");
#endif
    __asm__ volatile("dsb sy" ::: "memory");
}
