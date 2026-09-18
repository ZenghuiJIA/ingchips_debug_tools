<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';
import type { TriggerRule, CommandEnding, CommandFormat } from '../types';
import {
  Zap,
  Plus,
  Trash2,
  RotateCcw,
  Info
} from '@lucide/vue';

const emit = defineEmits<{
  (e: 'close'): void;
}>();

const STORAGE_KEY = 'ai_hil_rx_triggers_v1';

const defaultPresets: TriggerRule[] = [
  {
    id: 'trig_handshake',
    name: '开机握手应答',
    enabled: true,
    matchType: 'contains',
    matchPattern: 'READY',
    responsePayload: 'AT+START',
    responseFormat: 'string',
    responseEnding: 'crlf',
    delayMs: 100,
    mode: 'continuous',
    hits: 0
  },
  {
    id: 'trig_ping',
    name: 'PING 心跳应答',
    enabled: true,
    matchType: 'contains',
    matchPattern: 'PING',
    responsePayload: 'PONG',
    responseFormat: 'string',
    responseEnding: 'crlf',
    delayMs: 50,
    mode: 'continuous',
    hits: 0
  },
  {
    id: 'trig_auth',
    name: '控制台密码输入',
    enabled: false,
    matchType: 'contains',
    matchPattern: 'Password:',
    responsePayload: 'admin123',
    responseFormat: 'string',
    responseEnding: 'crlf',
    delayMs: 150,
    mode: 'once',
    hits: 0
  }
];

const rules = ref<TriggerRule[]>([]);
const isAddingRule = ref<boolean>(false);

const newRule = ref<Partial<TriggerRule>>({
  name: '',
  matchType: 'contains',
  matchPattern: '',
  responsePayload: '',
  responseFormat: 'string',
  responseEnding: 'crlf',
  delayMs: 50,
  mode: 'continuous',
  enabled: true
});

function loadRules() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      rules.value = JSON.parse(raw);
    } else {
      rules.value = [...defaultPresets];
      saveRules();
    }
  } catch (err) {
    console.error('Failed to load trigger rules:', err);
    rules.value = [...defaultPresets];
  }
}

function saveRules() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rules.value));
  } catch (err) {
    console.error('Failed to save trigger rules:', err);
  }
}

watch(rules, () => {
  saveRules();
}, { deep: true });

