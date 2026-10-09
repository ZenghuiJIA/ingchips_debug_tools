<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue';
import type { CommandGroup, CommandItem } from '../types';
import {
  loadCommandGroups,
  saveCommandGroups,
  encodeCommand,
} from '../utils/commandEncoder';
import { safeInvoke } from '../utils/ipc';
import {
  Play,
  Square,
  Plus,
  Trash2,
  Edit2,
  Download,
  Upload,
  Send,
  Check,
  X,
  Clock,
  Layers,
  Repeat,
  Sparkles
} from 'lucide-vue-next';
import { t } from '../utils/i18n';

const props = defineProps<{
  isConnected: boolean;
  portName?: string;
}>();

const emit = defineEmits<{
  (e: 'log', text: string, type: 'tx' | 'error' | 'info'): void;
  (e: 'bytesSent', count: number): void;
  (e: 'groupChanged', currentGroup: CommandGroup): void;
}>();

// Groups state
const groups = ref<CommandGroup[]>(loadCommandGroups());
const activeGroupId = ref<string>(groups.value[0]?.id || '');

const activeGroup = computed<CommandGroup | undefined>(() => {
  return groups.value.find(g => g.id === activeGroupId.value);
});

// Watch and sync to localStorage
watch(
  groups,
  (newVal) => {
    saveCommandGroups(newVal);
    if (activeGroup.value) {
      emit('groupChanged', activeGroup.value);
    }
  },
  { deep: true }
);

// Batch Execution State Machine
const isBatchRunning = ref(false);
const currentRunningIndex = ref<number>(-1);
const abortController = ref<boolean>(false);
const loopCounter = ref<number>(0);

/**
 * Send a single command immediately (满足：支持一个命令的单独发送)
 */
async function sendSingleCommand(cmd: CommandItem) {
  if (!props.isConnected) {
    emit('log', t('cmd_send_err_no_conn', { label: cmd.label }), 'error');
    return;
  }

  try {
    const { bytes, textDisplay } = encodeCommand(cmd);
    const count: number = await safeInvoke('send_serial_data', { 
      data: bytes,
      portName: props.portName
    });
    emit('bytesSent', count);
    emit('log', `[TX] ${textDisplay}`, 'tx');
  } catch (err: any) {
    emit('log', t('cmd_send_err', { label: cmd.label, err: err.message || err }), 'error');
  }
}

/**
 * Execute all enabled commands in the group sequentially with delay
 */
