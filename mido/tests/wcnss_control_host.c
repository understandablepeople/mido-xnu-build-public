#include <assert.h>
#include "mido_wcnss_control.h"

static uint32_t
get32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
        (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

int
main(void)
{
    uint8_t nv[65540], output[3090], rebuilt[65536];
    for (unsigned index = 0; index < sizeof(nv); index++) {
        nv[index] = (uint8_t)(index * 13);
    }
    memset(output, 0xa5, sizeof(output));
    assert(!mido_wcnss_version_request(output, 7));
    assert(output[0] == 0xa5);
    assert(mido_wcnss_version_request(output + 1, 8) == 8);
    assert(get32(output + 1) == 0x01000000 && get32(output + 5) == 8);
    const size_t sizes[] = {5, 3075, 3076, 3077, 31723, 65540};
    for (unsigned test = 0; test < sizeof(sizes) / sizeof(sizes[0]); test++) {
        size_t size = sizes[test], assembled = 0;
        unsigned fragments = (unsigned)((size - 4 + 3071) / 3072);
        for (unsigned fragment = 0; fragment < fragments; fragment++) {
            memset(output, 0xa5, sizeof(output));
            size_t length = mido_wcnss_nv_request(nv, size, fragment, 0, output + 1, 3088);
            assert(length >= 17 && length <= 3088);
            assert(output[0] == 0xa5 && output[length + 1] == 0xa5);
            assert(get32(output + 1) == 0x01000002 && get32(output + 5) == length);
            assert(output[9] == fragment && output[10] == 0);
            assert(output[11] == (fragment + 1 == fragments ? 1 : 0));
            assert(output[12] == 0);
            assert(get32(output + 13) == length - 16);
            memcpy(rebuilt + assembled, output + 17, length - 16);
            assembled += length - 16;
        }
        assert(assembled == size - 4 && !memcmp(rebuilt, nv + 4, assembled));
        assert(!mido_wcnss_nv_request(nv, size, fragments, 0, output, sizeof(output)));
    }
    assert(mido_wcnss_nv_request(nv, 5, 0, 1, output, sizeof(output)) == 17);
    assert(output[10] == 1 && output[11] == 0x80);
    memset(output, 0xa5, sizeof(output));
    assert(!mido_wcnss_nv_request(nv, 5, 0, 0, output, 16));
    assert(!mido_wcnss_nv_request(nv, 4, 0, 0, output, sizeof(output)));
    assert(!mido_wcnss_nv_request(nv, 65541, 0, 0, output, sizeof(output)));
    assert(!mido_wcnss_nv_request(NULL, 5, 0, 0, output, sizeof(output)));
    assert(!mido_wcnss_nv_request(nv, 5, 0, 0, NULL, sizeof(output)));
    assert(!mido_wcnss_nv_request(nv, 5, UINT32_MAX, 0, output, sizeof(output)));
    assert(output[0] == 0xa5);
    return 0;
}
