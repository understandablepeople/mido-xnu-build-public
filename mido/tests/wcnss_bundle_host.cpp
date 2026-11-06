#include <cassert>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iterator>
#include <vector>
#include "mido_wcnss_bundle.h"
static void put(std::vector<uint8_t> &blob, size_t offset, uint64_t value)
{
    for (unsigned index = 0; index < 8; index++) blob[offset + index] = uint8_t(value >> (index * 8));
}
static std::vector<uint8_t> fixture()
{
    std::vector<uint8_t> blob(128, 0);
    std::memcpy(blob.data(), "MIDOPRNT", 8);
    put(blob, 8, (1ULL << 32) | 1);
    put(blob, 16, 4096); put(blob, 24, 0x8edfe000);
    put(blob, 32, 88); put(blob, 40, 4); put(blob, 48, blob.size());
    put(blob, 56, MIDO_PRONTO_BASE); put(blob, 64, 96);
    put(blob, 72, 2); put(blob, 80, 16);
    blob[88] = 0x7f; blob[96] = 0x11; blob[97] = 0x22;
    return blob;
}
int main(int argc, char **argv)
{
    mido_pronto_segment segments[32] = {};
    mido_pronto_image image = {};
    auto valid = fixture();
    assert(!mido_pronto_bundle_parse(valid.data(), valid.size(), &image, segments, 32));
    assert(image.metadata[0] == 0x7f && segments[0].data[0] == 0x11);
    assert(segments[0].physical == MIDO_PRONTO_BASE && segments[0].file_bytes == 2);
    for (size_t length = 0; length < valid.size(); length++) {
        assert(mido_pronto_bundle_parse(valid.data(), length, &image, segments, 32) == -1);
    }
    for (unsigned failure = 0; failure < 14; failure++) {
        auto bad = fixture();
        switch (failure) {
        case 0: bad[0] = 0; break;
        case 1: put(bad, 8, 1); break;
        case 2: put(bad, 8, (33ULL << 32) | 1); break;
        case 3: put(bad, 8, (1ULL << 32) | 2); break;
        case 4: put(bad, 32, UINT64_MAX); break;
        case 5: put(bad, 40, UINT64_MAX); break;
        case 6: put(bad, 48, 127); break;
        case 7: put(bad, 64, 88); break;
        case 8: put(bad, 72, 0); break;
        case 9: put(bad, 80, MIDO_PRONTO_BYTES + 1); break;
        case 10: put(bad, 64, UINT64_MAX); break;
        case 11: put(bad, 56, UINT64_MAX); break;
        case 12: put(bad, 24, MIDO_PRONTO_BASE); break;
        case 13: put(bad, 72, 17); break;
        }
        assert(mido_pronto_bundle_parse(bad.data(), bad.size(), &image, segments, 32) == -1);
    }
    auto pure_bss = fixture(); put(pure_bss, 64, 0); put(pure_bss, 72, 0);
    assert(!mido_pronto_bundle_parse(pure_bss.data(), pure_bss.size(), &image, segments, 32));
    assert(!segments[0].data && !segments[0].file_bytes);
    assert(mido_pronto_bundle_parse(valid.data(), valid.size(), &image, segments, 0) == -1);
    assert(mido_pronto_bundle_parse(nullptr, 128, &image, segments, 32) == -1);
    for (unsigned offset = 0; offset < valid.size(); offset++) {
        for (uint8_t value : {uint8_t(0), uint8_t(0xff), uint8_t(0x80)}) {
            auto fuzzed = valid; fuzzed[offset] = value;
            mido_pronto_bundle_parse(fuzzed.data(), fuzzed.size(), &image, segments, 32);
        }
    }
    if (argc == 2) {
        std::ifstream input(argv[1], std::ios::binary);
        assert(input);
        std::vector<uint8_t> own((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
        assert(!mido_pronto_bundle_parse(own.data(), own.size(), &image, segments, 32));
        assert(image.allocation_bytes == 6565888 && image.metadata_bytes == 7324);
    }
    return 0;
}
