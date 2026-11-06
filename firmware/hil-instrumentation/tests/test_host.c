#include "hil_instrumentation.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint64_t clock_value; static uint8_t output[8192]; static size_t output_length; static uint32_t critical;
static int fail_send, recurse;
static uint64_t ticks_cb(void *p){(void)p;if(recurse){recurse=0;assert(hil_event_u32(99,0)==-2);}return clock_value++;}
static uint32_t context_cb(void *p){(void)p;return 7;}
static int send_cb(void *p,const uint8_t *data,size_t n){(void)p;assert(critical==0);if(fail_send)return -1;assert(output_length+n<=sizeof(output));memcpy(output+output_length,data,n);output_length+=n;return 0;}
static uint32_t enter_cb(void *p){(void)p;return critical++;} static void exit_cb(void *p,uint32_t old){(void)p;critical=old;}
static void barrier(void *p){(void)p;}
int main(int argc,char**argv){uint8_t ring[256],crash[128]={0};hil_config_t cfg={0};cfg.ring=ring;cfg.ring_size=sizeof(ring);cfg.crash_slot=crash;cfg.crash_size=sizeof(crash);cfg.boot_id=7;cfg.clock_id=1;cfg.tick_hz=1000000;cfg.counter_bits=64;cfg.clock_flags=4;cfg.build_id[0]=1;cfg.port=(hil_port_t){ticks_cb,context_cb,enter_cb,exit_cb,send_cb,barrier,0};
 assert(hil_crc32((const uint8_t*)"123456789",9)==0xcbf43926u);assert(hil_instr_init(&cfg)==0);assert(output_length==0);while(hil_instr_drain()>0){}assert(output_length==120);assert(memcmp(output,"HILI",4)==0);
 hil_span_token_t token=hil_span_begin(42);assert(token.token);assert(hil_span_end(token)==0);fail_send=1;assert(hil_instr_drain()==-4);fail_send=0;while(hil_instr_drain()>0){}
 recurse=1;assert(hil_event_u32(1,2)==0);assert(hil_instr_lost_events()==1);for(unsigned i=0;i<20;i++)(void)hil_event_u32(1,i);assert(hil_instr_lost_events()>1);assert(critical==0);while(hil_instr_drain()>0){}
 uint8_t value[4]={0x34,0x12,0,0},read[4]={0};assert(hil_crash_capture(value,4)==0);assert(hil_crash_capture(value,4)==-2);assert(hil_crash_read(7,0,read,4)==0&&!memcmp(read,value,4));assert(hil_crash_clear(8)==-1);assert(hil_crash_clear(7)==0);
 if(argc>1){FILE*f=fopen(argv[1],"wb");assert(f);assert(fwrite(output,1,output_length,f)==output_length);fclose(f);}return 0;}
