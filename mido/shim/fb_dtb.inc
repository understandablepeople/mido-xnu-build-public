/* strict simple-framebuffer parser, verbatim from mido/m1/fdt_fb.inc (hardware-validated);
 * only the root marker string changed to match tools/pack_mido_boot.py's DTB. */
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
                node->root_marker = equal(value, length, "mido,xnu-shim");
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
