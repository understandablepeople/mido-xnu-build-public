#include <cassert>
#include <cstring>
#include <cerrno>
#include <cstdint>
#define MIDO_BACKEND_HOST_TEST 1
#include "mido_gpu_backend.cpp"
#include "mido_wlan_backend.cpp"

struct __mbuf { int marker; };
static bool hardware_ready;
static unsigned submitted, unmapped, fences, outputs, freed, requests;
static uint32_t chip = 0x05000600U;
static bool ready() { return hardware_ready; }
static uint64_t map_pages(const uint64_t *pages, uint32_t count, bool readonly)
{
    assert(pages[0] == 0x94000000 && count == 1 && readonly);
    return 0x200000000ULL;
}
static void unmap_pages(uint64_t address) { assert(address == 0x200000000ULL); unmapped++; }
static int quad(const struct sweet_gpu_quad *) { return 17; }
static int submit(const sweet_gpu_ib *, uint32_t count, uint32_t *sequence)
{
    assert(count == 1); submitted++; *sequence = 42; return 0;
}
static int wait_fence(uint32_t sequence, uint32_t milliseconds)
{
    assert(sequence == 42 && milliseconds == 100); return 0;
}
static void info(sweet_gpu_info *output)
{
    *output = {chip, 139264, 0x100000, 50000000, 0};
}
static void fence(uintptr_t address, uint64_t physical)
{
    assert(address == 0x10000 && physical == 0x94004000); fences++;
}
extern "C" void mbuf_freem(mbuf_t packet) { assert(packet); freed++; }
static void output(mbuf_t packet) { outputs++; mbuf_freem(packet); }
static int request(int set, uint32_t type, int32_t *value, user_addr_t data, uint32_t *length)
{
    assert(set == 1 && type == 3 && data == 0x1234 && *length == 4);
    *value = 19; requests++; return 0;
}
int main(int argc, char **argv)
{
    bool late = argc == 2 && !std::strcmp(argv[1], "late-fence");
    uint64_t page = 0x94000000;
    uint32_t sequence = 99, length = 4;
    int32_t value = 0;
    sweet_gpu_ib buffer = {0x200000000ULL, 4, 0};
    struct sweet_gpu_quad rectangle = {};
    sweet_gpu_info description = {};
    __mbuf packet = {1};
    assert(!sweet_gpu_ready() && !mido_wlan_backend_ready());
    assert(sweet_gpu_vm_map(&page, 1, true) == 0);
    assert(sweet_gpu_submit(&buffer, 1, &sequence) == ENXIO && sequence == 0);
    assert(sweet_gpu_submit(nullptr, 1, &sequence) == EINVAL);
    assert(sweet_gpu_submit(&buffer, SWEET_GPU_MAX_IBS + 1, &sequence) == EINVAL);
    assert(sweet_gpu_wait(42, 100) == ENXIO);
    assert(sweet_gpu_quad(&rectangle) == ENXIO);
    assert(sweet_gpu_quad(nullptr) == EINVAL);
    sweet_gpu_get_info(&description); assert(description.chip_id == 0);
    mido_wlan_output(&packet); assert(freed == 1 && outputs == 0);
    assert(mido_wlan_a80211(1, 3, &value, 0x1234, &length) == ENXIO);
    assert(mido_wlan_a80211(2, 3, &value, 0x1234, &length) == EINVAL);
    mido_gpu_backend gpu = {ready, map_pages, unmap_pages, quad, submit, wait_fence, info, fence};
    mido_wlan_backend wlan = {ready, output, request};
    assert(mido_gpu_register_backend(nullptr) == EINVAL);
    assert(mido_wlan_register_backend(nullptr) == EINVAL);
    assert(mido_gpu_register_backend(&gpu) == EINVAL);
    assert(mido_wlan_register_backend(&wlan) == EINVAL);
    hardware_ready = true;
    chip = 0x05030002; assert(mido_gpu_register_backend(&gpu) == EINVAL);
    chip = 0x05000600;
    if (!late) sweet_gpu_set_fence_page(0x10000, 0x94004000);
    assert(mido_gpu_register_backend(&gpu) == 0);
    if (late) sweet_gpu_set_fence_page(0x10000, 0x94004000);
    sweet_gpu_set_fence_page(0x10000, 0x94004000);
    assert(fences == 1 && mido_gpu_register_backend(&gpu) == EBUSY);
    assert(mido_wlan_register_backend(&wlan) == 0);
    assert(mido_wlan_register_backend(&wlan) == EBUSY);
    assert(sweet_gpu_ready() && mido_wlan_backend_ready());
    assert(sweet_gpu_vm_map(&page, 1, true) == 0x200000000ULL);
    assert(sweet_gpu_submit(&buffer, 1, &sequence) == 0 && sequence == 42 && submitted == 1);
    assert(sweet_gpu_wait(42, 100) == 0);
    assert(sweet_gpu_quad(&rectangle) == 17);
    sweet_gpu_get_info(&description); assert(description.chip_id == chip);
    mido_wlan_output(&packet); assert(outputs == 1 && freed == 2);
    assert(mido_wlan_a80211(1, 3, &value, 0x1234, &length) == 0 && requests == 1 && value == 19);
    hardware_ready = false;
    assert(!sweet_gpu_ready() && !mido_wlan_backend_ready());
    assert(sweet_gpu_vm_map(&page, 1, true) == 0);
    assert(sweet_gpu_submit(&buffer, 1, &sequence) == ENXIO && submitted == 1);
    sweet_gpu_vm_unmap(0x200000000ULL); assert(unmapped == 1);
    mido_wlan_output(&packet); assert(outputs == 1 && freed == 3);
    assert(mido_wlan_a80211(1, 3, &value, 0x1234, &length) == ENXIO && requests == 1);
    return 0;
}
