#include <pexpert/arm64/board_config.h>
#include <kern/debug.h>

#if !defined(MIDO)
#error MIDO minimal UBSan runtime must not be selected for other platforms
#endif

#define MIDO_UBSAN_HANDLER(operation) \
    void __ubsan_handle_##operation##_minimal(void); \
    void __ubsan_handle_##operation##_minimal_abort(void); \
    __attribute__((no_sanitize("undefined", "integer"), noreturn)) \
    void __ubsan_handle_##operation##_minimal(void) \
    { \
        panic("MIDO UBSan: " #operation); \
    } \
    __attribute__((no_sanitize("undefined", "integer"), noreturn)) \
    void __ubsan_handle_##operation##_minimal_abort(void) \
    { \
        panic("MIDO UBSan: " #operation); \
    }

MIDO_UBSAN_HANDLER(add_overflow)
MIDO_UBSAN_HANDLER(sub_overflow)
MIDO_UBSAN_HANDLER(mul_overflow)
MIDO_UBSAN_HANDLER(divrem_overflow)
MIDO_UBSAN_HANDLER(negate_overflow)
