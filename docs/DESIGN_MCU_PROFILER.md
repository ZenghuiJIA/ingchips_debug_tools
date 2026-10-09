# MCU 实时性能与耗时统计分析器 (MCU Runtime Profiler & Performance Monitor) 详细设计方案

## 1. 方案背景与目标

在嵌入式固件开发与调试过程中，系统性能分析（CPU 占用率、中断服务程序 ISR 执行耗时、关键算法函数耗时、RTOS 任务调度抖动）是优化代码和定位疑难卡死 Bug 的核心手段。
传统做法往往采用以下方式，各有弊端：
1. **GPIO 引脚打点配合示波器**：需要额外硬件硬件连接，占用芯片有限的 GPIO 引脚，且无法大规模批量分析。
2. **串口 `printf` 打印时间戳**：侵入性极强，串口输出本身消耗数十毫秒级别的时间，严重干扰实时系统时序。
3. **软件定时器中断打点**：增加了中断开销，且分辨率有限。

### 核心目标
本项目方案依托 Cortex-M 架构内置的 **DWT (Data Watchpoint and Trace) 周期计数器**、**SWD 硬件调试通道**以及 **RTT 超高速共享内存**，实现以下目标：
- **微侵入 / 免侵入** 纳秒/微秒级函数执行耗时统计；
- 统计并可视化函数的 **Min / Max / Avg / P99 耗时分布直方图**；
- 实时 CPU 负载率折线图与火焰图（Flame Graph）；
- 超时/抖动阈值告警（如中断执行超过 200µs 自动高亮并记录调用现场）。

---

## 2. 硬件与底层技术原理

ARM Cortex-M3/M4/M7/M33 内核集成了 CoreDebug 与 DWT 硬件模块：
1. **DWT->CYCCNT (Cycle Count Register, 0xE0001004)**：
   - 32 位递增计数器，以 CPU 主频的时钟频率（如 64MHz/120MHz/240MHz）单周期递增。
   - 1 个周期的分辨率在 100MHz 下达到 10ns，无需消耗额外定时器外设。
2. **DEMCR (Debug Exception and Monitor Control Register, 0xE000EDFC)**：
   - 将 TRCENA 位（bit 24）置 1，即可解锁 DWT 外设。
3. **DWT->CTRL (0xE0001000)**：
   - 将 CYCCNTENA 位（bit 0）置 1，即可启动周期计数器；支持配置采样分频器产生 PC (Program Counter) 采样事件。

### 双模式采集架构
```
+--------------------------------------------------------------------------------+
|                               模式 A: 微侵入打点模式                            |
|  MCU 固件 (轻量宏打点，约 4~6 条汇编指令):                                       |
|     PROFILER_ENTER(FUNC_ID_BLE_POLL);                                          |
|        uint32_t t0 = DWT->CYCCNT;                                              |
|        ... 业务逻辑 ...                                                        |
|     PROFILER_EXIT(FUNC_ID_BLE_POLL);                                           |
|        ring_buffer_push(FUNC_ID_BLE_POLL, DWT->CYCCNT - t0);                   |
|                                                                                |
|  数据输出通道: RTT Up-Buffer 专用通道 (通道 2，无阻塞环形队列，吞吐 > 2MB/s)       |
+--------------------------------------------------------------------------------+
                                       或
+--------------------------------------------------------------------------------+
|                               模式 B: 免侵入 SWD 轮询模式                       |
|  PC 采样 / DWT 比较器:                                                          |
|     Debugger 硬件仿真器通过 SWD 周期性读取 PC 寄存器与 DWT_CYCCNT                 |
|     结合固件 .axf/.elf 符号表，解析统计各函数在采样窗口内的命中百分比 (CPU 负载)    |
+--------------------------------------------------------------------------------+
```

---

## 3. 系统架构与模块划分

```mermaid
flowchart TD
    subgraph Target MCU
        MCU_App["固件运行区"] --> DWT["DWT 周期计数器 (CYCCNT)"]
        MCU_App --> RTT_Buf["RTT Profiler 环形缓冲区"]
    end

    subgraph Rust 后端 (hil-daemon)
        DAP["DAPLink / CMSIS-DAP / J-Link"] -->|SWD 轮询/读取| RTT_Reader["RTT 高速流解析引擎"]
        DAP -->|SWD 寄存器控制| DWT_Ctrl["DWT 控制模块 (使能/复位)"]
        RTT_Reader --> Proto_Parser["Profiler 二进制帧协议解析"]
        Proto_Parser --> Stat_Engine["耗时分布与统计引擎 (Min/Max/Avg/Jitter)"]
        Stat_Engine --> IPC["Tauri IPC 消息分发 (profiler-data)"]
    end

    subgraph 前端 UI (Vue 3)
        IPC --> Profiler_View["Profiler 主面板"]
        Profiler_View --> Tab_Hist["耗时分布直方图 & 列表"]
        Profiler_View --> Tab_Cpu["CPU 负载趋势图 (Chart.js / Canvas)"]
        Profiler_View --> Tab_Flame["函数调用时间火焰图"]
        Profiler_View --> Tab_Alert["超限告警与事件捕捉"]
    end
```

