#include "hil_freertos.h"
#include <string.h>
#if !defined(tskKERNEL_VERSION_MAJOR) || (tskKERNEL_VERSION_MAJOR != 10 && tskKERNEL_VERSION_MAJOR != 11)
#error "Only explicitly validated FreeRTOS 10/11 API is supported"
#endif
#if configUSE_TRACE_FACILITY != 1
#error "Task snapshots require configUSE_TRACE_FACILITY=1"
#endif
#if INCLUDE_xTaskGetSchedulerState != 1
#error "Task snapshots require INCLUDE_xTaskGetSchedulerState=1"
#endif
#define CAPACITY 16u
static TaskStatus_t statuses[CAPACITY];
static uint8_t payload[36+60*CAPACITY];
typedef struct {TaskHandle_t handle;uint32_t generation,total;uint64_t instance;} identity_t;
static identity_t identities[CAPACITY];static uint64_t next_instance=1,snapshot_id=1;static uint8_t overflow;
static void p32(uint8_t*p,uint32_t x){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(x>>(8*i));}
static void p64(uint8_t*p,uint64_t x){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(x>>(8*i));}
void hil_freertos_task_created(TaskHandle_t handle,uint32_t total){taskENTER_CRITICAL();unsigned free_index=CAPACITY;for(unsigned i=0;i<CAPACITY;i++){if(identities[i].handle==handle){taskEXIT_CRITICAL();return;}if(!identities[i].handle)free_index=i;}if(free_index==CAPACITY||!next_instance)overflow=1;else{identity_t*p=&identities[free_index];p->handle=handle;p->instance=next_instance++;p->generation++;p->total=total;}taskEXIT_CRITICAL();}
void hil_freertos_task_deleted(TaskHandle_t handle){taskENTER_CRITICAL();for(unsigned i=0;i<CAPACITY;i++)if(identities[i].handle==handle)identities[i].handle=0;taskEXIT_CRITICAL();}
int hil_rtos_snapshot(void){
 uint64_t begin=hil_instr_timestamp();
 if(xTaskGetSchedulerState()!=taskSCHEDULER_RUNNING)return -1;
 vTaskSuspendAll();UBaseType_t total=uxTaskGetNumberOfTasks();uint32_t flags=3;
 if(total>CAPACITY||overflow){memset(payload,0,36);p64(payload,snapshot_id++);p32(payload+24,(uint32_t)total);(void)xTaskResumeAll();return hil_event(HIL_TASK_SNAPSHOT,payload,36);}
 /* NULL runtime total avoids assuming configRUN_TIME_COUNTER_TYPE width. */
 UBaseType_t count=uxTaskGetSystemState(statuses,CAPACITY,NULL);memset(payload,0,sizeof(payload));p64(payload,snapshot_id++);p64(payload+8,begin);p64(payload+16,hil_instr_timestamp());p32(payload+24,(uint32_t)total);payload[28]=(uint8_t)count;
 if(count!=total)flags=0;
 for(UBaseType_t i=0;i<count;i++){TaskStatus_t*t=&statuses[i];uint8_t*p=payload+36+i*60;identity_t*id=NULL;for(unsigned j=0;j<CAPACITY;j++)if(identities[j].handle==t->xHandle)id=&identities[j];if(!id){flags=0;continue;}p64(p,id->instance);p32(p+8,id->generation);p[12]=(uint8_t)t->uxCurrentPriority;p[13]=(uint8_t)(t->uxCurrentPriority>>8);p[14]=(uint8_t)t->eCurrentState;p[15]=5;
 p32(p+16,(uint32_t)(uintptr_t)t->pxStackBase);if(id->total){p32(p+20,id->total);p[15]|=2;}p32(p+24,(uint32_t)t->usStackHighWaterMark*sizeof(StackType_t));
#if configGENERATE_RUN_TIME_STATS == 1
 p64(p+28,(uint64_t)t->ulRunTimeCounter);p[15]|=8;
#endif
 if(t->pcTaskName){size_t n=0;while(n<23&&t->pcTaskName[n]){p[36+n]=(uint8_t)t->pcTaskName[n];n++;}}
 }
 payload[30]=(uint8_t)flags; /* scheduler lock does not imply full scheduling trace */
 (void)xTaskResumeAll();return hil_event(HIL_TASK_SNAPSHOT,payload,(uint16_t)(36+count*60));
}
