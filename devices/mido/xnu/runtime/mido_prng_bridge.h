#ifndef MIDO_PRNG_BRIDGE_H
#define MIDO_PRNG_BRIDGE_H

#include "kernel_prng.h"

void mido_kernel_prng_install(const struct mido_prng_services *services);
void mido_kernel_prng_install_native(void);
int mido_kernel_prng_is_ready(void);

#endif
