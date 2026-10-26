#ifndef MIDO_XNU_CONFIG_HOST_COMPAT_H
#define MIDO_XNU_CONFIG_HOST_COMPAT_H

#include <string.h>
#include <strings.h>

typedef unsigned char u_char;

#define index strchr
#define rindex strrchr

#endif
