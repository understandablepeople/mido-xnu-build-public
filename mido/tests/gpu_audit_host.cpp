#include <cstddef>
#include <cstdint>
#include <cstring>

typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;

static int argument_present, argument_mode, mapping_failure;
static unsigned mapping_count, logging_count;
alignas(16384) static uint32_t registers[0x8000 / sizeof(uint32_t)];

static bool
PE_parse_boot_argn(const char *name, void *output, int size)
{
    if (std::strcmp(name, "midogpu") || size != sizeof(int) || !argument_present) {
        return false;
    }
    std::memcpy(output, &argument_mode, sizeof(argument_mode));
    return true;
}

static void IOLog(const char *, ...) { logging_count++; }

extern "C" vm_offset_t
ml_io_map(vm_offset_t address, vm_size_t size)
{
    mapping_count++;
    if (address != 0x01858000U || size != sizeof(registers) || mapping_failure) {
        return 0;
    }
    return (vm_offset_t)registers;
}

#define MIDO_GPU_AUDIT_BARRIER() ((void)0)
#include "../gpu/mido_gpu_audit.h"
#undef MIDO_GPU_AUDIT_BARRIER

extern "C" unsigned
host_audit(int present, int mode, int failure)
{
    argument_present = present;
    argument_mode = mode;
    mapping_failure = failure;
    mapping_count = logging_count = 0;
    std::memset(registers, 0x5a, sizeof(registers));
    mido_gpu_audit();
    for (unsigned index = 0; index < sizeof(registers) / sizeof(registers[0]); index++) {
        if (registers[index] != 0x5a5a5a5aU) {
            return 0xffffffffU;
        }
    }
    return mapping_count * 100 + logging_count;
}
