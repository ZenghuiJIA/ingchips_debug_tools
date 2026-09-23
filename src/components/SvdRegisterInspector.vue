<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { SvdDevice, SvdPeripheral, SvdRegister, SvdField, ProbeInfo } from '../types';
import {
  RefreshCw,
  Search,
  Zap,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Edit3,
  Sliders,
  Database,
  FolderPlus
} from 'lucide-vue-next';

// State
const devices = ref<SvdDevice[]>([]);
const selectedDeviceName = ref<string>('');
const peripherals = ref<SvdPeripheral[]>([]);
const selectedPeripheral = ref<SvdPeripheral | null>(null);
const registers = ref<SvdRegister[]>([]);

const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');

const isLoadingDevices = ref<boolean>(false);
const isLoadingPeripherals = ref<boolean>(false);
const isLoadingRegisters = ref<boolean>(false);
const isBatchReading = ref<boolean>(false);

const peripheralFilter = ref<string>('');
const registerFilter = ref<string>('');

const statusMessage = ref<{ text: string; type: 'info' | 'success' | 'error' } | null>(null);

// Editing Modal State for Register
const editingRegister = ref<SvdRegister | null>(null);
const editRegValueHex = ref<string>('');
const isSubmittingReg = ref<boolean>(false);

// Editing Field State
const editingField = ref<{ reg: SvdRegister; field: SvdField } | null>(null);
const editFieldValue = ref<string>('');
const isSubmittingField = ref<boolean>(false);

function setStatus(text: string, type: 'info' | 'success' | 'error' = 'info') {
  statusMessage.value = { text, type };
  if (type === 'success') {
    setTimeout(() => {
      if (statusMessage.value?.text === text) {
        statusMessage.value = null;
      }
    }, 4000);
  }
}

// Current device details
const currentDevice = computed(() => {
  return devices.value.find(d => d.name === selectedDeviceName.value) || null;
});

// Filtered peripherals
const filteredPeripherals = computed(() => {
  const query = peripheralFilter.value.trim().toLowerCase();
  if (!query) return peripherals.value;
  return peripherals.value.filter(p =>
    p.name.toLowerCase().includes(query) ||
    p.description.toLowerCase().includes(query) ||
    p.group_name.toLowerCase().includes(query) ||
    p.base_address.toLowerCase().includes(query)
  );
});

// Filtered registers
const filteredRegisters = computed(() => {
  const query = registerFilter.value.trim().toLowerCase();
  if (!query) return registers.value;
  return registers.value.filter(r =>
    r.name.toLowerCase().includes(query) ||
    r.description.toLowerCase().includes(query) ||
    r.offset.toLowerCase().includes(query) ||
    r.address.toLowerCase().includes(query)
  );
});

// Load Probes
async function loadProbes() {
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    probes.value = list;
    if (list.length > 0 && !selectedProbeId.value) {
      selectedProbeId.value = list[0].unique_id;
    }
  } catch (err) {
    console.warn('Failed to load probes:', err);
  }
}

// Import CMSIS-Pack state
const isImportingPack = ref<boolean>(false);

// Load SVD Devices
async function loadDevices() {
  isLoadingDevices.value = true;
  try {
    const devs: SvdDevice[] = await safeInvoke('svd_get_devices');
    devices.value = devs;
    if (devs.length > 0) {
      if (!selectedDeviceName.value || !devs.some(d => d.name === selectedDeviceName.value)) {
        const defaultDev = devs.find(d => d.name.toUpperCase().includes('918')) || devs[0];
        selectedDeviceName.value = defaultDev.name;
      }
    } else {
      setStatus('未在 pack 库中发现芯片 SVD 定义文件', 'error');
    }
  } catch (err: any) {
    setStatus(`加载 SVD 芯片列表失败: ${err}`, 'error');
  } finally {
    isLoadingDevices.value = false;
  }
}

// Dynamically import CMSIS-Pack
async function handleImportPack() {
  try {
    const selectedPath = await safeInvoke<string | null>('pick_pack_file', {
      title: '选择 CMSIS-Pack 芯片描述包 (*.pack)'
    });
    if (!selectedPath) return;

    isImportingPack.value = true;
    setStatus(`正在解析并导入 Pack: ${selectedPath}...`, 'info');

    const result: any = await safeInvoke('svd_import_pack', {
      packPath: selectedPath
    });

    if (result && result.devices && result.devices.length > 0) {
      setStatus(`成功导入 ${result.pack}，新增 ${result.devices.length} 款芯片型号！`, 'success');
      const firstDev = result.devices[0].name;
      if (firstDev) {
        selectedDeviceName.value = firstDev;
      }
      await loadDevices();
    } else {
      setStatus(`Pack 导入完成，已刷新设备列表`, 'info');
      await loadDevices();
    }
  } catch (err: any) {
    setStatus(`导入 Pack 文件失败: ${err}`, 'error');
  } finally {
    isImportingPack.value = false;
  }
}

