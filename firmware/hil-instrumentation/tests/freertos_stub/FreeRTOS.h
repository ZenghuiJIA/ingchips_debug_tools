#ifndef TEST_FREERTOS_H
#define TEST_FREERTOS_H
#include <stdint.h>
#include <stddef.h>
#define tskKERNEL_VERSION_MAJOR 10
#define configUSE_TRACE_FACILITY 1
#define INCLUDE_xTaskGetSchedulerState 1
#ifndef configGENERATE_RUN_TIME_STATS
#define configGENERATE_RUN_TIME_STATS 1
#endif
typedef unsigned UBaseType_t;
typedef uint32_t StackType_t;
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
#endif
