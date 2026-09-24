# 多 AXF 联合分析与底层平台加密符号库架构规划方案
(Multi-AXF & Platform Symbol Vault Architecture Plan)

---

## 1. 背景与工程痛点

在现代无线连接与边缘计算 SoC（如 INGChips ING918xx / ING916xx / ING20xx、Nordic nRF 系列、恒玄 BES 等）工程开发中，固件普遍采用**分层镜像或多核隔离架构**：
- **底层平台 (`platform.bin` / ROM)**：原厂闭源维护，集成硬件底层驱动、射频/协议栈控制器、以及 **RTOS 内核调度器**；
- **上层应用 (`app.axf` / `app.bin`)**：开发者编写业务代码，通过函数跳转表或系统调用调用底层能力。

### 核心痛点：
1. **RTOS 调度与任务监控完全断层**：
   - 开发者仅有 `app.axf`，而 FreeRTOS/RT-Thread/LiteOS 的关键内核控制块（`pxReadyTasksLists`、`pxCurrentTCB`、任务堆栈数组）全部编译在 `platform.bin` 中。
   - 上位机无法定位任务列表、堆栈水位及 CPU 占用率，**RTOS Trace 功能在闭源平台架构下失效**。
2. **HardFault 崩溃穿透定位失败**：
   - 当应用传参错误导致底层死锁或野指针访问时，PC / LR 落在底层地址空间（如 `0x0000xxxx` 或 `0x0200xxxx`）。
   - `app.axf` 无法反查底层符号，调用栈中断在 `[Unknown Module] 0x0000452A`，无法追溯到底是哪个上层调用触发了内核异常。
3. **闭源安全性与调试透明度的矛盾**：
   - 原厂无法直接将 `platform.axf`（含源码符号、函数名、结构体定义与源码行）公开给所有终端开发者；
   - 但开发者又极度渴望底层关键调度器符号的可视化调试能力。

---

## 2. 总体架构设计

通过**“符号数据库提纯 + AES 内存加密保管箱 + 多符号域动态聚合引擎”**，在**不泄露平台敏感代码**的前提下，让上位机在内存中安全解密并缝合底层与应用层符号表。

```
┌────────────────────────────────────────────────────────┐
│                   上位机前端界面 (Vue 3)                 │
│  - 多 AXF/ELF 列表管理                                  │
│  - 平台符号库版本选择 (如 ING91800 SDK 2.2 / ING2000)   │
│  - 跨域 RTOS 任务监控 / HardFault 穿透栈回溯           │
└───────────────────────────┬────────────────────────────┘
                            │ JSON-RPC
┌───────────────────────────▼────────────────────────────┐
│              Rust 后端 / Python MCP 守护进程            │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │   平台符号安全保险箱 (Platform Symbol Vault)        │  │
│  │   - 内置 .vault 加密包 (AES-256-GCM 封装)         │  │
│  │   - 仅包含 RTOS 控制块与公开 API 签名 (无源码行)   │  │
│  │   - 运行时流式内存解密 (绝不落地写磁盘临时文件)     │  │
│  └──────────────────────────┬───────────────────────┘  │
│                             │ 内存数据流                │
│  ┌──────────────────────────▼───────────────────────┐  │
│  │        多符号域聚合引擎 (Symbol Union Engine)     │  │
│  │   - 地址区间映射 (Domain Partitioning)           │  │
│  │   - 重名符号作用域隔离 (Scope Isolation)          │  │
│  │   - 联合全局符号检索 (Unified Symbol Lookup)       │  │
│  └──────────────────────────┬───────────────────────┘  │
│                             │ 联合符号查询              │
│         ┌───────────────────┼───────────────────┐      │
│         ▼                   ▼                   ▼      │
│   [RTOS 内核感知]     [HardFault 穿透]    [J-Scope 采样]│
└────────────────────────────────────────────────────────┘
```

---

## 3. 详细子系统规划

### 3.1 平台符号提纯与安全加密机制 (Symbol Vault)

#### 3.1.1 符号抽取（Stripping & Extraction）
原厂发布 Platform SDK 时，运行专用脚本处理 `platform.axf`，剔除 DWARF 调试代码行信息与内部算法实现函数，**仅萃取调试所需的核心元数据**：
- **RTOS 调度器内核变量**：
  - `pxCurrentTCB`、`pxReadyTasksLists`、`xDelayedTaskList1`、`xTickCount` 等；
  - 任务控制块（TCB）中各字段的字节偏移（`uxPriority_offset`, `pxTopOfStack_offset`, `pcTaskName_offset`）；
- **对外公开驱动与 API 函数入口**：
  - 函数名、地址范围 `[start_addr, end_addr]`，用于崩溃调用栈解析；
- **基础外设与内存边界**：
  - Platform 占据的 RAM 起止地址与保留堆栈边界。

#### 3.1.2 加密打包格式 (`.vault`)
- 采用二进制紧凑格式（Protobuf 或 MsgPack），体积通常从几十 MB 缩减至 **< 150KB**；
- 采用 **AES-256-GCM** 或 **ChaCha20-Poly1305** 加密（带消息认证码 MAC，防篡改）；
- 存储于 `assets/platforms/{chip_family}_{version}.vault`；
- 解密密钥由上位机 Rust 后端动态生成并受控维护，解密过程仅存在于进程 Working Memory 中，**绝不在操作系统写出任何明文临时文件**。

---

### 3.2 多符号域聚合引擎 (Multi-Domain Symbol Union)

