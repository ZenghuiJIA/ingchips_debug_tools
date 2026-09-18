# Release v1.0.0 (2026-09-18)

AI-HIL 嵌入式硬件在环（Hardware-in-the-Loop）测试与调试终端正式发布 **v1.0.0** 版本！

本项目基于 **Tauri v2 (Rust)** 与 **Vue 3 + TailwindCSS** 构建，提供极速、安全、低内存消耗（空载常驻物理内存仅 ~26MB）的嵌入式设备交互与自动化调试平台。

---

## 🌟 核心新特性与重大更新 (What's New)

### 1. 🌐 标准 MCP (Model Context Protocol) 原生生态全覆盖
- **独立硬件守护进程**：提供免 Python 运行环境的独立守护进程二进制 `bin/hil-daemon-x86_64-pc-windows-msvc.exe`，原生支持标准 `stdio JSON-RPC 2.0`。
- **7 大嵌入式硬件调试工具 (MCP Tools)**：
  - `list_probes`: 实时扫描总线硬件探针（DAPLink / CMSIS-DAP / J-Link）。
  - `read_memory`: 物理内存及外设寄存器 16/32 位字节流与 HEX Dump 抓取。
  - `write_memory`: 32 位整型物理地址免编译实时注入与在线调参。
  - `read_core_registers`: ARM Cortex-M 核心寄存器（R0-R12, SP, LR, PC, xPSR, MSP, PSP）拉取。
  - `diagnose_hardfault`: Cortex-M SCB 故障状态寄存器（CFSR/HFSR/BFAR/MMFAR）全自动位域深度解析。
  - `flash_firmware`: 通过 SWD 协议自动擦除并烧录 `.bin` / `.hex` / `.elf` 固件。
  - `reset_target`: 目标硬件普通复位或挂起复位 (Reset & Halt)。
- **全 Agent 生态一键配置与热部署**：
  - 自动注册到 **CCSwitch** (`~/.cc-switch/cc-switch.db`)
  - 自动注册到 **DeepSeek Harness** (`~/.ohdsh/profiles/desktop/cordis.patch.yml` & `web/cordis.patch.yml`)
  - 自动注册到 **Claude Code** (`~/.claude.json`)
  - 自动注册到 **Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`)
  - 自动注册到 **Cursor / Windsurf** (`mcp.json`)
  - 自动注册到 **OpenAI Codex** (`~/.codex/config.toml`)
  - 自动注册到 **OpenCode** (`~/.config/opencode/opencode.json`)
  - 自动注册到 **Gemini / Antigravity CLI** (`~/.gemini/config/mcp_config.json`)
- **防重复安装机制**：升级一键安装脚本（`install_mcp.bat` / `install_skill.bat`），具备全路径与配置指纹比对，已安装项目自动跳过，绝无冗余备份或重复覆盖。

### 2. 🧠 全局通用 Skill 与 CC Switch 技能空间深度整合
- 部署并同步 `embedded-hil-debugger` Skill 至通用技能库目录 `~/.agents/skills/embedded-hil-debugger/`。
- 自动同步至 DeepSeek Harness (`~/.ohdsh/skills/`) 与 Antigravity 全局技能空间，赋予大模型自动排查 HardFault、烧录固件及外设寄存器分析的专家能力。

### 3. 🔌 智能串口支持与硬件时序安全防护
- **多类型设备自动识别**：
  - ⚡ `[DAPLink]` (CMSIS-DAP 虚拟串口)
  - 🔗 `[J-Link CDC]` (SEGGER CDC 虚拟串口)
  - 🔌 `[通用串口]` (CH340 / CP210x / FTDI / PL2303 / USB CDC 等)
- **硬件时序安全隔离**：
  - 严格限制仅 DAPLink 支持 RTS/DTR 硬件复位脉冲（Normal Reset 50ms 与 ISP Bootloader 500ms 建立电平）；
  - J-Link CDC 及其他通用串口设备严格拦截一键 BOOT 与复位操作，界面与底层双重互锁，杜绝因引脚悬空或电平误触导致的硬件故障。

### 4. 📈 60 FPS 硬件加速串口实时示波器 (Telemetry)
- 支持 CSV 流、键值对（`roll:12.3`）、JSON 自动识别解析。
- 自适应 Y 轴缩放、十字线 HUD 悬浮测量与 CSV 一键导出。
- 内置 50Hz 虚拟仿真信号发生器，支持无实物脱机算法与波形验证。

### 5. 🛡️ 进程自愈与 GUI 管道健壮性升级
- Rust 后端新增子进程存活实时轮询 (`child.try_wait()`)，若底层守护进程因环境变动退出，上位机下发指令时自动零延迟自愈拉起。
- 优化 Windows GUI 子系统下的管道与标准错误流重定向，彻底杜绝管道溢出或无控制台句柄造成的阻塞。

---

## 📦 发布包信息 (Assets)

| 文件名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `AI-HIL-Debugger-v1.0.0-windows-x64.zip` | 绿色归档包 (106 MB) | 解压即用，内含主程序、MCP守护进程、安装脚本与文档 |
| `release/AI-HIL-Debugger-v1.0.0-windows-x64/` | 解包目录 | 便携运行目录，支持 `start.bat` 一键启动 |

---

## 🚀 快速使用说明

1. **解压运行**：双击 `start.bat` 或 `AI-HIL-Debugger.exe`。
2. **连接 AI Agent**：双击 `install_mcp.bat` 和 `install_skill.bat`，几秒内即可让系统上的所有 AI Agent 具备嵌入式 HIL 调试能力。