// Load Peripherals for selected device
async function loadPeripherals(deviceName: string) {
  if (!deviceName) return;
  isLoadingPeripherals.value = true;
  peripherals.value = [];
  selectedPeripheral.value = null;
  registers.value = [];

  try {
    const periphs: SvdPeripheral[] = await safeInvoke('svd_get_peripherals', { deviceName });
    peripherals.value = periphs;
    if (periphs.length > 0) {
      selectPeripheral(periphs[0]);
    }
  } catch (err: any) {
    setStatus(`加载外设列表失败: ${err}`, 'error');
  } finally {
    isLoadingPeripherals.value = false;
  }
}

// Select a peripheral & load its registers
async function selectPeripheral(p: SvdPeripheral) {
  selectedPeripheral.value = p;
  isLoadingRegisters.value = true;
  registers.value = [];

  try {
    const regs: SvdRegister[] = await safeInvoke('svd_get_registers', {
      deviceName: selectedDeviceName.value,
      peripheralName: p.name
    });
    registers.value = regs.map(r => ({
      ...r,
      is_expanded: false,
      is_reading: false,
      is_writing: false
    }));
  } catch (err: any) {
    setStatus(`加载 ${p.name} 寄存器定义失败: ${err}`, 'error');
  } finally {
    isLoadingRegisters.value = false;
  }
}

// Toggle register bitfield expand
function toggleExpandRegister(reg: SvdRegister) {
  reg.is_expanded = !reg.is_expanded;
}

// Helper to update field values from parent register value
function updateFieldsFromRegValue(reg: SvdRegister) {
  if (reg.current_value_uint === undefined || !reg.fields) return;
  const regVal = reg.current_value_uint >>> 0;
  reg.fields.forEach(f => {
    const mask = f.bit_width >= 32 ? 0xFFFFFFFF : (((1 << f.bit_width) - 1) >>> 0);
    const fval = (regVal >>> f.bit_offset) & mask;
    f.value = fval;
    f.hex_value = `0x${fval.toString(16).toUpperCase()}`;
    f.bin_value = fval.toString(2).padStart(f.bit_width, '0');
  });
}

// Single Register Read
async function readRegister(reg: SvdRegister) {
  reg.is_reading = true;
  try {
    const res: any = await safeInvoke('svd_read_register', {
      address: reg.address,
      probeId: selectedProbeId.value || null,
      targetOverride: selectedDeviceName.value || null
    });

    reg.current_value = res.value || res.current_value;
    reg.current_value_uint = res.value_uint !== undefined ? (res.value_uint >>> 0) : (res.value ? (parseInt(res.value, 16) >>> 0) : 0);
    reg.current_binary = res.binary || (reg.current_value_uint >>> 0).toString(2).padStart(32, '0');
    reg.last_updated = new Date().toLocaleTimeString();

    updateFieldsFromRegValue(reg);

    setStatus(`已读取 ${selectedPeripheral.value?.name}->${reg.name} = ${reg.current_value}`, 'success');
  } catch (err: any) {
    setStatus(`读取 ${reg.name} 失败: ${err}`, 'error');
  } finally {
    reg.is_reading = false;
  }
}