在现有的单一 ELF/AXF 解析器基础上，升级为**多域符号管理器**：

```python
class SymbolDomain:
    name: str             # 如 "platform" 或 "app"
    base_address: int     # 装载基地址
    memory_ranges: list   # 所辖物理地址段 [(0x00000000, 0x00020000), ...]
    symbols: dict         # 地址 -> 符号信息
    structures: dict      # 结构体定义与字段偏移
    is_protected: bool    # 是否为内置加密符号库

class MultiDomainSymbolManager:
    domains: List[SymbolDomain]

    def lookup_symbol_by_address(self, addr: int) -> Optional[SymbolInfo]:
        """按地址区间精准路由到对应符号域，防止不同镜像地址重叠冲突"""
        for domain in self.domains:
            if domain.contains_address(addr):
                return domain.lookup_address(addr)
        return None

    def lookup_rtos_kernel_symbols(self) -> Dict[str, int]:
        """优先从 platform 域获取 RTOS 内核调度器指针"""
        ...
```

---

### 3.3 典型应用场景联动增强

#### 场景 1：RTOS 任务级穿透监控 (RTOS Tracer)
- **输入**：用户仅需载入自己的 `app.axf`，上位机根据芯片型号（如 `ING91800`）自动装载内置的 `ing918_platform_v2.vault`。
- **效果**：
  1. 上位机从加密 Vault 中拿到底层 RTOS 的 `pxReadyTasksLists` 地址与 TCB 结构偏移；
  2. 通过 SWD/DAPLink 直接抓出芯片内运行的全部任务列表、任务名、实时栈顶、剩余深度与运行状态；
  3. 用户无需在 App 代码中包含 RTOS 调试宏，即可在前端看到原生任务仪表盘。

#### 场景 2：跨越 Platform 边界的 HardFault 穿透分析
- **输入**：MCU 发生硬件硬故障（HardFault），堆栈 PC 停在 `0x00004A12`（Platform 代码段）。
- **效果**：
  1. 回溯栈帧时，上位机同时索引 `app.axf` 与 Platform Vault；
  2. 诊断结果精确展示两级调用拓扑：
     ```text
     [Level 0 - App]      user_ble_send()  at main.c:142
     [Level 1 - Platform] ble_tx_enqueue() at 0x00002100 (platform.bin)
     [Level 2 - Platform] xQueueGenericSend() + 0x24 (platform.bin) -> Triggered Null Pointer HardFault
     ```
  3. 一针见血指出根因：“上层 App 传入了非法空指针，导致底层平台队列函数异常”。

#### 场景 3：J-Scope / 实时变量采样扩展
- 支持在采样配置列表中，不仅可以选择 App 中的全局变量，还可以直接勾选 Platform 暴露的连接计数器、RSSI 状态机变量或协议栈缓冲区指针进行波形采样。

---

## 4. UI 交互体验设计

在上位机前端的“固件资源分析”与“RTOS 任务Trace”页面中，引入**联合符号库控制面板**：

1. **自动模式（零配置）**：
   - 默认选中“自动匹配芯片原厂平台符号库”；
   - 载入 App 固件时，系统自动识别芯片架构并激活对应 Vault。
2. **多 AXF 手动装配模式（高级）**：
   - 提供多文件卡片列表：
     - `[1] platform.axf`（支持从外部载入或选用内置 Vault）
     - `[2] ble_stack.axf`
     - `[3] app.axf`
   - 支持动态启用/禁用某个符号层；
   - 展示各个符号层在 Flash/RAM 中的地址空间分布比例，形成**完整的系统内存全景拼图**。

---

## 5. 分阶段推进路线建议

| 阶段 | 重点任务 | 预期交付物 |
| :--- | :--- | :--- |
| **阶段 1：多 AXF 引擎升级** | 扩展 Python 后端 `AxfSymbolParser`，支持传入多个 AXF 并在内存中合并地址索引表；前端增加多 AXF 选取与列表展示。 | 支持手动多选多个 AXF 进行联合符号反查。 |
| **阶段 2：轻量 Vault 格式与加密** | 定义紧凑的符号 Protobuf/MsgPack 结构，编写 AXF $\to$ Vault 萃取脚本；在 Rust/Python 中集成 AES-GCM 内存解密机制。 | 能够将百兆级 AXF 萃取为 < 150KB 的加密 `.vault` 文件。 |
| **阶段 3：原厂平台预置与自动装配** | 将 INGChips 各系列芯片（ING918xx、ING916xx、ING20xx）标准 SDK 的平台符号打包内置，完成开箱即用的自动化装配。 | 用户只拖入业务 `app.axf`，上位机即可穿透分析底层 RTOS 与 HardFault。 |
| **阶段 4：商业与权限控制（可选）** | 若原厂对部分高密算法符号有客户权限区分，可支持通过 License Key 激活特定深度符号域。 | 灵活的原厂商业与安全隔离方案。 |

---

## 6. 总结与建议

多 AXF 联合分析方案**完美切中了闭源平台与开放应用之间的调试断层痛点**：
- **对原厂**：核心代码和源码行路径不泄露，安全性 100% 受控；
- **对用户**：使用体验从“两眼一摸黑”跃升至“全系统穿透透视”，极大提升 RTOS 调试与故障定位效率；
- **对上位机**：形成了同类通用调试工具（如 Keil / Ozone）在芯片平台层面的**显著差异化壁垒**。
