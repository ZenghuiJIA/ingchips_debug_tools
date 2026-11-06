# AI-HIL Debugger v1.3.2 Release Notes

## 🛠️ 工业级 Modbus 双模调试控制台与从站仿真全面重构

本版本重点落地了 **串口 Modbus 工业级调试控制台重构** 与 **生命周期进程管理深度加固**。

---

### 1. 全功能码与端序转换引擎
- **全功能码支持**：
  - `01` (Read Coils)、`02` (Read Discrete Inputs)
  - `03` (Read Holding Registers)、`04` (Read Input Registers)
  - `05` (Write Single Coil)、`06` (Write Single Register)
  - `15 / 0x0F` (Write Multiple Coils)、`16 / 0x10` (Write Multiple Registers)
- **4 大工控字端序适配**：
  - `AB CD` (标准大端 Big-Endian)
  - `CD AB` (小端字交换 Mid-Little，工控与国产/日系传感器标配)
  - `BA DC` (大端字节交换 Mid-Big)
  - `DC BA` (纯小端 Little-Endian / Intel)
- **丰富数据格式展示**：
  - 支持 `UInt16`、`Int16`、`UInt32`、`Int32`、`Float32 (IEEE-754单精度浮点)`、`HEX`、`Binary (16位位域高亮)`、`ASCII (字符文本)` 动态计算切换。

---

### 2. 主站控制台 (Master) 与从站仿真 (Slave) 双角色
- **Master 模式**：
  - 单次触发与周期性后台连续轮询（50ms~ 步进）；
  - **线圈状态卡片**：绿色/灰色指示灯实时显示线圈开关状态，一键点击反转发送 05 指令；
  - **寄存器即点即改**：双击数值单元格弹出内联编辑，修改后按回车即时触发 06 单寄存器写入；
- **Slave 模式 (从站仿真器)**：
  - 上位机可作为独立 Modbus Slave 设备，自定义从机 ID；
  - 自动响应来自外部下位机/主板/PLC 的 01/02/03/04/05/06/0F/10 读写请求；
  - 界面提供仿真寄存器表与线圈表，随时修改点位值供下位机读取。

---

### 3. 通信可靠性与报文流水
- **防粘包/拆包帧重组引擎**：
  - RTU 模式采用 25ms 静默间隔防抖自动切分完整帧；
  - ASCII 模式基于 `:` 与 `\r\n` 自动定界完整报文，彻底解决低波特率或 USB 串口拆包导致的 CRC 校验失效；
- **通信统计看板**：
  - 实时记录 TX 发送帧数、RX 接收成功帧数、异常/错误帧数与重置功能；
- **报文流水明细 (Traffic Trace Log)**：
  - 底部可折叠实时流水记录，清晰展示精确到毫秒的时间戳、方向、Raw Hex 与报文语义分析。

---

### 4. 守护进程生命周期与防孤儿加固
- 解决 PyInstaller 单文件双进程脱钩导致的后台残留问题；
- 引入父进程存活看门狗与原生进程树递归终结机制。
