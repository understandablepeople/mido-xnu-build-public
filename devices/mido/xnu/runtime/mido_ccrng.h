#ifndef MIDO_CCRNG_H
#define MIDO_CCRNG_H

#include <corecrypto/ccrng.h>

struct ccrng_state *mido_ccrng(int *error);

#endif
