# Embedded HIL Debugger - MCP (Model Context Protocol) 服务使用指南

本服务为大语言模型（LLM）与各类 AI 编码助手（如 Claude Code, Cursor, Windsurf, CCSwitch, Antigravity, OpenCode, Codex）提供无侵入式的**嵌入式硬件在环（HIL）控制与调试能力**。

通过 Rust runtime、Tauri UI bridge 和受限 Python probe worker 共享同一套资源状态，AI 助手可以读取 UI 已采集的串口/调试快照，并在明确获得资源所有权后执行固件烧录、寄存器读写、内核复位以及 Cortex-M 单片机死机硬故障（HardFault）诊断。MCP 默认不会关闭、发送或复位 UI 正在使用的串口。

---

## 1. 核心架构与运行方式

* **通信协议**：基于标准 **JSON-RPC 2.0** over `stdio`（标准输入输出）；
* **独立运行**：支持两种运行形态：
  1. **独立二进制发布形态（推荐）**：`bin/hil-daemon-x86_64-pc-windows-msvc.exe --mode stdio-mcp`（无需目标机安装 Python 环境）；
  2. **Python 源码形态**：`python src-tauri/daemon/daemon_entry.py --mode stdio-mcp`（需依赖 `pyocd`、`pyserial`）。
* **物理依赖**：USB 连接的 DAPLink / CMSIS-DAP 调试器（支持 ARM Cortex-M0/M3/M4/M7/M33 全系，如 STM32, RP2040, NRF52, ING918 等）。

---

## 2. 核心 MCP 工具清单 (MCP Tools Reference)

| MCP Tool 工具名称 | 核心功能简述 | 输入参数 (Parameters) | 常见使用时机 |
| :--- | :--- | :--- | :--- |
| **`list_probes`** | 列出所有物理连接的调试器探针 | 无 | 确认 DAPLink 连接状态与唯一 ID |
| **`read_core_registers`** | 读取 CPU 核心与 SCB 寄存器 | `probe_id`*(可选)*, `target_override`*(可选)* | 检查 `R0-R12`、`PC`、`LR`、`SP` 及中断状态 |
| **`read_memory`** | 读取目标芯片内存 / 外设地址空间 | `address`*(必填)*, `count`*(默认64)* | 查外设寄存器 (如 GPIO, UART, DMA) 或 RAM |
| **`write_memory`** | 写入 32 位数值至指定物理地址 | `address`*(必填)*, `value`*(必填)* | 在线修改外设寄存器配置、免编译调参 |
| **`flash_firmware`** | 通过 SWD 擦除并烧录固件到 Flash | `file_path`*(必填)*, `target_override`*(可选)* | 自动化烧录 `.bin` / `.hex` / `.elf` 镜像 |
| **`reset_target`** | 硬件/软件复位目标单片机 | `halt`*(布尔值, 默认 false)* | 固件烧录后重启运行，或挂起 CPU 检查初始态 |
| **`diagnose_hardfault`** | **【核心诊断】** 自动化提取 HardFault 现场并输出位域根因分析 | `probe_id`*(可选)*, `target_override`*(可选)* | 单片机死机、卡死、进入 HardFault_Handler |
| **`get_ui_state`** | 读取 UI 持有的串口会话、捕获游标和 MCP 权限 | 无 | 任何硬件动作前确认资源所有权 |
| **`get_serial_snapshot`** | 按游标读取 UI 已采集的串口事件 | `port_name`*(可选)*, `after`, `limit` | 不抢占串口查看日志/响应 |
| **`list_serial_ports`** | 枚举系统可用串口及连接状态 | 无 | 查看当前物理/虚拟串口，识别默认端口 |
| **`open_serial_port`** | 以 observe 模式观察已有 UI 会话；独立 daemon 可显式 control | `port_name`*(必填)*, `access_mode`*(默认 observe)* | 建立或共享指定串口通信会话 |
| **`close_serial_port`** | 请求关闭串口；UI 持有时返回 `resource_busy` | `port_name`*(单串口时可选)* | 仅在资源归属明确时使用 |
| **`send_serial_data`** | 向串口发送数据；UI 持有时拒绝抢占 | `data`*(必填)*, `port_name`*(可选)*, `is_hex` | 资源已释放后的控制操作 |
| **`reset_serial`** | 请求 RTS/DTR 复位；UI 持有时拒绝抢占 | `port_name`*(可选)*, `sequence` | 资源已释放后的复位操作 |
| **`read_serial_data`** | 读取共享捕获；默认不推进 UI 缓冲 | `port_name`*(可选)*, `format`*(text/hex)*, `clear_buffer` | 接收单片机输出日志、AT响应或二进制流 |

---

## 3. 一键快速部署 (One-Click Installation)

在项目根目录中，直接双击运行：

```cmd
install_mcp.bat
```

