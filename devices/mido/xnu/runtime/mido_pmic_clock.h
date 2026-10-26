#ifndef MIDO_PMIC_CLOCK_H
#define MIDO_PMIC_CLOCK_H

#ifdef __cplusplus
extern "C" {
#endif
int mido_pmic_clock_available(void);
void mido_pmic_clock_initialize(void);
int mido_pmic_clock_read(unsigned int *seconds);
#ifdef __cplusplus
}
#endif

#endif