function handleCreateRule() {
  if (!newRule.value.name || !newRule.value.matchPattern || !newRule.value.responsePayload) {
    alert('请填写完整的触发器名称、匹配规则和应答内容');
    return;
  }

  const created: TriggerRule = {
    id: `trig_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    name: newRule.value.name,
    enabled: newRule.value.enabled ?? true,
    matchType: newRule.value.matchType || 'contains',
    matchPattern: newRule.value.matchPattern,
    responsePayload: newRule.value.responsePayload,
    responseFormat: (newRule.value.responseFormat as CommandFormat) || 'string',
    responseEnding: (newRule.value.responseEnding as CommandEnding) || 'crlf',
    delayMs: Number(newRule.value.delayMs) || 0,
    mode: newRule.value.mode || 'continuous',
    hits: 0
  };

  rules.value.push(created);
  isAddingRule.value = false;

  // Reset form
  newRule.value = {
    name: '',
    matchType: 'contains',
    matchPattern: '',
    responsePayload: '',
    responseFormat: 'string',
    responseEnding: 'crlf',
    delayMs: 50,
    mode: 'continuous',
    enabled: true
  };
}

function deleteRule(id: string) {
  rules.value = rules.value.filter(r => r.id !== id);
}

function resetHits() {
  rules.value.forEach(r => r.hits = 0);
}

function restorePresets() {
  if (confirm('确认恢复默认触发器预设？这会覆盖当前自定义规则')) {
    rules.value = [...defaultPresets];
  }
}

// Expose public method for SerialTerminal to evaluate triggers on incoming text
function checkAndMatchTriggers(rxText: string): TriggerRule[] {
  const matchedRules: TriggerRule[] = [];

  for (const rule of rules.value) {
    if (!rule.enabled) continue;

    let matched = false;
    if (rule.matchType === 'contains') {
      matched = rxText.includes(rule.matchPattern);
    } else if (rule.matchType === 'regex') {
      try {
        const re = new RegExp(rule.matchPattern);
        matched = re.test(rxText);
      } catch {
        matched = false;
      }
    }

    if (matched) {
      rule.hits++;
      rule.lastTriggerTime = new Date().toTimeString().split(' ')[0];
      if (rule.mode === 'once') {
        rule.enabled = false;
      }
      matchedRules.push(rule);
    }
  }

  return matchedRules;
}

defineExpose({
  checkAndMatchTriggers,
  rules
});

onMounted(() => {
  loadRules();
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-900 border-l border-zinc-800 w-96 text-xs text-zinc-100 shadow-2xl">
    <!-- Header -->
    <div class="bg-zinc-950 border-b border-zinc-800 p-3 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <Zap class="w-4 h-4 text-amber-400" />
        <span class="font-bold text-zinc-200">智能触发器 / 自动应答机</span>
      </div>

      <div class="flex items-center gap-1">
        <button
          @click="restorePresets"
          class="p-1 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 rounded"
          title="恢复预设规则"
        >
          <RotateCcw class="w-3.5 h-3.5" />
        </button>
        <button
          @click="emit('close')"
          class="p-1 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 rounded"
          title="关闭抽屉"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Description Banner -->
    <div class="bg-amber-950/30 border-b border-amber-900/50 px-3 py-2 text-[11px] text-amber-300/90 flex items-start gap-2">
      <Info class="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400" />
      <div>
        当串口接收到匹配内容时，自动在指定延时后回复设定命令。可用于<strong>自动化握手、密码应答与异常拦截</strong>。
      </div>
    </div>

    <!-- Toolbar -->
    <div class="px-3 py-2 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between">
      <div class="text-[11px] text-zinc-400">
        激活规则: <strong class="text-emerald-400">{{ rules.filter(r => r.enabled).length }}</strong> / {{ rules.length }}
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="resetHits"
          class="text-[10px] text-zinc-400 hover:text-zinc-200 underline"
        >
          清零计数
        </button>
        <button
          @click="isAddingRule = !isAddingRule"
          class="px-2 py-0.5 bg-amber-600 hover:bg-amber-500 text-zinc-950 font-bold rounded text-[11px] flex items-center gap-1"
        >
          <Plus class="w-3 h-3" />
          <span>添加规则</span>
        </button>
      </div>
    </div>

    <!-- Add Rule Form Dialog (Inline) -->
    <div v-if="isAddingRule" class="bg-zinc-950 p-3 border-b border-zinc-700 space-y-2.5">
      <div class="text-xs font-bold text-amber-400">新建触发应答规则</div>

      <div>
        <label class="text-[10px] text-zinc-400 block mb-0.5">规则名称</label>
        <input
          v-model="newRule.name"
          placeholder="如: AT握手测试"
          class="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-zinc-200 focus:outline-none focus:border-amber-500"
        />
      </div>

      <div class="grid grid-cols-3 gap-2">
        <div class="col-span-1">
          <label class="text-[10px] text-zinc-400 block mb-0.5">匹配方式</label>
          <select
            v-model="newRule.matchType"
            class="w-full bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-200 focus:outline-none text-xs"
          >
            <option value="contains">包含</option>
            <option value="regex">正则</option>
          </select>
        </div>
        <div class="col-span-2">
          <label class="text-[10px] text-zinc-400 block mb-0.5">匹配文本 / 正则</label>
          <input
            v-model="newRule.matchPattern"
            placeholder="如: READY 或 Error:0x"
            class="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-zinc-200 focus:outline-none font-mono"
          />
        </div>
      </div>

      <div>
        <label class="text-[10px] text-zinc-400 block mb-0.5">自动回复内容</label>
        <input
          v-model="newRule.responsePayload"
          placeholder="如: AT+START"
          class="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-zinc-200 focus:outline-none font-mono"
        />
      </div>

      <div class="grid grid-cols-3 gap-2">
        <div>
          <label class="text-[10px] text-zinc-400 block mb-0.5">换行格式</label>
          <select
            v-model="newRule.responseEnding"
            class="w-full bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-200 focus:outline-none text-xs"
          >
            <option value="crlf">+CRLF</option>
            <option value="lf">+LF</option>
            <option value="cr">+CR</option>
            <option value="none">无换行</option>
          </select>
        </div>
        <div>
          <label class="text-[10px] text-zinc-400 block mb-0.5">应答延时(ms)</label>
          <input
            type="number"
            v-model="newRule.delayMs"
            step="10"
            min="0"
            class="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-zinc-200 focus:outline-none"
          />
        </div>
        <div>
          <label class="text-[10px] text-zinc-400 block mb-0.5">触发模式</label>
          <select
            v-model="newRule.mode"
            class="w-full bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-200 focus:outline-none text-xs"
          >
            <option value="continuous">每次触发</option>
            <option value="once">仅单次</option>
          </select>
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button
          @click="isAddingRule = false"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs"
        >
          取消
        </button>
        <button
          @click="handleCreateRule"
          class="px-3 py-1 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold rounded text-xs"
        >
          保存规则
        </button>
      </div>
    </div>

    <!-- Rules List -->
    <div class="flex-1 overflow-y-auto p-3 space-y-2.5">
      <div v-if="rules.length === 0" class="text-center py-8 text-zinc-500 text-xs">
        暂无触发规则，点击上方添加
      </div>

      <div
        v-for="rule in rules"
        :key="rule.id"
        class="bg-zinc-950 border rounded-lg p-2.5 transition-all space-y-1.5"
        :class="rule.enabled ? 'border-zinc-700' : 'border-zinc-800 opacity-60'"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input
              type="checkbox"
              v-model="rule.enabled"
              class="rounded bg-zinc-800 border-zinc-700 text-amber-500 focus:ring-0 cursor-pointer"
            />
            <span class="font-bold text-zinc-200">{{ rule.name }}</span>
            <span
              class="px-1.5 py-0.2 rounded text-[10px]"
              :class="rule.mode === 'once' ? 'bg-purple-950 text-purple-300 border border-purple-800' : 'bg-zinc-800 text-zinc-400'"
            >
              {{ rule.mode === 'once' ? '单次' : '持续' }}
            </span>
          </div>

          <button
            @click="deleteRule(rule.id)"
            class="text-zinc-500 hover:text-rose-400 p-1 rounded hover:bg-zinc-900"
            title="删除规则"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- Pattern Condition -->
        <div class="text-[11px] font-mono text-zinc-400 flex items-center gap-1 bg-zinc-900 px-2 py-1 rounded">
          <span class="text-zinc-500">条件:</span>
          <span class="text-amber-400">[{{ rule.matchType === 'regex' ? '正则' : '包含' }}]</span>
          <code class="text-zinc-200">"{{ rule.matchPattern }}"</code>
        </div>

        <!-- Response Action -->
        <div class="text-[11px] font-mono text-zinc-400 flex items-center justify-between bg-zinc-900 px-2 py-1 rounded">
          <div class="flex items-center gap-1 overflow-hidden truncate">
            <span class="text-zinc-500">应答:</span>
            <code class="text-emerald-400 truncate">"{{ rule.responsePayload }}"</code>
            <span class="text-[10px] text-zinc-500">+{{ rule.responseEnding.toUpperCase() }}</span>
          </div>
          <span class="text-[10px] text-zinc-500 shrink-0">⏳ {{ rule.delayMs }}ms</span>
        </div>

        <!-- Stats Footer -->
        <div class="flex items-center justify-between text-[10px] text-zinc-500 pt-0.5">
          <span>已触发: <strong class="text-amber-400">{{ rule.hits }}</strong> 次</span>
          <span v-if="rule.lastTriggerTime">最近: {{ rule.lastTriggerTime }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