脚本将自动探测您系统上已安装的各种 Agent 工具，并自动完成注册与热配置：
* ✅ **CCSwitch**：自动注入 SQLite 数据库 `~/.cc-switch/cc-switch.db`，并打上 `embedded`、`hil`、`swd` 标签；
* ✅ **DeepSeek Harness**：自动注入 `~/.ohdsh/profiles/desktop/cordis.patch.yml` 与 `web/cordis.patch.yml`；
* ✅ **Claude Code**：自动配置 `~/.claude.json` 中的 `mcpServers`；
* ✅ **Claude Desktop**：自动配置 `%APPDATA%\Claude\claude_desktop_config.json`；
* ✅ **Cursor / Windsurf**：兼容标准 `mcp.json`；
* ✅ **OpenAI Codex**：自动配置 `~/.codex/config.toml`；
* ✅ **OpenCode**：自动配置 `~/.config/opencode/opencode.json`；
* ✅ **Gemini / Antigravity CLI**：自动配置 `~/.gemini/config/mcp_config.json`。

> 💡 **防重复安装保障**：安装脚本具备完全的幂等性校验机制，若对应 Agent 已注册该 MCP 服务且配置一致，将自动跳过，绝不产生重复写入或冗余备份。

---

## 4. 手动集成配置指南 (Manual Configuration)

若需手动配置某款 AI 客户端，请参考以下配置片段：

### 4.1 Claude Desktop (`claude_desktop_config.json`)
文件路径：`%APPDATA%\Claude\claude_desktop_config.json`
```json
{
  "mcpServers": {
    "embedded-hil-debugger": {
      "command": "C:\\ming\\source\\tools\\test_tools\\bin\\hil-daemon-x86_64-pc-windows-msvc.exe",
      "args": ["--mode", "stdio-mcp"]
    }
  }
}
```

### 4.2 Claude Code (`.claude.json`)
文件路径：`~/.claude.json`
```json
{
  "mcpServers": {
    "embedded-hil-debugger": {
      "command": "C:\\ming\\source\\tools\\test_tools\\bin\\hil-daemon-x86_64-pc-windows-msvc.exe",
      "args": ["--mode", "stdio-mcp"]
    }
  }
}
```

### 4.3 Cursor / Windsurf (`mcp.json`)
文件路径：项目根目录 `.cursor/mcp.json` 或用户全局 `~/.cursor/mcp.json`
```json
{
  "mcpServers": {
    "embedded-hil-debugger": {
      "command": "C:\\ming\\source\\tools\\test_tools\\bin\\hil-daemon-x86_64-pc-windows-msvc.exe",
      "args": ["--mode", "stdio-mcp"]
    }
  }
}
```

### 4.4 OpenAI Codex (`config.toml`)
文件路径：`~/.codex/config.toml`
```toml
[mcp_servers.embedded_hil_debugger]
command = 'C:\ming\source\tools\test_tools\bin\hil-daemon-x86_64-pc-windows-msvc.exe'
args = ["--mode", "stdio-mcp"]
```

### 4.5 Gemini / Antigravity CLI (`mcp_config.json`)
文件路径：`~/.gemini/config/mcp_config.json`
```json
{
  "mcpServers": {
    "embedded-hil-debugger": {
      "command": "C:\\ming\\source\\tools\\test_tools\\bin\\hil-daemon-x86_64-pc-windows-msvc.exe",
      "args": ["--mode", "stdio-mcp"]
    }
  }
}
```

---

## 5. AI Skill 联动与使用场景

为了让大模型在最恰当的时机自动调用这些 MCP 硬件工具，我们提供了专用的 **`embedded-hil-debugger` Skill**。

### 5.1 安装 Skill
运行根目录下的安装脚本：
```cmd
install_skill.bat
```
或通过 Python 执行：
```cmd
python scripts/install_skill.py
```
该脚本会将标准 Skill 文件安全部署至各大 AI Agent 技能空间（若检测到已有相同版本的 Skill 则自动跳过，绝不重复写入）：
1. `~/.agents/skills/embedded-hil-debugger/`（CC Switch 管理的通用全局 Skill 目录）
2. `~/.ohdsh/skills/embedded-hil-debugger/`（DeepSeek Harness 全局 Skill 目录）
3. `~/.gemini/antigravity-cli/skills/embedded-hil-debugger/`（Antigravity CLI 默认技能目录）
4. `~/.gemini/config/skills/embedded-hil-debugger/`（Gemini CLI 全局配置目录）
5. `~/.claude/skills/embedded-hil-debugger/`（Claude Code 默认技能目录）
6. 本地工程 `.agents/skills/embedded-hil-debugger/`（项目工作区技能目录）
7. 自动同步登记至 CC Switch 本地数据库 (`~/.cc-switch/cc-switch.db`) 中的 `skills` 表。

### 5.2 什么时候调用 MCP
1. **死机排障**：当用户说“程序死在 HardFault_Handler 里了”、“单片机跑飞了”，AI 自动触发 `diagnose_hardfault` 提取 `CFSR` 位域，结合 `PC` 寄存器指出是空指针越界、总线错误还是未使能时钟；
2. **自动化烧录**：当编译出 `.bin`/`.hex`/`.elf` 时，AI 自动调用 `flash_firmware` 并触发 `reset_target`；
3. **外设调测**：当排查某个 GPIO 或 UART 为何不工作时，AI 自动调用 `read_memory` 抓取外设控制寄存器，向用户解释位状态（如 `USART_CR1->UE` 是否为 1）；
4. **动态调参**：AI 可通过 `write_memory` 直接修改内存变量或外设寄存器，免除反复烧录的繁琐步骤。
