#ifndef HIL_FREERTOS_H
#define HIL_FREERTOS_H
#include "FreeRTOS.h"
#include "task.h"
#include "hil_instrumentation.h"
/* Call creation/deletion hooks from application wrappers, including idle/timer
 * tasks. Handles absent from this registry make the snapshot incomplete. */
void hil_freertos_task_created(TaskHandle_t task,uint32_t total_stack_bytes);
void hil_freertos_task_deleted(TaskHandle_t task);
int hil_rtos_snapshot(void); /* task context only, not ISR/scheduler callback */
#endif
