#include "mido_ccrng.h"
#ifndef __enum_decl
#define __enum_decl(name, type, ...) typedef type name; enum __VA_ARGS__
#endif
#include <libkern/crypto/register_crypto.h>

_Static_assert(_Generic(&mido_ccrng, ccrng_fn_t: 1, default: 0), "ccrng getter ABI");

struct ccrng_state *mido_ccrng_test_get(int *error)
{
    return mido_ccrng(error);
}

int mido_ccrng_test_generate(struct ccrng_state *state, size_t length, void *output)
{
    return ccrng_generate(state, length, output);
}

int mido_ccrng_test_wrong_state(struct ccrng_state *state, size_t length, void *output)
{
    struct ccrng_state fake = *state;
    return ccrng_generate(&fake, length, output);
}
