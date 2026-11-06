#include "hil_cortex_m.h"
#include <string.h>
static void put(uint8_t*p,uint32_t value){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(value>>(8*i));}
static int allowed(const hil_cortex_port_t*p,uint32_t address,uint32_t bytes){
 if(address&3u)return 0;
 for(uint32_t i=0;i<p->range_count;i++){uint32_t start=p->ranges[i].start,length=p->ranges[i].length;if(length<=UINT32_MAX-start&&address>=start&&address-start<=length&&bytes<=length-(address-start))return 1;}
 return 0;
}
int hil_cortex_capture(uint32_t exc,uint32_t msp,uint32_t psp,const hil_cortex_port_t*p){
 uint8_t record[76]={0};memcpy(record,"CMF1",4);put(record+4,exc);put(record+8,msp);put(record+12,psp);uint32_t valid=0;
 if(!p||!p->ranges||!p->read_word||p->range_count>64)return hil_crash_capture(record,sizeof(record));
 uint32_t scb[4]={0},scb_valid=p->fault_status?p->fault_status(scb):0;for(unsigned i=0;i<4;i++)if(scb_valid&(1u<<i)){put(record+60+i*4,scb[i]);valid|=1u<<(8+i);}
 int recognized=exc==0xfffffff1u||exc==0xfffffff9u||exc==0xfffffffdu;
 int extended=exc==0xffffffe1u||exc==0xffffffe9u||exc==0xffffffedu;
 uint32_t sp=(exc&4u)?psp:msp,skip=extended?72u:0u;
 /* Stacking/unstacking faults invalidate an otherwise plausible SP. */
 if((recognized||(extended&&p->supports_fpu))&&!(scb[0]&0x3838u)&&sp<=UINT32_MAX-skip&&allowed(p,sp+skip,32)){
   uint32_t values[8]={0};int readable=1;
   for(unsigned i=0;i<8;i++)if(p->read_word(sp+skip+i*4,&values[i])){readable=0;break;}
   if(readable&&(values[7]&(1u<<24))){for(unsigned i=0;i<8;i++)put(record+28+i*4,values[i]);valid|=1u;put(record+20,sp);put(record+24,skip+32u+((values[7]&(1u<<9))?4u:0u));}
 }
 put(record+16,valid);return hil_crash_capture(record,sizeof(record));
}
#if defined(__arm__) && defined(__GNUC__)
__attribute__((naked)) void hil_fault_entry(void){__asm volatile("mov r0, lr\n mrs r1, msp\n mrs r2, psp\n b hil_fault_entry_c\n");}
#endif