---

## 4. 数据协议设计 (MCU 端与上位机传输)

为了将 MCU 端开销压缩到极致，MCU 打点输出格式为极简 8 字节二进制结构体：

```c
// MCU 侧输出协议包 (对齐为 8 字节)
typedef struct __attribute__((packed)) {
    uint16_t func_id;       // 函数/任务唯一标识 (对应上位机导入的符号 ID 或枚举)
    uint16_t flags;         // 标志位: bit0=Enter/Exit, bit1=超时报警, bit2-15=保留
    uint32_t delta_cycles;  // 耗费的 CPU 时钟周期数 (Exit 时填写) 或起始绝对周期 (Enter 时)
} profiler_event_t;
```

上位机收到 `delta_cycles` 后，根据当前配置的 MCU 主频（如 64MHz）：
$$\text{耗时} = \frac{\text{delta\_cycles}}{\text{CPU\_FREQ\_HZ}} \times 10^6 \quad (\mu\text{s})$$

---

## 5. 前端功能与交互设计

1. **配置面板**：
   - **CPU 主频设置**：支持快速选择 16MHz、32MHz、48MHz、64MHz、120MHz、168MHz、240MHz 或自定义。
   - **符号表关联**：关联当前已加载的 `.axf` / `.elf` 文件，根据函数名称自动分配 `func_id`。
   - **采样模式切换**：模式 A (RTT 高精度打点) / 模式 B (SWD PC 采样热点统计)。
2. **实时数据列表 (Data Grid)**：
   - 列定义：`函数名称 / 任务`、`当前执行耗时`、`最小耗时 (Min)`、`最大耗时 (Max)`、`平均耗时 (Avg)`、`P95 耗时`、`调用频次 (Calls/s)`、`总 CPU 占比 (%)`。
   - 排序与筛选：支持按 Max 耗时倒序排列，快速定位性能瓶颈。
3. **可视化图表**：
   - **耗时分布直方图 (Histogram)**：展示单个函数执行耗时的分布正态区间（排查偶发长耗时抖动）。
   - **CPU 负载时序图**：实时 1 秒滑动窗口，折线展示系统综合 CPU 占用率。
4. **超限告警 (Timeout Trigger)**：
   - 用户可设定特定函数的告警阈值（例如 `ble_event_process` > 1500µs）。
   - 一旦触发，界面高亮告警行，记录发生时刻、持续时间，并可选通过 SWD 暂停 CPU 查看调用栈。

---

## 6. 后端 IPC 接口与 MCP 自动化工具

### Tauri IPC Commands
- `profiler_enable_dwt(probe_index: number, cpu_freq: number): Promise<boolean>`
- `profiler_start_session(mode: 'rtt' | 'swd', sample_rate_hz: number): Promise<void>`
- `profiler_stop_session(): Promise<void>`
- `profiler_get_statistics(): Promise<ProfilerFunctionStats[]>`
- `profiler_clear_data(): Promise<void>`

### AI / MCP 集成工具
- `mcp_profiler_get_top_cpu_consumers(limit: number)`: 返回当前 CPU 占用最高的前 N 个函数及最大耗时。
- `mcp_profiler_analyze_jitter(function_name: string)`: AI 自动评估该函数的执行耗时方差并分析可能阻塞的原因。

---

## 7. 实施计划与里程碑

1. **第一阶段 (固件与 Rust 后端引擎)**：
   - 实现 SWD 一键使能 CoreDebug DEMCR 与 DWT CYCCNT。
   - 编写 MCU 侧轻量开源打点头文件 `hil_profiler.h`（开源放至 `scripts/mcu_include/`）。
   - 实现 RTT 二进制数据帧解算与统计计数器（Min/Max/Avg/Histogram）。
2. **第二阶段 (前端界面集成)**：
   - 开发 `src/components/McuProfiler.vue` 界面组件。
   - 接入 Canvas 实时直方图与虚拟长列表展示。
3. **第三阶段 (联调与发布)**：
   - 在 ING9188 / ING9168 及通用 STM32 上进行主频耗时精度校准验证。
