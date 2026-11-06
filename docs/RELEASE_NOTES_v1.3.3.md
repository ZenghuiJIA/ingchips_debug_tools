# AI-HIL Debugger v1.3.3 Release Notes

## 🚀 智能硬件助手全面升级：AI 原生 MCP 深度集成与桌面资源共享架构

本版本主要聚焦于 **AI 在环 MCP 助手的全模块能力整合**、**跨进程资源共享架构（Vue 桌面与外部 MCP 客户端无冲突）** 以及 **ING 芯片串口烧录硬件复位自动触发体验修复**。

---

### 1. ING 串口烧录硬件复位自动握手修复
- **默认恢复硬件自动复位脉冲**：
  - 放开此前对 `manual_boot` 的硬编码限制，默认开启自动 RTS/DTR 脉冲时序；
  - 启动烧录时自动拉高 RTS 进入 ISP Bootloader 模式，并下发 100ms DTR 低电平复位脉冲；提供 800ms 二次容错微脉冲；
- **交互式手动 Bootloader 模式开关**：
  - 界面新增可交互的“手动进入 Boot 模式”复选框，并通过 `localStorage` 进行用户习惯记忆；
  - 勾选后支持为非标准接线或独立引脚板卡提供 15 秒等待窗口，引导用户手动按键复位。

---

### 2. AI 在环 MCP 助手模块能力深度集成
原生支持通过大模型标准协议（Model Context Protocol）直接调度底层硬件引擎：
- **SWD 调试与芯片状态透视**：
  - `list_probes`：扫描并枚举所有在线的 DAPLink / CMSIS-DAP / J-Link 调试探针；
  - `read_core_registers`：一键抓取 ARM Cortex-M 核心寄存器（R0-R12, SP/MSP/PSP, LR, PC, xPSR, PRIMASK）并以结构化表格呈现；
  - `read_memory` / `write_memory`：直读直写指定内存地址，支持 32 位地址自动对齐校验与保护；
  - `reset_target`：通过 SWD 总线直接发送目标 MCU 硬件复位命令并释放运行；
  - `diagnose_hardfault`：读取 CFSR / HFSR / MMFAR / BFAR 崩溃现场寄存器并自动输出诊断分析与修复建议。
- **全功能串口读写与监测调度**：
  - `list_serial_ports`：扫描系统当前可用串口及 DAPLink CDC 设备信息；
  - `read_serial_data`：获取指定串口当前的最新 RX/TX 数据片段流；
  - `send_serial_data`：支持下发 HEX 字节数组或 UTF-8 文本数据。
- **UI 界面快速交互卡片与快捷按钮**：
  - 底部快速指令栏扩充：`[🔍 扫描可用串口]`、`[📥 读取串口最新数据]`、`[📊 读取 CPU 核心寄存器]`、`[🔄 SWD 目标复位]`；
  - 支持中英文双语界面（i18n 自动适配）。

---

### 3. Desktop IPC Bridge 跨进程资源共享架构（MCP 与 Vue 零冲突）
针对 Windows 操作系统对 COM 物理串口的排他性排它锁机制进行了开创性重构：
- **本地回环 IPC Bridge（`DesktopBridgeServer`）**：
  - 桌面应用启动时自动在 `127.0.0.1:0` 动态绑定轻量级 Desktop Bridge Server，并将端口与 PID 写入 `%TEMP%/ai-hil-serial-bridge.json`；
- **透明透明转发与数据双向共享（`DesktopBridgeClient`）**：
  - 当外部 AI Agent（如 Claude / Codex / Antigravity 等独立 MCP 客户端）调用串口工具时，优先检测桌面 Bridge；
  - 若桌面端在线，所有打开、发送、读取请求透明由桌面端底层会话承载，彻底告别 Windows `AccessDenied` 端口冲突；
  - 外部 AI 写入数据在 Vue 串口终端实时回显，外部 AI 也能即刻读取到真实设备的最新接收数据；
- **优雅离线 Fallback**：
  - 桌面端未启动或关闭时，MCP 守护进程自动平滑回退为原生独立 `pyserial` 驱动，保证无头模式（Headless）与 CLI 自动化依然正常工作。

---

### 4. 自动化测试与工程质量保障
- 新增 `scripts/test_mcp_integrated_capabilities.py`：端到端验证 MCP stdio 协议生命周期、工具注册清单、Desktop Bridge 资源共享与通信隔离；
- 通过 Node.js 前端规则回归（33 项全部 PASS）与 Rust 后端单元测试（11 项全部 PASS）。
