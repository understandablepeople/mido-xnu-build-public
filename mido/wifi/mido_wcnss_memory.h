#ifndef MIDO_WCNSS_MEMORY_H
#define MIDO_WCNSS_MEMORY_H

#include "mido_wcnss_loader.h"
#include "mido_scm_probe.h"

#ifndef MIDO_PRONTO_SYNC
#define MIDO_PRONTO_SYNC() __asm__ volatile("dsb sy" ::: "memory")
#endif

struct mido_pronto_memory {
    vm_offset_t mapping;
    unsigned claimed;
    int (*dependencies_ready)(void *);
    void *dependencies;
    struct mido_pronto_result result;
};

static inline int
mido_pronto_memory_ready(void *argument)
{
    struct mido_pronto_memory *memory = (struct mido_pronto_memory *)argument;
    return memory->dependencies_ready(memory->dependencies);
}

static inline int
mido_pronto_memory_write(void *argument, uint64_t physical, const uint8_t *source, size_t bytes)
{
    struct mido_pronto_memory *memory = (struct mido_pronto_memory *)argument;
    if (!memory->mapping || !source || !mido_pronto_inside(physical, bytes)) {
        return -1;
    }
    volatile uint8_t *destination = (volatile uint8_t *)(memory->mapping + physical - MIDO_PRONTO_BASE);
    for (size_t index = 0; index < bytes; index++) {
        destination[index] = source[index];
    }
    return 0;
}

static inline int
mido_pronto_memory_zero(void *argument, uint64_t physical, size_t bytes)
{
    struct mido_pronto_memory *memory = (struct mido_pronto_memory *)argument;
    if (!memory->mapping || !mido_pronto_inside(physical, bytes)) {
        return -1;
    }
    volatile uint8_t *destination = (volatile uint8_t *)(memory->mapping + physical - MIDO_PRONTO_BASE);
    for (size_t index = 0; index < bytes; index++) {
        destination[index] = 0;
    }
    return 0;
}

static inline int
mido_pronto_memory_clean(void *argument, uint64_t physical, size_t bytes)
{
    struct mido_pronto_memory *memory = (struct mido_pronto_memory *)argument;
    if (!memory->mapping || !mido_pronto_inside(physical, bytes)) {
        return -1;
    }
    MIDO_PRONTO_SYNC();
    return 0;
}

static inline int64_t
mido_pronto_memory_call(void *argument, uint32_t function, uint32_t info,
    const uint64_t *arguments, uint64_t *secure)
{
    struct mido_pronto_memory *memory = (struct mido_pronto_memory *)argument;
    if (!memory->mapping || !arguments || !secure || arguments[0] != 6 ||
        mido_pronto_memory_ready(argument) != 1) {
        return -1;
    }
    if (function == 0x02000201U) {
        if (info != 0x82 || arguments[2] || (arguments[1] & 4095) ||
            !mido_pronto_inside(arguments[1], 1)) {
            return -1;
        }
    } else if (function == 0x02000202U) {
        if (info != 3 || arguments[1] != MIDO_PRONTO_BASE ||
            (arguments[2] & 4095) || !mido_pronto_inside(arguments[1], arguments[2])) {
            return -1;
        }
    } else if (function != 0x02000205U || info != 1 || arguments[1] || arguments[2]) {
        return -1;
    }
    MIDO_PRONTO_SYNC();
    return mido_scm_call(function | 0x40000000U, info, arguments[0],
        arguments[1], arguments[2], secure);
}

static inline int
mido_pronto_memory_load(struct mido_pronto_memory *memory, const struct mido_pronto_image *image,
    uint64_t arena_base, uint64_t arena_bytes)
{
    if (!memory || !memory->dependencies_ready || mido_pronto_validate(image) ||
        !arena_bytes || arena_base > UINT64_MAX - arena_bytes ||
        (arena_base < MIDO_PRONTO_BASE + MIDO_PRONTO_BYTES &&
            MIDO_PRONTO_BASE < arena_base + arena_bytes)) {
        return -10;
    }
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&memory->claimed, &expected, 1, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        return -11;
    }
    if (memory->mapping || memory->result.stage != MIDO_PRONTO_IDLE ||
        mido_pronto_memory_ready(memory) != 1) {
        return -12;
    }
    uint64_t available = 0;
    if (mido_scm_available(0x40000000U, 0x82000601U, &available) || available != 1) {
        return -13;
    }
    static const uint32_t functions[] = {0x02000201U, 0x02000202U, 0x02000205U};
    for (unsigned index = 0; index < sizeof(functions) / sizeof(functions[0]); index++) {
        if (mido_scm_available(0x40000000U, functions[index], &available) || available != 1) {
            return -13;
        }
    }
    if (mido_scm_available(0x40000000U, 0x02000207U, &available) || available != 1 ||
        mido_scm_query(0x42000207U, 6, &available) || available != 1) {
        return -13;
    }
    if (mido_pronto_memory_ready(memory) != 1) {
        return -12;
    }
    memory->mapping = ml_io_map_unmappable(MIDO_PRONTO_BASE, MIDO_PRONTO_BYTES, VM_WIMG_WCOMB);
    if (!memory->mapping) {
        return -14;
    }
    struct mido_pronto_ops ops = {memory, mido_pronto_memory_ready, mido_pronto_memory_write,
        mido_pronto_memory_zero, mido_pronto_memory_clean, mido_pronto_memory_call};
    int result = mido_pronto_load(image, &ops, &memory->result);
    MIDO_PRONTO_SYNC();
    ml_io_unmap(memory->mapping, MIDO_PRONTO_BYTES);
    memory->mapping = 0;
    return result;
}

#endif
