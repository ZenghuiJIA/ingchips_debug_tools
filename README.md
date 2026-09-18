# AI-HIL 嵌入式硬件在环(HIL)测试与调试终端

本项目是一款基于 **Tauri v2 (Rust)** 与 **Vue 3 + Vite + TailwindCSS** 构建的现代化、极速、低内存消耗的 AI 驱动嵌入式调试工具。

---

## 🎯 核心特性清单

1. **硬件串口支持与智能分类安全控制**：
   - 支持全类型串口设备：自动识别 **DAPLink** (`⚡ [DAPLink]`)、**J-Link CDC 虚拟串口** (`🔗 [J-Link CDC]`) 以及 **通用串口设备** (`🔌 [通用串口]`, 包括 CH340, CP210x, FTDI, PL2303, USB CDC 等)。
   - 基于 Rust `serialport` crate 实现底层操作系统直连，支持 9600 至 **921600 高波特率**无损通信。
   - **硬件时序安全隔离（仅 DAPLink 支持硬件复位）**：
     - **普通复位 (Normal Reset)**：RTS=0 $\to$ 延迟 50ms $\to$ DTR 脉冲 100ms (复位低电平有效) $\to$ 释放 DTR。
     - **引导模式 (ISP Bootloader Reset)**：RTS=1 (拉高进入Boot) $\to$ 稳定等待 **500ms** $\to$ DTR 脉冲 100ms (拉低复位) $\to$ 释放 DTR。
     - **安全限制**：由于仅 DAPLink 具备标准 HIL RTS/DTR 硬件引脚接线，**J-Link CDC 及其他通用串口设备不支持一键进入 BOOT 和硬件复位功能**。前端界面将自动禁用复位按键并给予提示，Rust 后端同样实施严格的硬件校验与状态拦截。

2. **串口命令组与多格式编码**：
   - 支持为每条命令配置独立的换行符与格式：`+CRLF (\r\n)`、`+LF (\n)`、`+CR (\r)`、`RAW (无换行)`、`HEX (十六进制字节流)`。
   - 支持组内**单条命令一键单独发送**，以及底部常驻快捷指令胶囊栏一键单发。
   - 支持批量顺序流水线执行（支持指令间隔延时配置与循环执行）。

3. **📈 串口实时波形与虚拟示波器 (Serial Telemetry)**：
   - 自动识别多种串口流协议：**CSV 格式**（`12.3, 45.6, -7.8`）、**键值对**（`roll:12.3, pitch:45.6`）、**JSON 对象**，自动过滤非数据纯文本日志。
   - 60 FPS 硬件加速 Canvas 2D 渲染引擎，支持自适应 Y 轴缩放与固定量程模式。
   - 通道状态指示栏：显示各通道极值 `[Min ~ Max]`、实时数值、显隐切换；支持十字线光标 HUD 悬浮测量与 CSV 一键导出。
   - **🎲 内置 50Hz 虚拟仿真信号发生器**：一键注入多通道正弦/余弦/三角波，无需物理板卡即可完整回归验证。

4. **⚡ 串口智能触发器与自动应答机 (Smart RX Triggers)**：
   - 监听串口数据流，支持 `包含匹配 (Contains)` 与 `正则表达式 (Regex)`。
   - 命中后自动在指定延时后回传设定命令（支持配置换行格式）。
   - 支持 `持续触发` 与 `仅单次触发`（防死循环），界面实时统计命中次数并记录触发时间。

5. **SWD 固件烧录与硬件在环调试 (PyOCD 驱动 DAPLink & J-Link)**：
   - 探针驱动全面基于 **PyOCD**（集成 CMSIS-DAP 与 J-Link `pylink` 原生驱动链路）。
   - 自动扫描总线上连接的 **DAPLink / CMSIS-DAP / J-Link** 硬件探针，并在烧录器与 HardFault 智能诊断器中提供自由切换选择。
   - 支持通过 CMSIS-Pack 对 STM32、RP2040、NRF52、通用 Cortex-M 进行一键烧录（`.bin` / `.hex` / `.elf`）。
   - 提供 SWD 硬件复位与复位并挂起 (Reset & Halt)。

6. **HardFault 寄存器与现场智能诊断**：
   - 一键抓取 ARM Cortex-M 核心寄存器（`R0-R12`, `SP`, `LR`, `PC`, `xPSR`, `MSP`, `PSP`）。
   - 自动解析系统控制块 (SCB) 故障寄存器：
     - **CFSR**: 自动拆解并高亮 `PRECISERR`, `IMPRECISERR`, `BFARVALID`, `INVSTATE`, `DIVBYZERO`, `UNALIGNED`, `NOCP` 等。
     - **HFSR**: 诊断 `FORCED` 强制硬故障及 `DEBUGEVT`。
     - **BFAR** / **MMFAR**: 捕获触发崩溃的物理内存地址。

