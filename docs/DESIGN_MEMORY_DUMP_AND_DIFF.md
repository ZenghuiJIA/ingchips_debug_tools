# 通用 Flash / RAM 内存直接转储与差异对比 (Hex Dump & Diff) 详细设计方案

## 1. 方案背景与目标

在嵌入式开发、量产测试、售后分析与固件逆向排查中，经常遇到以下高频痛点：
1. **校准参数 / NVRAM 意外丢失或损坏**：无法快速确认 Flash 某固定存储扇区（如 `0x020FC000`）的内容是否被擦除或写坏。
2. **OTA 差分升级校验**：升级前后需要比对实际烧录到芯片各 Bank 的数据与本地生成 bin 文件是否逐字节一致。
3. **内存泄漏与变量篡改排查**：在 MCU 跑飞或出现 HardFault 前后，缺乏直观的“内存快照对比（Snapshot Diff）”机制，无法看清到底哪些全局变量或堆栈区发生了变动。

### 核心目标
- **高性能全块转储 (High-speed Memory Dump)**：利用 SWD 高速 DAP 批量块读取协议，将 Flash / RAM 任意范围转储并一键保存为 `.bin`、`.hex` 或 `.srec` 文件。
- **双向快照对比 (Memory Snapshot Diff)**：支持“运行前拍摄快照 A” -> “运行后拍摄快照 B”，秒级计算并高亮显示差异字节（增加、删除、修改）。
- **设备内存 vs 本地文件比对 (Device vs File Diff)**：直接将芯片内部 Flash 实时读出的内容与本地待烧录的 `.bin` / `.hex` 固件进行差异比对，支持标记未编程区（0xFF）。

---

## 2. 系统架构设计

```mermaid
flowchart TD
    subgraph Target MCU
        RAM["SRAM 存储区 (0x20000000)"]
        FLASH["Internal Flash 存储区 (0x02000000)"]
    end

    subgraph Rust 后端 (DAP Transfer & Diff Engine)
        SWD["SWD 硬件调试通道 (CMSIS-DAP / J-Link)"] -->|块读请求 Block Read 32-bit| RAM
        SWD -->|块读请求 Block Read 32-bit| FLASH
        SWD --> Buffer["原始字节流缓存 (Raw Buffer)"]
        Buffer --> Exporter["格式导出器 (.bin / .hex / .c array)"]
        Buffer --> Diff_Core["高速差异比对核心 (Diff Engine)"]
        LocalFile["本地固件文件 (.bin / .hex)"] --> FileParser["IntelHex / Bin 解析器"]
        FileParser --> Diff_Core
    end

    subgraph 前端 UI (Vue 3)
        Diff_Core -->|增量差异索引| HexDiffView["双栏十六进制对比视图 (Dual-pane Hex Diff)"]
        HexDiffView --> DiffNav["差异块快速跳转导航器 (Prev / Next)"]
        HexDiffView --> MiniMap["全范围差异缩略图 (Minimap)"]
        Exporter --> FileDownload["本地文件保存对话框"]
    end
```

---

## 3. 核心功能设计

### 3.1 高速内存转储 (Dump Engine)
- **参数输入**：
  - 起始地址（支持十六进制输入，如 `0x02000000`）；
  - 长度大小（支持输入字节数或快捷选项：4KB, 16KB, 64KB, 256KB, 1MB, 2MB）；
  - 访问宽度：32-bit (默认高速字对齐传输), 16-bit, 8-bit。
- **传输优化机制**：
  - Rust 端使用 `probe-rs` / CMSIS-DAP 批处理流水线传输指令（`read_block_32`），单次传输块大小自动适配（1024 字节/批），读取吞吐量达到 300KB/s ~ 800KB/s。
  - 进度条实时反馈：显示已读取字节数、传输百分比、平均读取速度。
- **导出格式支持**：
  - **Raw Binary (.bin)**：纯二进制镜像。
  - **Intel HEX (.hex)**：标准 HEX 格式，包含正确的高位扩展线性地址记录（Record Type 04）。
  - **C 语言头文件 (.h)**：生成 `const uint8_t dump_data[] = { 0xAA, ... };` 便于直接嵌入工程回放验证。

### 3.2 内存差异对比 (Memory Diff)
提供两种比对模式：
1. **模式一：芯片快照 A vs 芯片快照 B (Snapshot vs Snapshot)**
   - 步骤 1：点击“记录快照 A”（记录当前内存状态并给打上时间标签）；
   - 步骤 2：对目标板进行特定操作（例如按下按键、发送通信指令、等待一段时间）；
   - 步骤 3：点击“抓取快照 B 并比对”；
   - 结果：系统立即生成内存 Diff 表。
2. **模式二：芯片实际数据 vs 本地文件 (Target Flash vs Local File)**
   - 选择本地 `.bin` 或 `.hex` 文件，系统提取出该文件对应的地址段；
   - 上位机自动通过 SWD 读取芯片对应地址段的数据进行比对；
   - 智能识别“已烧录区域”与“未使用的空白区域 (0xFF)”。

---

## 4. UI 界面与交互细节

### 4.1 双栏十六进制对比器 (Dual-pane Hex Diff View)
- 采用左右双栏（Left: Source A, Right: Source B）标准 Hex 视图：
  - 偏移地址列（Offset）：`0x02001000`, `0x02001010`...
  - 十六进制字节区：16 个字节一组；
  - ASCII 字符区：对应的可见字符。
- **高亮着色规则**：
  - **绿色背景**：内容完全一致；
  - **黄色/橙色背景**：字节值修改变动（如快照 A 是 `0x00`，快照 B 是 `0x5A`）；
  - **红色背景**：一侧存在数据，另一侧为空白或未对齐缺失；
  - **灰色字体**：全 0xFF（空白 Flash）弱化显示，减少视觉干扰。
- **交互功能**：
  - **双向联动滚动 (Synchronized Scrolling)**：左右两栏滚动条严格同频对齐；
  - **差异导航浮动条**：提供 `[上一处差异 (Ctrl+↑)]` 和 `[下一处差异 (Ctrl+↓)]`，点击后瞬间平滑滚动至差异字节；
  - **统计栏 Summary**：显示 `总比对字节数: 65,536 B`、`差异字节数: 42 B (0.06%)`、`差异连续块: 3 处`。

---

## 5. 后端 IPC 接口设计

```rust
// Rust Tauri Commands
#[tauri::command]
async fn dump_memory_range(
    probe_index: usize,
    address: u32,
    length: usize,
    export_path: Option<String>,
) -> Result<Vec<u8>, String>;

#[tauri::command]
async fn compare_memory_with_file(
    probe_index: usize,
    address: u32,
    file_path: String,
) -> Result<DiffResultSummary, String>;
```

### 数据结构：`DiffResultSummary`
```typescript
export interface DiffBlock {
  offset: number;          // 相对起始偏移
  address: number;         // 绝对物理地址
  length: number;          // 差异块长度
  data_a: number[];        // 源 A 字节序列
  data_b: number[];        // 源 B 字节序列
}

export interface DiffResultSummary {
  start_address: number;
  total_length: number;
  diff_byte_count: number;
  diff_blocks: DiffBlock[];
}
```

---

## 6. MCP AI 自动化集成工具

- `dump_memory_to_file`: 输入起始地址与大小，自动读出并保存至磁盘临时目录供 AI 进一步解析。
- `diff_memory_against_file`: AI 可调用该工具验证当前板子 Flash 是否已经成功写入指定版本固件。
- `explain_memory_corruption`: 当发现配置区异常时，AI 分析差异偏移量，结合符号表判断是哪一个结构体成员发生了溢出覆盖。
