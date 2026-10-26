#ifndef MIDO_DIAGNOSTIC_PLATFORM_CONTRACT_H
#define MIDO_DIAGNOSTIC_PLATFORM_CONTRACT_H

struct mido_platform_contract {
    __UINT64_TYPE__ version;
    __UINT64_TYPE__ cpu_count;
    __UINT64_TYPE__ boot_cpu;
    __UINT64_TYPE__ frequency;
    __UINT64_TYPE__ timer_intid;
    __UINT64_TYPE__ distributor;
    __UINT64_TYPE__ interface_base;
};

static inline int mido_platform_contract_matches(const void *compatible, __SIZE_TYPE__ compatible_size,
    const void *property, __SIZE_TYPE__ property_size, unsigned int cpu_count,
    int boot_cpu, __UINT64_TYPE__ frequency)
{
    const char expected[] = "mido,synthetic-abi-only";
    const unsigned char *bytes = (const unsigned char *)compatible;
    struct mido_platform_contract contract;
    unsigned int index;
    if (!compatible || !property || compatible_size != sizeof(expected) || property_size != sizeof(contract))
        return 0;
    for (index = 0; index < sizeof(expected); index++) {
        if (bytes[index] != (unsigned char)expected[index])
            return 0;
    }
    __builtin_memcpy(&contract, property, sizeof(contract));
    return contract.version == 1 && contract.cpu_count == 1 && contract.boot_cpu == 0 &&
        contract.frequency == 19200000 && contract.timer_intid == 20 &&
        contract.distributor == 0x0b000000 && contract.interface_base == 0x0b002000 &&
        cpu_count == 1 && boot_cpu == 0 && frequency == 19200000;
}

#endif
