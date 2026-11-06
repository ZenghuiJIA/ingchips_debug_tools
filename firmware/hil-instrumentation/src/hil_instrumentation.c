#include "hil_instrumentation.h"
#include <string.h>
static hil_config_t g;
static uint32_t head,tail,used,seq,lost,next_token;
static uint8_t ready,busy,draining;
static volatile uint8_t crashing;
static uint8_t output[HIL_MAX_FRAME];
static void u16(uint8_t*p,uint16_t x){p[0]=(uint8_t)x;p[1]=(uint8_t)(x>>8);}
static void u32(uint8_t*p,uint32_t x){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(x>>(i*8));}
static void u64(uint8_t*p,uint64_t x){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(x>>(i*8));}
static uint32_t read32(const uint8_t*p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint32_t update_crc(uint32_t c,const uint8_t*p,size_t n){while(n--){c^=*p++;for(unsigned j=0;j<8;j++)c=(c>>1)^((c&1)?0xedb88320u:0);}return c;}
uint32_t hil_crc32(const uint8_t*p,size_t n){return update_crc(0xffffffffu,p,n)^0xffffffffu;}
static void push(uint8_t b){g.ring[head]=b;head=(head+1)%g.ring_size;used++;}
int hil_event(uint16_t type,const void*payload,uint16_t length){
 if(!ready||length>HIL_MAX_PAYLOAD||(length&&!payload))return -1;
 uint32_t mask=g.port.critical_enter(g.port.user);
 if(busy){lost++;g.port.critical_exit(g.port.user,mask);return -2;}busy=1;
 uint32_t sequence=seq++;uint32_t size=40u+length;
 if(size+2>g.ring_size-used){lost++;busy=0;g.port.critical_exit(g.port.user,mask);return -3;}
 uint8_t header[40]={0};memcpy(header,"HILI",4);header[4]=1;u16(header+6,type);u16(header+8,40);u32(header+12,length);u64(header+16,g.boot_id);u32(header+24,sequence);u64(header+28,g.port.ticks(g.port.user));
 uint32_t crc=update_crc(0xffffffffu,header,36);crc=update_crc(crc,(const uint8_t*)payload,length)^0xffffffffu;u32(header+36,crc);
 push((uint8_t)size);push((uint8_t)(size>>8));for(unsigned i=0;i<40;i++)push(header[i]);for(unsigned i=0;i<length;i++)push(((const uint8_t*)payload)[i]);
 busy=0;g.port.critical_exit(g.port.user,mask);return 0;
}
int hil_clock_info(uint32_t id,uint32_t epoch,uint32_t hz,uint8_t bits,uint8_t flags){
 if(!hz||!bits||bits>64)return -1;uint8_t p[16]={0};u32(p,id);u32(p+4,epoch);u32(p+8,hz);p[12]=bits;p[13]=flags;
 int result=hil_event(HIL_CLOCK_INFO,p,16);if(!result){g.clock_id=id;g.clock_epoch=epoch;g.tick_hz=hz;}return result;
}
int hil_instr_init(const hil_config_t*c){
 if(!c||!c->ring||c->ring_size<128||!c->port.ticks||!c->port.context_id||!c->port.critical_enter||!c->port.critical_exit||!c->port.send||!c->tick_hz||!c->counter_bits||c->counter_bits>64)return -1;
 g=*c;head=tail=used=seq=lost=0;next_token=1;busy=draining=crashing=0;ready=1;
 uint8_t boot[24]={0};memcpy(boot,g.build_id,16);u32(boot+16,1);u32(boot+20,0); /* dictionary 1, no full scheduler capability */
 if(hil_event(HIL_BOOT_INFO,boot,24))return -1;return hil_clock_info(g.clock_id,g.clock_epoch,g.tick_hz,g.counter_bits,g.clock_flags);
}
int hil_event_u32(uint32_t id,uint32_t value){uint8_t p[8];u32(p,id);u32(p+4,value);return hil_event(HIL_MARK,p,8);}
hil_span_token_t hil_span_begin(uint32_t id){hil_span_token_t t={0};if(!ready)return t;
 uint32_t mask=g.port.critical_enter(g.port.user);if(!next_token){g.port.critical_exit(g.port.user,mask);return t;}t.boot_id=g.boot_id;t.token=next_token++;t.context=g.port.context_id(g.port.user);t.span_id=id;g.port.critical_exit(g.port.user,mask);
 uint8_t p[12];u32(p,t.token);u32(p+4,t.context);u32(p+8,id);if(hil_event(HIL_SPAN_BEGIN,p,12))t.token=0;return t;
}
int hil_span_end(hil_span_token_t t){if(!ready||!t.token||t.boot_id!=g.boot_id||t.context!=g.port.context_id(g.port.user))return -1;uint8_t p[12];u32(p,t.token);u32(p+4,t.context);u32(p+8,t.span_id);return hil_event(HIL_SPAN_END,p,12);}
static int irq(uint16_t type,uint32_t id){if(!ready)return -1;uint8_t p[8];u32(p,id);u32(p+4,g.port.context_id(g.port.user));return hil_event(type,p,8);}
int hil_irq_enter(uint32_t id){return irq(HIL_IRQ_ENTER,id);}int hil_irq_exit(uint32_t id){return irq(HIL_IRQ_EXIT,id);}
int hil_instr_drain(void){if(!ready)return -1;uint32_t mask=g.port.critical_enter(g.port.user);if(draining){g.port.critical_exit(g.port.user,mask);return -2;}if(!used){g.port.critical_exit(g.port.user,mask);return 0;}draining=1;
 uint32_t size=g.ring[tail]|((uint32_t)g.ring[(tail+1)%g.ring_size]<<8);if(size>HIL_MAX_FRAME||size+2>used){draining=0;g.port.critical_exit(g.port.user,mask);return -3;}
 for(uint32_t i=0;i<size;i++)output[i]=g.ring[(tail+2+i)%g.ring_size];g.port.critical_exit(g.port.user,mask);
 int result=g.port.send(g.port.user,output,size);mask=g.port.critical_enter(g.port.user);if(!result){tail=(tail+size+2)%g.ring_size;used-=size+2;}draining=0;g.port.critical_exit(g.port.user,mask);return result? -4:1;
}
uint64_t hil_instr_timestamp(void){return ready?g.port.ticks(g.port.user):0;}
uint32_t hil_instr_lost_events(void){if(!ready)return 0;uint32_t mask=g.port.critical_enter(g.port.user);uint32_t value=lost;g.port.critical_exit(g.port.user,mask);return value;}
/* HCR1: commit[4], id[4], length[4], crc[4], opaque explicit-byte payload.
 * Platform must place slot in retained RAM and implement barrier/cache maintenance. */
int hil_crash_capture(const void*data,uint32_t length){if(!ready||!g.crash_slot||g.crash_size<16||length>g.crash_size-16||(length&&!data)||!g.port.commit_barrier)return -1;
 if(crashing||!memcmp(g.crash_slot,"HCR1",4))return -2;crashing=1;memset(g.crash_slot,0,4);u32(g.crash_slot+4,(uint32_t)g.boot_id);u32(g.crash_slot+8,length);if(length)memcpy(g.crash_slot+16,data,length);u32(g.crash_slot+12,(update_crc(update_crc(0xffffffffu,g.crash_slot+4,8),g.crash_slot+16,length)^0xffffffffu));g.port.commit_barrier(g.port.user);memcpy(g.crash_slot,"HCR1",4);g.port.commit_barrier(g.port.user);crashing=0;return 0;}
int hil_crash_read(uint32_t id,uint32_t offset,void*out,uint32_t length){if(!ready||!g.crash_slot||g.crash_size<16||memcmp(g.crash_slot,"HCR1",4)||read32(g.crash_slot+4)!=id||!out)return -1;uint32_t size=read32(g.crash_slot+8);if(size>g.crash_size-16||offset>size||length>size-offset||(update_crc(update_crc(0xffffffffu,g.crash_slot+4,8),g.crash_slot+16,size)^0xffffffffu)!=read32(g.crash_slot+12))return -2;memcpy(out,g.crash_slot+16+offset,length);return 0;}
int hil_crash_clear(uint32_t id){if(!ready||!g.crash_slot||g.crash_size<16||!g.port.commit_barrier||read32(g.crash_slot+4)!=id||memcmp(g.crash_slot,"HCR1",4))return -1;memset(g.crash_slot,0,4);g.port.commit_barrier(g.port.user);return 0;}
