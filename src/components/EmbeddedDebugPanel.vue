<script setup lang="ts">
import { ref,onMounted,onUnmounted } from 'vue';
import { debugCall } from '../utils/instrumentationClient';
import type { DebugCapabilities,DebugJob,DebugReport } from '../types/instrumentation';
const emit=defineEmits<{(event:'close'):void}>();
const operation=ref('analyze_instrumentation');const path=ref('');const mode=ref('binary');const budget=ref('{}');
const start=ref('0');const end=ref('1000000000');const gap=ref('1000000000');const elf=ref('');const build=ref('');
const capabilities=ref<DebugCapabilities|null>(null);const job=ref<DebugJob|null>(null);const report=ref<DebugReport|null>(null);const error=ref('');
let timer:ReturnType<typeof setTimeout>|undefined;let closed=false;
async function poll(){if(!job.value||closed)return;try{job.value=await debugCall<DebugJob>('get_debug_analysis_status',{job_id:job.value.job_id});if(job.value.done){report.value=await debugCall<DebugReport>('get_debug_analysis_result',{job_id:job.value.job_id});return;}}catch(e){error.value=String(e);}if(!closed)timer=setTimeout(poll,500);}
async function run(){error.value='';report.value=null;try{
  const args:Record<string,unknown>=operation.value==='analyze_instrumentation'?{file_path:path.value,mode:mode.value,budgets:JSON.parse(budget.value)}:operation.value==='analyze_power_capture'?{file_path:path.value,start_ns:start.value,end_ns:end.value,max_gap_ns:gap.value}:{directory:path.value,elf_path:elf.value||undefined,build_id:build.value||undefined};
  job.value=await debugCall<DebugJob>('start_debug_analysis',{operation:operation.value,arguments:args,timeout_ms:120000});sessionStorage.setItem('embedded_debug_job',job.value.job_id);await poll();
}catch(e){error.value=String(e);}}
async function stop(){if(job.value)try{await debugCall('stop_debug_analysis',{job_id:job.value.job_id});}catch(e){error.value=String(e);}}
function download(){if(!report.value)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report.value,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='offline-debug-analysis.json';link.click();URL.revokeObjectURL(url);}
onMounted(async()=>{try{capabilities.value=await debugCall<DebugCapabilities>('get_debug_capabilities');const previous=sessionStorage.getItem('embedded_debug_job');if(previous){job.value=await debugCall<DebugJob>('get_debug_analysis_status',{job_id:previous});await poll();}}catch(e){error.value=String(e);}});
onUnmounted(()=>{closed=true;if(timer)clearTimeout(timer);});
</script>
<template>
 <div class="absolute inset-3 z-50 bg-zinc-950 border border-zinc-600 rounded flex flex-col text-xs text-zinc-200">
  <div class="p-3 border-b border-zinc-800 flex gap-3"><strong>嵌入式离线分析</strong><span class="text-amber-300">不连接设备 · 不暂停或复位 · 不代表本轮硬件通过</span><button class="ml-auto" @click="emit('close')">关闭</button></div>
  <div class="p-4 space-y-3 overflow-auto flex-1">
   <div class="flex gap-2"><select v-model="operation" :disabled="!!job && !job.done" class="bg-zinc-900 p-2 rounded"><option value="analyze_instrumentation">HILI 插桩 / 耗时 / RTOS</option><option value="analyze_crash_bundle">崩溃证据包</option><option value="analyze_power_capture">功耗 JSONL 积分</option></select><input v-model="path" placeholder="记录文件绝对路径；崩溃分析填写证据包目录" class="bg-zinc-900 border border-zinc-700 p-2 flex-1 select-text" /></div>
   <div v-if="operation==='analyze_instrumentation'" class="space-y-2"><select v-model="mode" class="bg-zinc-900 p-1"><option value="binary">HILI 二进制</option><option value="text">@HILI1 文本封装</option></select><label class="block">预算 JSON（ID → metric: elapsed、threshold、unit、min_samples）<textarea v-model="budget" rows="4" class="block w-full bg-zinc-900 p-2 font-mono" /></label><p class="text-zinc-400">耗时来自目标 ticks；缺 BOOT、时钟、丢事件或零样本判为 INCONCLUSIVE。</p></div>
   <div v-if="operation==='analyze_power_capture'" class="flex gap-3"><label>开始 ns <input v-model="start" class="bg-zinc-900 p-1" /></label><label>结束 ns <input v-model="end" class="bg-zinc-900 p-1" /></label><label>最大间隔 ns <input v-model="gap" class="bg-zinc-900 p-1" /></label></div>
   <div v-if="operation==='analyze_crash_bundle'" class="flex gap-2"><input v-model="elf" placeholder="可选：匹配 ELF 路径" class="bg-zinc-900 p-2 flex-1" /><input v-model="build" placeholder="显式构建 ID" class="bg-zinc-900 p-2 flex-1" /></div>
   <div class="flex gap-3"><button @click="run" :disabled="!!job && !job.done" class="bg-emerald-900 px-3 py-2 rounded disabled:opacity-40">分析</button><button @click="stop" :disabled="!job || job.done" class="bg-rose-900 px-3 py-2 rounded disabled:opacity-40">取消</button><button @click="download" :disabled="!report" class="bg-zinc-800 px-3 py-2 rounded disabled:opacity-40">导出结果</button><span>{{ job?.state }}</span></div>
   <p class="text-rose-400 whitespace-pre-wrap">{{ error }}</p><p v-if="job" class="select-text text-zinc-400">{{ job.report_dir }}</p>
   <p class="text-amber-300">电源与功耗仪生产驱动未安装，实时控制不可用；数据断点未启用。</p>
   <table v-if="report?.metrics" class="w-full text-left"><thead><tr><th>范围</th><th>样本数</th><th>最大 ns</th><th>P95 ns</th><th>结论</th></tr></thead><tbody><tr v-for="m in report.metrics" :key="m.id"><td>{{ m.id }}</td><td>{{ m.sample_count }}</td><td>{{ m.max_ns ?? '未知' }}</td><td>{{ m.p95_ns ?? '未知' }}</td><td>{{ m.status }}</td></tr></tbody></table>
   <pre class="whitespace-pre-wrap break-all select-text bg-zinc-900 p-3">{{ report ? JSON.stringify(report,null,2) : capabilities ? JSON.stringify(capabilities,null,2) : '读取能力…' }}</pre>
  </div>
 </div>
</template>