7. **原生 MCP (Model Context Protocol) 协议与全 Agent 支持**：
   - 独立的 Python 守护进程充当 **MCP Server**，基于 `stdio JSON-RPC 2.0`。
   - 提供 7 大核心硬件 MCP Tools：`list_probes`, `read_core_registers`, `read_memory`, `write_memory`, `flash_firmware`, `reset_target`, `diagnose_hardfault`。
   - 详情参见：[`mcp/README.md`](./mcp/README.md)。

8. **极致性能与内存控制**：
   - **空载常驻物理内存 (RSS)**：实测仅 **~25.8 MB**（严格远低于 100MB 目标）！
   - Windows 平台使用 **Win32 Job Object**，主程序退出时内核自动级联销毁底层子进程，杜绝端口占用。

---

## 🛠️ 快速上手与使用

### 1. 启动调试工具
直接双击运行根目录下的：
* **`start.bat`** (推荐，自动清理旧僵尸进程并启动桌面程序)
* 或直接运行 `AI-HIL-Debugger.exe`

### 2. 一键安装 MCP 服务到系统所有 AI Agent
双击运行根目录下的：
```cmd
install_mcp.bat
```
或执行：
```cmd
python scripts/deploy_mcp_to_agents.py
```
该脚本会自动检测并注册 MCP 服务到（具备幂等检测，已有配置自动跳过，不重复安装）：
- **CCSwitch** (`~/.cc-switch/cc-switch.db`)
- **DeepSeek Harness** (`~/.ohdsh/profiles/desktop/cordis.patch.yml` 与 `web/cordis.patch.yml`)
- **Claude Code** (`~/.claude.json`)
- **Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`)
- **Cursor / Windsurf** (`mcp.json`)
- **OpenAI Codex** (`~/.codex/config.toml`)
- **OpenCode** (`~/.config/opencode/opencode.json`)
- **Gemini / Antigravity CLI** (`~/.gemini/config/mcp_config.json`)

### 3. 一键安装 AI Agent 技能 (Skill)
双击运行根目录下的：
```cmd
install_skill.bat
```
或执行：
```cmd
python scripts/install_skill.py
```
该脚本会自动校验版本一致性，安全部署且**不重复覆盖**已有相同 Skill：
- **CC Switch 全局通用技能库** (`~/.agents/skills/embedded-hil-debugger/`)
- **DeepSeek Harness 全局技能库** (`~/.ohdsh/skills/embedded-hil-debugger/`)
- **Antigravity / Gemini CLI 技能库** (`~/.gemini/antigravity-cli/skills/` & `~/.gemini/config/skills/`)
- **Claude Code 技能库** (`~/.claude/skills/`)
- **本地工程技能空间** (`.agents/skills/`)
- 自动向 CC Switch 数据库登记同步。

---

## 🧠 AI Skill 与 MCP 协同说明

### 什么时候调用 MCP？
* **遇到死机/HardFault**：AI 调用 `diagnose_hardfault` 提取寄存器现场，结合 `PC` 与 `BFAR` 给出根本原因排查建议；
* **固件烧录需求**：AI 调用 `flash_firmware(file_path=...)` 并调用 `reset_target` 引导运行；
* **外设状态排错**：AI 调用 `read_memory(address=..., count=...)` 实时拉取 GPIO/UART/DMA 外设寄存器；
* **免编译修改参数**：AI 调用 `write_memory` 直接修改内存变量或外设寄存器。

更多工具规范与示例，请阅读 [`skills/embedded-hil-debugger/SKILL.md`](./skills/embedded-hil-debugger/SKILL.md)。

---

## 📦 开发者编译与打包

```powershell
# 1. 重新编译独立 MCP 守护进程与自测流水线 (当修改了 daemon_entry.py 时)
.\build_daemon.bat

# 2. 前端与桌面端完整构建
.\build.bat

# 3. 自动化协议与功能回归测试
node scripts/verify_features_regression.js
```

---

## 📄 开源许可证 (License)

本项目遵循 [Apache License 2.0](LICENSE) 开源许可证。
您可以自由商用、修改与分发，详情请阅读根目录下的 [LICENSE](LICENSE) 协议文本。
