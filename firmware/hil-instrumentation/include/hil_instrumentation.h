#ifndef HIL_INSTRUMENTATION_H
#define HIL_INSTRUMENTATION_H
#include <stddef.h>
#include <stdint.h>
#define HIL_MAX_PAYLOAD 1024u
#define HIL_MAX_FRAME 1064u
enum { HIL_BOOT_INFO=1,HIL_CLOCK_INFO,HIL_MARK,HIL_SPAN_BEGIN,HIL_SPAN_END,HIL_IRQ_ENTER,HIL_IRQ_EXIT,HIL_TASK_SNAPSHOT,HIL_TASK_SWITCH,HIL_LOSS,HIL_CRASH_CHUNK };
/* Ports must be nonblocking. critical_enter saves the old mask; exit restores it.
 * send returns zero only after accepting the entire frame. drain runs in task context.
 * NMI/HardFault must call only hil_crash_capture, never the normal event API. */
typedef struct {
 uint64_t (*ticks)(void*); uint32_t (*context_id)(void*);
 uint32_t (*critical_enter)(void*); void (*critical_exit)(void*,uint32_t);
 int (*send)(void*,const uint8_t*,size_t); void (*commit_barrier)(void*);
 void *user;
} hil_port_t;
typedef struct { uint8_t *ring; uint32_t ring_size; uint8_t *crash_slot; uint32_t crash_size;
 uint64_t boot_id; uint8_t build_id[16]; uint32_t clock_id,clock_epoch,tick_hz;
 uint8_t counter_bits,clock_flags; hil_port_t port; } hil_config_t;
typedef struct { uint64_t boot_id; uint32_t token,context,span_id; } hil_span_token_t;
int hil_instr_init(const hil_config_t*);
int hil_event(uint16_t type,const void *payload,uint16_t length);
int hil_event_u32(uint32_t event_id,uint32_t value);
hil_span_token_t hil_span_begin(uint32_t id);
int hil_span_end(hil_span_token_t token);
int hil_irq_enter(uint32_t irq); int hil_irq_exit(uint32_t irq);
int hil_instr_drain(void); /* sends at most one frame; preserves frame on send failure */
uint32_t hil_instr_lost_events(void);
uint64_t hil_instr_timestamp(void);
int hil_clock_info(uint32_t id,uint32_t epoch,uint32_t hz,uint8_t bits,uint8_t flags);
int hil_crash_capture(const void *data,uint32_t length); /* independent fixed slot, no locks/logging */
int hil_crash_read(uint32_t record_id,uint32_t offset,void *out,uint32_t length);
int hil_crash_clear(uint32_t record_id); /* call only following explicit host acknowledgement */
uint32_t hil_crc32(const uint8_t*,size_t);
#ifdef HIL_INSTRUMENTATION_DISABLED
#define HIL_EVENT(id,value) ((void)0)
#define HIL_SPAN_BEGIN(id) ((hil_span_token_t){0})
#define HIL_SPAN_END(token) ((void)0)
#else
#define HIL_EVENT(id,value) ((void)hil_event_u32((id),(value)))
#define HIL_SPAN_BEGIN(id) hil_span_begin(id)
#define HIL_SPAN_END(token) ((void)hil_span_end(token))
#endif
#endif