// Read All Registers for active peripheral
async function readAllRegisters() {
  if (!selectedPeripheral.value) return;
  isBatchReading.value = true;
  setStatus(`正在批量读取 ${selectedPeripheral.value.name} 外设所有寄存器...`, 'info');

  try {
    const addrs = registers.value.map(r => r.address);
    const res: any = await safeInvoke('svd_read_all_registers', {
      addresses: addrs,
      probeId: selectedProbeId.value || null,
      targetOverride: selectedDeviceName.value || null
    });

    if (res && res.results) {
      let count = 0;
      registers.value.forEach(r => {
        const item = res.results[r.address] || res.results[r.address.toLowerCase()] || res.results[r.address.toUpperCase()];
        if (item && !item.error) {
          r.current_value = item.value;
          r.current_value_uint = item.value_uint !== undefined ? (item.value_uint >>> 0) : (parseInt(item.value, 16) >>> 0);
          r.current_binary = item.binary || (r.current_value_uint >>> 0).toString(2).padStart(32, '0');
          r.last_updated = new Date().toLocaleTimeString();
          updateFieldsFromRegValue(r);
          count++;
        }
      });
      setStatus(`成功批量读取 ${selectedPeripheral.value.name} 的 ${count} 个寄存器`, 'success');
    } else {
      setStatus(`批量读取完成`, 'success');
    }
  } catch (err: any) {
    setStatus(`批量读取失败: ${err}`, 'error');
  } finally {
    isBatchReading.value = false;
  }
}

// Open Edit Register Dialog
function openWriteRegisterModal(reg: SvdRegister) {
  editingRegister.value = reg;
  editRegValueHex.value = reg.current_value || reg.reset_value || '0x00000000';
}

// Confirm Write Register
async function confirmWriteRegister() {
  if (!editingRegister.value || !selectedPeripheral.value) return;
  isSubmittingReg.value = true;

  let val = 0;
  try {
    const raw = editRegValueHex.value.trim();
    if (raw.toLowerCase().startsWith('0x')) {
      val = parseInt(raw, 16);
    } else {
      val = parseInt(raw, 10);
    }
    if (isNaN(val)) throw new Error('无效的数值格式 (支持 0x12AB 或 十进制)');
  } catch (e: any) {
    setStatus(e.message, 'error');
    isSubmittingReg.value = false;
    return;
  }

  try {
    const reg = editingRegister.value;
    const res: any = await safeInvoke('svd_write_register', {
      address: reg.address,
      value: val >>> 0,
      probeId: selectedProbeId.value || null,
      targetOverride: selectedDeviceName.value || null
    });

    const valUint = val >>> 0;
    reg.current_value = res.value || `0x${valUint.toString(16).padStart(8, '0').toUpperCase()}`;
    reg.current_value_uint = valUint;
    reg.current_binary = valUint.toString(2).padStart(32, '0');
    reg.last_updated = new Date().toLocaleTimeString();
    updateFieldsFromRegValue(reg);

    setStatus(`已成功写入 ${reg.name} = ${reg.current_value}`, 'success');
    editingRegister.value = null;
  } catch (err: any) {
    setStatus(`写入寄存器失败: ${err}`, 'error');
  } finally {
    isSubmittingReg.value = false;
  }
}

// Open Edit Field Dialog
function openWriteFieldModal(reg: SvdRegister, field: SvdField) {
  editingField.value = { reg, field };
  editFieldValue.value = field.value !== undefined ? `0x${field.value.toString(16).toUpperCase()}` : '0x0';
}

// Quick toggle single bit field (0 <-> 1)
async function toggleBitField(reg: SvdRegister, field: SvdField) {
  if (field.bit_width !== 1) return;
  const currentBit = field.value ?? 0;
  const newBit = currentBit === 0 ? 1 : 0;
  await submitWriteField(reg, field, newBit);
}

// Confirm Write Field
async function submitWriteField(reg: SvdRegister, field: SvdField, directVal?: number) {
  let val = 0;
  if (directVal !== undefined) {
    val = directVal;
  } else {
    try {
      const raw = editFieldValue.value.trim();
      if (raw.toLowerCase().startsWith('0x')) {
        val = parseInt(raw, 16);
      } else {
        val = parseInt(raw, 10);
      }
      if (isNaN(val)) throw new Error('无效数值格式');
    } catch (e: any) {
      setStatus(e.message, 'error');
      return;
    }
  }

  isSubmittingField.value = true;
  try {
    const res: any = await safeInvoke('svd_write_field', {
      address: reg.address,
      bitOffset: field.bit_offset,
      bitWidth: field.bit_width,
      fieldValue: val >>> 0,
      probeId: selectedProbeId.value || null,
      targetOverride: selectedDeviceName.value || null
    });

    const newValHex = res.new_value || `0x${((reg.current_value_uint ?? 0) >>> 0).toString(16).padStart(8, '0').toUpperCase()}`;
    const newValUint = parseInt(newValHex, 16) >>> 0;
    reg.current_value = newValHex;
    reg.current_value_uint = newValUint;
    reg.current_binary = newValUint.toString(2).padStart(32, '0');
    reg.last_updated = new Date().toLocaleTimeString();
    updateFieldsFromRegValue(reg);

    setStatus(`已更新位域 ${reg.name}->${field.name} = 0x${val.toString(16).toUpperCase()} (全寄存器: ${reg.current_value})`, 'success');
    editingField.value = null;
  } catch (err: any) {
    setStatus(`写入位域失败: ${err}`, 'error');
  } finally {
    isSubmittingField.value = false;
  }
}

