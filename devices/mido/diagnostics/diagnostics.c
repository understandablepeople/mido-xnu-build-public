#include <stdint.h>

struct brk_report {
    uint64_t syndrome;
    uint64_t continuation;
    uint64_t saved_status;
};

extern void screen_message(uintptr_t base, unsigned int row, const char *message);
extern uint64_t diagnostics_brk_probe(struct brk_report *report);
extern uint64_t diagnostics_counter(void);
extern uint64_t diagnostics_frequency(void);

static void hex_message(uintptr_t base, unsigned int row, const char *label, uint64_t value, unsigned int count)
{
    static const char alphabet[] = "0123456789ABCDEF";
    char message[22];
    unsigned int position = 0;
    while (label[position] && position < 4) {
        message[position] = label[position];
        ++position;
    }
    for (unsigned int digit = 0; digit < count; ++digit)
        message[position++] = alphabet[(value >> ((count - digit - 1) * 4)) & 15];
    message[position] = 0;
    screen_message(base, row, message);
}

void diagnostics_fault(uintptr_t base, uint64_t syndrome, uint64_t address, uint64_t fault_address, uint64_t saved_status)
{
    screen_message(base, 20, "EXCEPTION HALTED");
    hex_message(base, 100, "ESR ", syndrome, 16);
    hex_message(base, 180, "ELR ", address, 16);
    hex_message(base, 260, "FAR ", fault_address, 16);
    hex_message(base, 340, "SPS ", saved_status, 16);
    screen_message(base, 420, "NO RESUME");
    screen_message(base, 500, "RAM ONLY");
    screen_message(base, 580, "NOT XNU OR IOS");
    __asm__ volatile("dsb sy" ::: "memory");
}

void diagnostics_main(uintptr_t base, unsigned long level)
{
    struct brk_report report = {0};
    uint64_t frequency, first, latest, target;
    unsigned int backwards = 0;
    if (level != 1)
        return;
    __asm__ volatile("mov x28, %0" :: "r"(base) : "memory");
    screen_message(base, 20, "MIDO DIAG EL1");
    screen_message(base, 100, "BRK TEST");
    if (diagnostics_brk_probe(&report) != 1 || report.syndrome != 0xf2004d49
        || (report.saved_status & 15) != 5) {
        screen_message(base, 100, "BRK CHECK FAILED");
        return;
    }
    screen_message(base, 100, "BRK ERET OK");
    hex_message(base, 180, "ESR ", report.syndrome, 8);
    frequency = diagnostics_frequency();
    hex_message(base, 260, "FRQ ", frequency, 8);
    if (!frequency || frequency > 1000000000) {
        screen_message(base, 340, "BAD FREQUENCY");
        return;
    }
    first = diagnostics_counter();
    latest = first;
    target = frequency / 1000;
    for (unsigned int attempt = 0; attempt < 1000000; ++attempt) {
        uint64_t sample = diagnostics_counter();
        if (sample < latest) {
            backwards = 1;
            break;
        }
        latest = sample;
        if (latest - first >= target && latest > first)
            break;
    }
    screen_message(base, 340, backwards ? "COUNTER BACKWARDS" : latest > first ? "COUNTER OK" : "COUNTER STALLED");
    hex_message(base, 420, "CNT ", latest, 16);
    hex_message(base, 500, "DEL ", latest - first, 16);
    screen_message(base, 580, "NOT XNU OR IOS");
    __asm__ volatile("dsb sy" ::: "memory");
}
