#ifndef TEST_TASK_H
#define TEST_TASK_H
#include "FreeRTOS.h"
typedef void *TaskHandle_t;
typedef struct { TaskHandle_t xHandle;const char *pcTaskName;UBaseType_t uxCurrentPriority;unsigned eCurrentState;StackType_t *pxStackBase;uint16_t usStackHighWaterMark;uint32_t ulRunTimeCounter;} TaskStatus_t;
#define taskSCHEDULER_RUNNING 2
int xTaskGetSchedulerState(void);
void vTaskSuspendAll(void);
int xTaskResumeAll(void);
UBaseType_t uxTaskGetNumberOfTasks(void);
UBaseType_t uxTaskGetSystemState(TaskStatus_t*,UBaseType_t,uint32_t*);
#endif