// Watch device selection
watch(selectedDeviceName, (newVal) => {
  if (newVal) {
    loadPeripherals(newVal);
  }
});

// Format access badge color
function getAccessBadgeClass(access: string) {
  const acc = (access || '').toLowerCase();
  if (acc.includes('read-write') || acc === 'rw') {
    return 'bg-emerald-950/70 text-emerald-400 border-emerald-800/80';
  } else if (acc.includes('read') || acc === 'ro') {
    return 'bg-blue-950/70 text-blue-400 border-blue-800/80';
  } else if (acc.includes('write') || acc === 'wo') {
    return 'bg-amber-950/70 text-amber-400 border-amber-800/80';
  }
  return 'bg-slate-800 text-slate-400 border-slate-700';
}

onMounted(() => {
  loadDevices();
  loadProbes();
});
</script>

<template>
  <div class="flex flex-col h-full bg-slate-950 text-slate-100 overflow-hidden">
    <!-- Top Control Bar -->
    <header class="flex flex-wrap items-center justify-between px-4 py-3 bg-slate-900 border-b border-slate-800 gap-3">
      <!-- Chip SVD Selector -->
      <div class="flex items-center gap-2">
        <div class="p-1.5 bg-indigo-500/20 text-indigo-400 rounded-lg border border-indigo-500/30">
          <Database class="w-5 h-5" />
        </div>
        <div>
          <div class="text-xs text-slate-400 font-medium flex items-center gap-1.5">
            <span>SVD 设备型号 (CMSIS-Pack 原生支持)</span>
            <span v-if="currentDevice" class="px-1.5 py-0.2 text-[10px] bg-slate-800 text-cyan-400 rounded border border-slate-700">
              {{ currentDevice.core }} | Flash: {{ (currentDevice.flash_size / 1024).toFixed(0) }}KB
            </span>
          </div>
          <div class="relative mt-0.5 flex items-center gap-2">
            <select
              v-model="selectedDeviceName"
              :disabled="isLoadingDevices || devices.length === 0"
              class="bg-slate-800 border border-slate-700 text-white font-semibold text-sm rounded-md px-2.5 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-500 pr-8 cursor-pointer"
            >
              <option v-for="dev in devices" :key="dev.name" :value="dev.name">
                {{ dev.name }} ({{ dev.vendor }} - {{ dev.core }})
              </option>
            </select>

            <button
              @click="handleImportPack"
              :disabled="isImportingPack"
              class="flex items-center gap-1.5 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-indigo-300 hover:text-indigo-200 border border-slate-700 hover:border-indigo-500/50 rounded-md text-xs font-medium transition shadow-sm disabled:opacity-50"
              title="导入外部 CMSIS-Pack (*.pack) 芯片描述包以分析不同芯片"
            >
              <FolderPlus class="w-3.5 h-3.5" :class="{ 'animate-spin': isImportingPack }" />
              <span>{{ isImportingPack ? '正在导入...' : '导入 Pack 描述包' }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- SWD Probe Selector & Batch Read -->
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-2 bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/80 text-xs">
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          <span class="text-slate-400">SWD 探针:</span>
          <select
            v-model="selectedProbeId"
            class="bg-transparent text-slate-200 text-xs outline-none cursor-pointer max-w-[160px] truncate"
          >
            <option v-if="probes.length === 0" value="">无可用调试器探针</option>
            <option v-for="p in probes" :key="p.unique_id" :value="p.unique_id">
              {{ p.description || p.probe_type }} ({{ p.unique_id.slice(-6) }})
            </option>
          </select>
          <button
            @click="loadProbes"
            title="重新扫描探针"
            class="text-slate-400 hover:text-white transition p-0.5 rounded"
          >
            <RefreshCw class="w-3 h-3" />
          </button>
        </div>

        <button
          v-if="selectedPeripheral"
          @click="readAllRegisters"
          :disabled="isBatchReading || isLoadingRegisters"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white rounded-md text-xs font-semibold shadow-md hover:shadow-cyan-500/20 disabled:opacity-50 transition"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isBatchReading }" />
          <span>{{ isBatchReading ? '正在全量读取...' : '一键读取全部寄存器' }}</span>
        </button>
      </div>
    </header>

    <!-- Status Alert Bar -->
    <div
      v-if="statusMessage"
      class="px-4 py-1.5 text-xs flex items-center justify-between border-b transition-all duration-200"
      :class="{
        'bg-emerald-950/70 text-emerald-300 border-emerald-800': statusMessage.type === 'success',
        'bg-rose-950/70 text-rose-300 border-rose-800': statusMessage.type === 'error',
        'bg-blue-950/70 text-blue-300 border-blue-800': statusMessage.type === 'info'
      }"
    >
      <div class="flex items-center gap-2">
        <AlertCircle class="w-4 h-4" />
        <span>{{ statusMessage.text }}</span>
      </div>
      <button @click="statusMessage = null" class="text-xs opacity-70 hover:opacity-100">&times;</button>
    </div>

    <!-- Main Content Grid (Left Peripherals, Right Registers Table) -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left Sidebar: Peripherals Navigation -->
      <aside class="w-64 sm:w-72 bg-slate-900/90 border-r border-slate-800 flex flex-col shrink-0">
        <!-- Search Peripherals -->
        <div class="p-3 border-b border-slate-800">
          <div class="relative">
            <Search class="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
            <input
              v-model="peripheralFilter"
              type="text"
              placeholder="搜索外设 (UART, GPIO...)"
              class="w-full bg-slate-800/80 border border-slate-700/80 rounded-md pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div class="flex justify-between items-center mt-2 px-1 text-[11px] text-slate-400">
            <span>外设列表</span>
            <span class="bg-slate-800 px-1.5 py-0.5 rounded text-slate-300 font-mono">
              {{ filteredPeripherals.length }} / {{ peripherals.length }}
            </span>
          </div>
        </div>

        <!-- Peripheral Items List -->
        <div class="flex-1 overflow-y-auto divide-y divide-slate-800/50">
          <div
            v-if="isLoadingPeripherals"
            class="p-6 text-center text-xs text-slate-400 flex flex-col items-center gap-2"
          >
            <RefreshCw class="w-5 h-5 animate-spin text-indigo-400" />
            <span>加载 SVD 外设字典中...</span>
          </div>

          <div
            v-else-if="filteredPeripherals.length === 0"
            class="p-6 text-center text-xs text-slate-500"
          >
            未匹配到外设模块
          </div>

          <button
            v-for="p in filteredPeripherals"
            :key="p.name"
            @click="selectPeripheral(p)"
            class="w-full text-left px-3.5 py-2.5 flex flex-col gap-1 transition-colors group relative"
            :class="selectedPeripheral?.name === p.name ? 'bg-indigo-950/40 text-white' : 'hover:bg-slate-800/60 text-slate-300'"
          >
            <div
              v-if="selectedPeripheral?.name === p.name"
              class="absolute left-0 top-0 bottom-0 w-1 bg-indigo-500 rounded-r"
            />
            <div class="flex items-center justify-between">
              <span class="font-bold text-xs group-hover:text-indigo-300 font-mono tracking-wide"
                :class="selectedPeripheral?.name === p.name ? 'text-indigo-400 font-semibold' : 'text-slate-200'"
              >
                {{ p.name }}
              </span>
              <span class="text-[10px] font-mono text-slate-500 bg-slate-800/90 px-1.5 py-0.5 rounded border border-slate-700/60">
                {{ p.base_address }}
              </span>
            </div>
            <div class="text-[11px] text-slate-400 truncate" :title="p.description">
              {{ p.description || p.group_name || '外设控制模块' }}
            </div>
          </button>
        </div>
      </aside>

      <!-- Right Main: Registers Table & Bitfields Inspector -->
      <main class="flex-1 flex flex-col overflow-hidden bg-slate-950">
        <!-- Selected Peripheral Header -->
        <div v-if="selectedPeripheral" class="px-5 py-3 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-base font-bold text-white font-mono tracking-wide">{{ selectedPeripheral.name }}</h2>
              <span class="text-xs px-2 py-0.5 bg-indigo-950/80 text-indigo-300 rounded border border-indigo-800/80 font-mono">
                基地址: {{ selectedPeripheral.base_address }}
              </span>
              <span v-if="selectedPeripheral.group_name" class="text-xs px-2 py-0.5 bg-slate-800 text-slate-300 rounded border border-slate-700">
                {{ selectedPeripheral.group_name }}
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-0.5">{{ selectedPeripheral.description || '无详细功能描述' }}</p>
          </div>

          <!-- Register Search Filter -->
          <div class="flex items-center gap-2">
            <div class="relative w-48 sm:w-60">
              <Search class="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
              <input
                v-model="registerFilter"
                type="text"
                placeholder="过滤当前寄存器..."
                class="w-full bg-slate-800/80 border border-slate-700 rounded-md pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div class="text-xs text-slate-400 font-mono">
              {{ filteredRegisters.length }} 个寄存器
            </div>
          </div>
        </div>

        <!-- Registers Table Container -->
        <div class="flex-1 overflow-y-auto p-4 space-y-2">
          <div
            v-if="isLoadingRegisters"
            class="h-64 flex flex-col items-center justify-center gap-3 text-slate-400 text-xs"
          >
            <RefreshCw class="w-6 h-6 animate-spin text-indigo-500" />
            <span>正在解析 {{ selectedPeripheral?.name }} 的 SVD 寄存器字典...</span>
          </div>

          <div
            v-else-if="!selectedPeripheral"
            class="h-64 flex flex-col items-center justify-center text-slate-500 text-xs"
          >
            请从左侧选择外设模块
          </div>

          <div
            v-else-if="filteredRegisters.length === 0"
            class="h-64 flex flex-col items-center justify-center text-slate-500 text-xs"
          >
            无匹配寄存器
          </div>

          <!-- Registers Card / List -->
          <div
            v-for="reg in filteredRegisters"
            :key="reg.name"
            class="bg-slate-900 border border-slate-800/90 rounded-lg overflow-hidden transition-all shadow-sm hover:border-slate-700"
          >
            <!-- Register Row -->
            <div class="px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 bg-slate-900/90 hover:bg-slate-850">
              <div class="flex items-center gap-3 min-w-[200px]">
                <button
                  @click="toggleExpandRegister(reg)"
                  class="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition"
                  :title="reg.is_expanded ? '折叠位域详情' : '展开位域详情'"
                >
                  <ChevronDown v-if="reg.is_expanded" class="w-4 h-4 text-indigo-400" />
                  <ChevronRight v-else class="w-4 h-4" />
                </button>

                <div>
                  <div class="flex items-center gap-2">
                    <span class="font-bold text-sm text-slate-100 font-mono">{{ reg.name }}</span>
                    <span class="text-[11px] font-mono text-slate-400 bg-slate-800/80 px-1.5 py-0.2 rounded border border-slate-700/60">
                      {{ reg.offset }}
                    </span>
                    <span
                      class="text-[10px] font-medium px-1.5 py-0.2 rounded border font-mono uppercase"
                      :class="getAccessBadgeClass(reg.access)"
                    >
                      {{ reg.access }}
                    </span>
                  </div>
                  <div class="text-[11px] text-slate-400 truncate max-w-md mt-0.5" :title="reg.description">
                    {{ reg.description || '无描述' }}
                  </div>
                </div>
              </div>

              <!-- Register Values & Live Control -->
              <div class="flex items-center gap-3">
                <!-- Physical Address -->
                <div class="hidden md:flex flex-col items-end text-right">
                  <span class="text-[10px] text-slate-500 uppercase tracking-wider font-mono">物理地址</span>
                  <span class="text-xs font-mono text-slate-300">{{ reg.address }}</span>
                </div>

                <!-- Reset Value -->
                <div class="hidden lg:flex flex-col items-end text-right">
                  <span class="text-[10px] text-slate-500 uppercase tracking-wider font-mono">复位值</span>
                  <span class="text-xs font-mono text-slate-400">{{ reg.reset_value }}</span>
                </div>

                <!-- Live Value Display -->
                <div class="flex flex-col items-end">
                  <span class="text-[10px] text-slate-500 uppercase tracking-wider font-mono flex items-center gap-1">
                    <span>当前硬件值</span>
                    <span v-if="reg.last_updated" class="text-[9px] text-emerald-400">({{ reg.last_updated }})</span>
                  </span>
                  <div class="flex items-center gap-1">
                    <span
                      class="text-xs font-mono px-2 py-0.5 rounded border font-semibold"
                      :class="reg.current_value ? 'bg-indigo-950/80 text-cyan-300 border-indigo-700/80' : 'bg-slate-800 text-slate-500 border-slate-700'"
                    >
                      {{ reg.current_value || '尚未读取' }}
                    </span>
                  </div>
                </div>

                <!-- Actions: Read & Write -->
                <div class="flex items-center gap-1.5">
                  <button
                    @click="readRegister(reg)"
                    :disabled="reg.is_reading"
                    class="p-1.5 bg-slate-800 hover:bg-slate-700 text-cyan-400 hover:text-cyan-300 rounded border border-slate-700 text-xs flex items-center gap-1 transition"
                    title="从单片机硬件通过 SWD 读取寄存器"
                  >
                    <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': reg.is_reading }" />
                    <span class="hidden sm:inline">读取</span>
                  </button>

                  <button
                    v-if="!reg.access.toLowerCase().includes('read-only')"
                    @click="openWriteRegisterModal(reg)"
                    class="p-1.5 bg-slate-800 hover:bg-slate-700 text-amber-400 hover:text-amber-300 rounded border border-slate-700 text-xs flex items-center gap-1 transition"
                    title="向单片机寄存器写入新值"
                  >
                    <Edit3 class="w-3.5 h-3.5" />
                    <span class="hidden sm:inline">写入</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Expanded Bitfields Section -->
            <div
              v-if="reg.is_expanded"
              class="border-t border-slate-800 bg-slate-950/80 px-4 py-3"
            >
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2 text-xs font-semibold text-slate-300">
                  <Sliders class="w-3.5 h-3.5 text-indigo-400" />
                  <span>寄存器位域分解 (Bitfields - 32-bit):</span>
                </div>
                <div v-if="reg.current_binary" class="text-[11px] font-mono text-cyan-400/90 tracking-wider">
                  BIN: {{ reg.current_binary }}
                </div>
              </div>

              <!-- Bitfields Table -->
              <div v-if="reg.fields && reg.fields.length > 0" class="overflow-x-auto border border-slate-800 rounded-md">
                <table class="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr class="bg-slate-900/90 text-slate-400 font-mono text-[11px] border-b border-slate-800">
                      <th class="py-1.5 px-2.5 w-20">位区间</th>
                      <th class="py-1.5 px-2.5 w-36">位域名称</th>
                      <th class="py-1.5 px-2.5 w-20">属性</th>
                      <th class="py-1.5 px-2.5 w-32">当前位值</th>
                      <th class="py-1.5 px-2.5">功能描述</th>
                      <th class="py-1.5 px-2.5 w-32 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-800/60 font-mono">
                    <tr
                      v-for="field in reg.fields"
                      :key="field.name"
                      class="hover:bg-slate-900/50 transition-colors"
                    >
                      <td class="py-1.5 px-2.5 text-indigo-300 font-semibold">
                        {{ field.bit_range }}
                      </td>
                      <td class="py-1.5 px-2.5 font-bold text-slate-200">
                        {{ field.name }}
                      </td>
                      <td class="py-1.5 px-2.5">
                        <span
                          class="text-[10px] px-1 py-0.2 rounded border font-mono"
                          :class="getAccessBadgeClass(field.access)"
                        >
                          {{ field.access }}
                        </span>
                      </td>
                      <td class="py-1.5 px-2.5">
                        <div v-if="field.value !== undefined" class="flex items-center gap-1.5">
                          <span class="text-cyan-400 font-semibold">{{ field.hex_value }}</span>
                          <span class="text-[10px] text-slate-500">({{ field.value }})</span>
                        </div>
                        <span v-else class="text-slate-600 text-[11px]">未采样</span>
                      </td>
                      <td class="py-1.5 px-2.5 text-slate-400 font-sans text-[11px]" :title="field.description">
                        {{ field.description || '保留/无说明' }}
                      </td>
                      <td class="py-1.5 px-2.5 text-right font-sans">
                        <div class="flex items-center justify-end gap-1.5">
                          <!-- 1-bit Quick Toggle -->
                          <button
                            v-if="field.bit_width === 1 && !field.access.toLowerCase().includes('read-only')"
                            @click="toggleBitField(reg, field)"
                            class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold transition"
                            :class="field.value === 1 ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700'"
                            :title="`快速切换位状态 (当前为 ${field.value ?? 0})`"
                          >
                            {{ field.value === 1 ? '1 [开]' : '0 [关]' }}
                          </button>

                          <!-- Write Field Dialog Button -->
                          <button
                            v-if="!field.access.toLowerCase().includes('read-only')"
                            @click="openWriteFieldModal(reg, field)"
                            class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-indigo-300 rounded border border-slate-700 text-[11px] transition"
                            title="修改位域数值并写入"
                          >
                            修改
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="text-xs text-slate-500 italic py-2">
                该寄存器 SVD 中未定义具体位域分解。
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- Modal: Write Register Dialog -->
    <div
      v-if="editingRegister"
      class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4 backdrop-blur-sm"
    >
      <div class="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <div class="flex items-center gap-2">
            <Edit3 class="w-5 h-5 text-indigo-400" />
            <h3 class="font-bold text-white text-sm">写入寄存器: {{ editingRegister.name }}</h3>
          </div>
          <button @click="editingRegister = null" class="text-slate-400 hover:text-white">&times;</button>
        </div>

        <div class="space-y-3 text-xs">
          <div class="bg-slate-950 p-2.5 rounded border border-slate-800 text-slate-300 space-y-1 font-mono">
            <div class="flex justify-between">
              <span class="text-slate-500">所属外设:</span>
              <span class="text-slate-200">{{ selectedPeripheral?.name }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">物理地址:</span>
              <span class="text-slate-200">{{ editingRegister.address }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">当前读取值:</span>
              <span class="text-cyan-400">{{ editingRegister.current_value || '未知' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">复位默认值:</span>
              <span class="text-slate-400">{{ editingRegister.reset_value }}</span>
            </div>
          </div>

          <div>
            <label class="block text-slate-400 mb-1 font-medium">要写入的十六进制或十进制数值:</label>
            <input
              v-model="editRegValueHex"
              type="text"
              placeholder="例如: 0x00000001 或 0x12"
              class="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-indigo-500"
              @keyup.enter="confirmWriteRegister"
            />
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-slate-800">
          <button
            @click="editingRegister = null"
            class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs transition"
          >
            取消
          </button>
          <button
            @click="confirmWriteRegister"
            :disabled="isSubmittingReg"
            class="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded text-xs transition flex items-center gap-1.5 disabled:opacity-50"
          >
            <RefreshCw v-if="isSubmittingReg" class="w-3.5 h-3.5 animate-spin" />
            <span>确认写入 SWD</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Modal: Write Field Dialog -->
    <div
      v-if="editingField"
      class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4 backdrop-blur-sm"
    >
      <div class="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <div class="flex items-center gap-2">
            <Sliders class="w-5 h-5 text-indigo-400" />
            <h3 class="font-bold text-white text-sm">修改位域: {{ editingField.field.name }}</h3>
          </div>
          <button @click="editingField = null" class="text-slate-400 hover:text-white">&times;</button>
        </div>

        <div class="space-y-3 text-xs">
          <div class="bg-slate-950 p-2.5 rounded border border-slate-800 text-slate-300 space-y-1 font-mono">
            <div class="flex justify-between">
              <span class="text-slate-500">所属寄存器:</span>
              <span class="text-slate-200">{{ editingField.reg.name }} ({{ editingField.reg.offset }})</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">位域区间:</span>
              <span class="text-indigo-300">{{ editingField.field.bit_range }} ({{ editingField.field.bit_width }} 位)</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">当前位值:</span>
              <span class="text-cyan-400">{{ editingField.field.hex_value || '0x0' }} ({{ editingField.field.value ?? 0 }})</span>
            </div>
          </div>

          <div>
            <label class="block text-slate-400 mb-1 font-medium">输入新位值 (0x 或 十进制):</label>
            <input
              v-model="editFieldValue"
              type="text"
              placeholder="例如: 0x1 或 3"
              class="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-indigo-500"
              @keyup.enter="submitWriteField(editingField.reg, editingField.field)"
            />
            <p class="text-[11px] text-slate-500 mt-1">
              注意: 修改位域会自动保持寄存器中其它无关位不变 (执行 Read-Modify-Write 操作)。
            </p>
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-slate-800">
          <button
            @click="editingField = null"
            class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs transition"
          >
            取消
          </button>
          <button
            @click="submitWriteField(editingField.reg, editingField.field)"
            :disabled="isSubmittingField"
            class="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded text-xs transition flex items-center gap-1.5 disabled:opacity-50"
          >
            <RefreshCw v-if="isSubmittingField" class="w-3.5 h-3.5 animate-spin" />
            <span>写入位域</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
