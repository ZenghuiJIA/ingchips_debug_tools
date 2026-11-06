#ifndef HIL_CORTEX_M_H
#define HIL_CORTEX_M_H
#include "hil_instrumentation.h"
typedef struct {uint32_t start,length;} hil_ram_range_t;
/* A target-defined reader can refuse unsafe accesses. No peripheral traversal. */
typedef struct { const hil_ram_range_t *ranges; uint32_t range_count;
 int (*read_word)(uint32_t address,uint32_t *value);
 uint32_t (*fault_status)(uint32_t values[4]); /* return validity bitmap; NULL on M0 */
 uint8_t supports_fpu; } hil_cortex_port_t;
int hil_cortex_capture(uint32_t exc_return,uint32_t msp,uint32_t psp,const hil_cortex_port_t *port);
/* GCC entry calls a target-provided wrapper with the original registers.
 * Link the entire path into RAM if target flash can become unavailable.
 * No automatic reset or vector replacement is performed by the SDK. */
void hil_fault_entry_c(uint32_t exc_return,uint32_t msp,uint32_t psp);
#if defined(__arm__) && defined(__GNUC__)
__attribute__((naked)) void hil_fault_entry(void);
#endif
#endif