async function startBatchExecution() {
  if (!activeGroup.value || !props.isConnected) return;
  const enabledCmds = activeGroup.value.commands.filter(c => c.enabled);
  if (enabledCmds.length === 0) {
    emit('log', t('cmd_no_checked'), 'info');
    return;
  }

  isBatchRunning.value = true;
  abortController.value = false;
  loopCounter.value = 0;

  emit('log', t('cmd_run_start', { name: activeGroup.value.name, count: enabledCmds.length }), 'info');

  do {
    loopCounter.value++;
    for (let i = 0; i < activeGroup.value.commands.length; i++) {
      if (abortController.value) break;

      const cmd = activeGroup.value.commands[i];
      if (!cmd.enabled) continue;

      currentRunningIndex.value = i;

      // Send current command
      await sendSingleCommand(cmd);

      // Wait delayAfterMs before next command
      if (cmd.delayAfterMs > 0 && !abortController.value) {
        await new Promise(resolve => setTimeout(resolve, cmd.delayAfterMs));
      }
    }

    if (activeGroup.value.loop && !abortController.value) {
      const waitMs = activeGroup.value.loopIntervalMs || 1000;
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
  } while (activeGroup.value.loop && !abortController.value);

  isBatchRunning.value = false;
  currentRunningIndex.value = -1;
  abortController.value = false;
  emit('log', t('cmd_run_finish'), 'info');
}

function stopBatchExecution() {
  abortController.value = true;
  isBatchRunning.value = false;
  currentRunningIndex.value = -1;
  emit('log', t('cmd_run_user_stop'), 'info');
}

onUnmounted(() => {
  stopBatchExecution();
});

// Modals / Editors state
const isEditModalOpen = ref(false);
const editingCommand = ref<CommandItem | null>(null);
const isNewCommand = ref(false);

function openAddCommandModal() {
  editingCommand.value = {
    id: 'cmd_' + Date.now(),
    label: t('cmd_new_item_label'),
    payload: 'AT',
    format: 'string',
    lineEnding: 'crlf',
    delayAfterMs: 150,
    enabled: true,
  };
  isNewCommand.value = true;
  isEditModalOpen.value = true;
}

function openEditCommandModal(cmd: CommandItem) {
  editingCommand.value = JSON.parse(JSON.stringify(cmd));
  isNewCommand.value = false;
  isEditModalOpen.value = true;
}

function saveEditingCommand() {
  if (!editingCommand.value || !activeGroup.value) return;

  if (isNewCommand.value) {
    activeGroup.value.commands.push(editingCommand.value);
  } else {
    const idx = activeGroup.value.commands.findIndex(c => c.id === editingCommand.value!.id);
    if (idx !== -1) {
      activeGroup.value.commands[idx] = editingCommand.value;
    }
  }

  isEditModalOpen.value = false;
  editingCommand.value = null;
}

function deleteCommand(id: string) {
  if (!activeGroup.value) return;
  activeGroup.value.commands = activeGroup.value.commands.filter(c => c.id !== id);
}

// Group Operations (Create / Delete / Import / Export)
function createNewGroup() {
  const newId = 'grp_' + Date.now();
  const newGroup: CommandGroup = {
    id: newId,
    name: t('cmd_new_group_name', { index: groups.value.length + 1 }),
    commands: [],
    loop: false,
    loopIntervalMs: 1000,
  };
  groups.value.push(newGroup);
  activeGroupId.value = newId;
}

function deleteCurrentGroup() {
  if (groups.value.length <= 1) {
    alert(t('cmd_keep_one_group'));
    return;
  }
  if (confirm(t('cmd_confirm_delete_group', { name: activeGroup.value?.name || '' }))) {
    groups.value = groups.value.filter(g => g.id !== activeGroupId.value);
    activeGroupId.value = groups.value[0]?.id || '';
  }
}

function exportGroupsJson() {
  const jsonStr = JSON.stringify(groups.value, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `command_groups_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function importGroupsJson() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';
  input.onchange = (e: any) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const parsed = JSON.parse(evt.target?.result as string);
        if (Array.isArray(parsed) && parsed.length > 0) {
          groups.value = parsed;
          activeGroupId.value = parsed[0].id;
          emit('log', t('cmd_import_success', { count: parsed.length }), 'info');
        } else {
          alert(t('cmd_import_invalid_format'));
        }
      } catch (err: any) {
        alert(t('cmd_import_parse_err', { err: err.message }));
      }
    };
    reader.readAsText(file);
  };
  input.click();
}

// Expose single send method for parent components (like bottom quick bar)
defineExpose({
  sendSingleCommand,
  activeGroup,
  groups,
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-900 border-l border-zinc-800 text-xs select-none">
    <!-- Header: Group Selector & Actions -->
    <div class="p-3 border-b border-zinc-800 flex flex-col gap-2 bg-zinc-950/60">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-1.5 font-bold text-zinc-200">
          <Layers class="w-4 h-4 text-emerald-400" />
          <span>{{ t('cmd_title') }}</span>
        </div>
        <div class="flex items-center gap-1">
          <button
            @click="createNewGroup"
            :title="t('cmd_btn_new_group')"
            class="p-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white transition-colors"
          >
            <Plus class="w-3.5 h-3.5" />
          </button>
          <button
            @click="exportGroupsJson"
            :title="t('cmd_btn_export_json')"
            class="p-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white transition-colors"
          >
            <Download class="w-3.5 h-3.5" />
          </button>
          <button
            @click="importGroupsJson"
            :title="t('cmd_btn_import_json')"
            class="p-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white transition-colors"
          >
            <Upload class="w-3.5 h-3.5" />
          </button>
          <button
            @click="deleteCurrentGroup"
            :title="t('cmd_btn_delete_group')"
            class="p-1 rounded bg-zinc-800 hover:bg-rose-900/60 text-zinc-400 hover:text-rose-300 transition-colors"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <!-- Select active group -->
      <div class="flex items-center gap-2">
        <select
          v-model="activeGroupId"
          class="flex-1 bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1.5 text-xs text-zinc-100 outline-none focus:border-emerald-500"
        >
          <option v-for="g in groups" :key="g.id" :value="g.id">
            {{ g.name }} ({{ g.commands.length }})
          </option>
        </select>
      </div>

      <!-- Group Name In-place Edit -->
      <div v-if="activeGroup" class="flex items-center gap-2">
        <input
          v-model="activeGroup.name"
          type="text"
          :placeholder="t('cmd_group_name_placeholder')"
          class="flex-1 bg-zinc-900 border border-zinc-800 focus:border-zinc-700 rounded px-2 py-1 text-[11px] text-zinc-300 outline-none"
        />
      </div>

      <!-- Batch Runner Toolbar -->
      <div class="pt-2 border-t border-zinc-800/80 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <!-- Sequential Execution Button -->
          <button
            v-if="!isBatchRunning"
            @click="startBatchExecution"
            :disabled="!isConnected || !activeGroup || activeGroup.commands.length === 0"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition-colors shadow-sm disabled:opacity-40 disabled:hover:bg-emerald-600"
          >
            <Play class="w-3.5 h-3.5 fill-current" />
            <span>{{ t('cmd_seq_run') }}</span>
          </button>
          <button
            v-else
            @click="stopBatchExecution"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs transition-colors shadow-sm animate-pulse"
          >
            <Square class="w-3.5 h-3.5 fill-current" />
            <span>{{ t('cmd_stop_run') }} (#{{ loopCounter }})</span>
          </button>

          <!-- Loop toggle -->
          <label v-if="activeGroup" class="flex items-center gap-1 text-[11px] text-zinc-400 cursor-pointer select-none">
            <input
              type="checkbox"
              v-model="activeGroup.loop"
              class="accent-emerald-500 rounded cursor-pointer"
            />
            <span class="flex items-center gap-0.5">
              <Repeat class="w-3 h-3" />
              <span>{{ t('cmd_loop') }}</span>
            </span>
          </label>
        </div>

        <!-- Add Command Button -->
        <button
          @click="openAddCommandModal"
          class="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors"
        >
          <Plus class="w-3 h-3" />
          <span>{{ t('cmd_add') }}</span>
        </button>
      </div>
    </div>

    <!-- Command List -->
    <div class="flex-1 overflow-y-auto p-2 space-y-1.5">
      <div
        v-if="!activeGroup || activeGroup.commands.length === 0"
        class="h-48 flex flex-col items-center justify-center text-zinc-500 text-center gap-2"
      >
        <Sparkles class="w-8 h-8 text-zinc-700" />
        <span>{{ t('cmd_empty') }}</span>
        <button
          @click="openAddCommandModal"
          class="px-3 py-1 rounded bg-emerald-950/80 border border-emerald-800 text-emerald-400 hover:bg-emerald-900 transition-colors text-xs"
        >
          {{ t('cmd_empty_add') }}
        </button>
      </div>

      <div
        v-for="(cmd, idx) in activeGroup?.commands"
        :key="cmd.id"
        class="group p-2 rounded border transition-all duration-150 relative flex flex-col gap-1"
        :class="[
          currentRunningIndex === idx && isBatchRunning
            ? 'bg-emerald-950/50 border-emerald-500/80 shadow-[0_0_12px_rgba(16,185,129,0.2)]'
            : 'bg-zinc-950/80 border-zinc-800/80 hover:border-zinc-700'
        ]"
      >
        <!-- Top row: Checkbox, Index, Label, and Action Buttons -->
        <div class="flex items-center justify-between gap-1.5">
          <div class="flex items-center gap-2 overflow-hidden">
            <!-- Include in Batch Checkbox -->
            <input
              type="checkbox"
              v-model="cmd.enabled"
              :title="t('cmd_include_in_batch')"
              class="accent-emerald-500 rounded cursor-pointer shrink-0"
            />
            <span class="text-[10px] font-mono text-zinc-500 shrink-0">#{{ idx + 1 }}</span>
            <span class="font-semibold text-zinc-200 truncate" :title="cmd.label">{{ cmd.label }}</span>
          </div>

          <!-- Actions on the right -->
          <div class="flex items-center gap-1 shrink-0">
            <!-- ⭐ 单独发送按钮 (核心满足用户要求) ⭐ -->
            <button
              @click="sendSingleCommand(cmd)"
              :disabled="!isConnected || isBatchRunning"
              :title="t('cmd_single_send')"
              class="flex items-center gap-1 px-2 py-0.5 rounded bg-sky-950/80 hover:bg-sky-900 border border-sky-800/60 text-sky-300 font-medium text-[11px] transition-colors disabled:opacity-30"
            >
              <Send class="w-2.5 h-2.5" />
              <span>{{ t('cmd_single_send') }}</span>
            </button>

            <!-- Edit Button -->
            <button
              @click="openEditCommandModal(cmd)"
              :title="t('cmd_edit_instruction')"
              class="p-1 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
            >
              <Edit2 class="w-3 h-3" />
            </button>

            <!-- Delete Button -->
            <button
              @click="deleteCommand(cmd.id)"
              :title="t('cmd_delete_instruction')"
              class="p-1 rounded text-zinc-500 hover:text-rose-400 hover:bg-zinc-800 transition-colors"
            >
              <Trash2 class="w-3 h-3" />
            </button>
          </div>
        </div>

        <!-- Middle row: Payload code snippet -->
        <div class="font-mono text-[11.5px] text-zinc-300 bg-zinc-900/90 rounded px-2 py-1 break-all select-text border border-zinc-800/50">
          {{ cmd.payload }}
        </div>

        <!-- Bottom row: Badges for Format, Ending, and Delay -->
        <div class="flex items-center justify-between text-[10px] pt-0.5">
          <div class="flex items-center gap-1.5">
            <!-- Format Badge -->
            <span
              v-if="cmd.format === 'hex'"
              class="px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800/60 font-mono font-bold"
            >
              HEX
            </span>
            <span
              v-else
              class="px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400 font-mono"
            >
              TXT
            </span>

            <!-- Line Ending Badge (核心看清带不带 \r\n) -->
            <span
              v-if="cmd.format === 'string'"
              class="px-1.5 py-0.2 rounded font-mono font-bold"
              :class="{
                'bg-cyan-950 text-cyan-300 border border-cyan-800/60': cmd.lineEnding === 'crlf',
                'bg-blue-950 text-blue-300 border border-blue-800/60': cmd.lineEnding === 'lf',
                'bg-teal-950 text-teal-300 border border-teal-800/60': cmd.lineEnding === 'cr',
                'bg-amber-950 text-amber-300 border border-amber-800/60': cmd.lineEnding === 'none',
              }"
            >
              {{
                cmd.lineEnding === 'crlf'
                  ? '+CRLF (\\r\\n)'
                  : cmd.lineEnding === 'lf'
                  ? '+LF (\\n)'
                  : cmd.lineEnding === 'cr'
                  ? '+CR (\\r)'
                  : t('cmd_line_ending_raw')
              }}
            </span>
          </div>

          <!-- Delay tag -->
          <div class="flex items-center gap-1 text-zinc-500 font-mono">
            <Clock class="w-3 h-3" />
            <span>{{ cmd.delayAfterMs }}ms</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Edit / Add Command Modal -->
    <div
      v-if="isEditModalOpen && editingCommand"
      class="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 z-50"
    >
      <div class="bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl w-full max-w-sm p-4 flex flex-col gap-3 text-xs">
        <div class="flex items-center justify-between border-b border-zinc-800 pb-2">
          <span class="font-bold text-zinc-100 text-sm">
            {{ isNewCommand ? t('cmd_dialog_add') : t('cmd_dialog_edit') }}
          </span>
          <button @click="isEditModalOpen = false" class="text-zinc-400 hover:text-white">
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Label -->
        <div>
          <label class="block text-zinc-400 text-[11px] mb-1">{{ t("cmd_field_label") }}</label>
          <input
            v-model="editingCommand.label"
            type="text"
            :placeholder="t('cmd_field_label_placeholder')"
            class="w-full bg-zinc-950 border border-zinc-700 rounded px-2.5 py-1.5 text-zinc-100 outline-none focus:border-emerald-500"
          />
        </div>

        <!-- Format & Line Ending -->
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label class="block text-zinc-400 text-[11px] mb-1">{{ t("cmd_field_format") }}</label>
            <select
              v-model="editingCommand.format"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-zinc-100 outline-none"
            >
              <option value="string">{{ t("cmd_fmt_string") }}</option>
              <option value="hex">{{ t("cmd_fmt_hex") }}</option>
            </select>
          </div>

          <div>
            <label class="block text-zinc-400 text-[11px] mb-1">{{ t("cmd_field_line_ending") }}</label>
            <select
              v-model="editingCommand.lineEnding"
              :disabled="editingCommand.format === 'hex'"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-zinc-100 outline-none disabled:opacity-40"
            >
              <option value="crlf">{{ t("cmd_line_ending_crlf_at") }}</option>
              <option value="lf">+LF (\n) [Shell]</option>
              <option value="cr">+CR (\r)</option>
              <option value="none">{{ t("cmd_line_ending_none_raw") }}</option>
            </select>
          </div>
        </div>

        <!-- Payload -->
        <div>
          <label class="block text-zinc-400 text-[11px] mb-1">
            {{ t("cmd_field_payload") }}
            <span class="text-zinc-500 font-normal">
              {{ editingCommand.format === 'hex' ? t('cmd_field_payload_tip_hex') : t('cmd_field_payload_tip_str') }}
            </span>
          </label>
          <textarea
            v-model="editingCommand.payload"
            rows="3"
            :placeholder="t('cmd_payload_placeholder')"
            class="w-full bg-zinc-950 border border-zinc-700 rounded px-2.5 py-1.5 text-zinc-100 font-mono outline-none focus:border-emerald-500"
          ></textarea>
        </div>

        <!-- Delay -->
        <div>
          <label class="block text-zinc-400 text-[11px] mb-1">{{ t("cmd_field_delay") }}</label>
          <input
            v-model.number="editingCommand.delayAfterMs"
            type="number"
            min="0"
            step="50"
            class="w-full bg-zinc-950 border border-zinc-700 rounded px-2.5 py-1.5 text-zinc-100 font-mono outline-none"
          />
        </div>

        <!-- Modal Footer -->
        <div class="flex items-center justify-end gap-2 pt-2 border-t border-zinc-800">
          <button
            @click="isEditModalOpen = false"
            class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
          >
            {{ t("cmd_btn_cancel") }}
          </button>
          <button
            @click="saveEditingCommand"
            :disabled="!editingCommand.payload"
            class="flex items-center gap-1 px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors disabled:opacity-40"
          >
            <Check class="w-3.5 h-3.5" />
            <span>{{ t("cmd_btn_save") }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
