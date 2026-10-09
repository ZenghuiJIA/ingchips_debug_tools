# BLE / 射频调试控制台与 HCI 报文解析 (BLE RF Console & HCI Packet Analyzer) 详细设计方案

## 1. 方案背景与目标

INGChips 芯片（如 ING9187/ING9188/ING9168/ING9180 等）以及市场上主流的无线 MCU，其主要应用场景均为低功耗蓝牙 (BLE) 或 2.4GHz 私有无线通信。
在射频研发、天线调优、射频法规认证（SRRC / FCC / CE）以及蓝牙协议栈调试中，开发者普遍面临以下困扰：
1. **RF DTM (Direct Test Mode) 测试流程繁琐**：产线测试或认证实验室需要频繁发送特定的 2 字节 DTM 指令（如单载波发射、调制包发射、接收灵敏度统计），没有专用的直观控制台，容易输错十六进制命令。
2. **HCI 原始串口报文缺乏结构化解析**：协议栈通常通过串口输出 HCI (Host Controller Interface) 数据流。普通的串口终端只能看到一长串乱码或十六进制字节（如 `04 3E 13 02 01 00 ...`），无法直观识别出是哪个设备的广播、RSSI 信号强度是多少、广播包内容是什么。

### 核心目标
- **一体化 BLE DTM 射频测试控制台**：图形化设置信道（0~39）、发射功率、数据包类型（PRBS9, 0x0F, 0x55 等）、包长度，一键启动发射/接收测试并实时统计误包率 (PER)。
- **实时 HCI 报文监视与协议树解码**：串口捕获 HCI 帧（HCI Command, HCI Event, ACL Data, Synchronous Data），自动高亮拆解事件头部与参数 Payload，特别针对 BLE 5.x 扩展广播与连接事件做深度格式化展示。
- **RSSI 信号强度走势监控**：解析广播包携带的 RSSI 字段，实时绘制信号衰减曲线，便于天线选型与产线距离标定。

---

## 2. 协议与底层基础

### 2.1 Bluetooth HCI 数据帧封装格式 (UART H4 Transport)
蓝牙标准 H4 协议通过单个指示符（Indicator 字节）定义报文类型：
| Indicator (1 Byte) | 报文类型 | 结构组成 |
| :--- | :--- | :--- |
| `0x01` | **HCI Command** | `Opcode (2B: OGF+OCF)` + `Param Length (1B)` + `Parameters (NB)` |
| `0x02` | **HCI ACL Data** | `Handle + PB + BC (2B)` + `Data Length (2B)` + `Data (NB)` |
| `0x04` | **HCI Event** | `Event Code (1B)` + `Param Length (1B)` + `Parameters (NB)` |

对于 BLE 而言，绝大多数事件以 `0x3E` (**HCI_LE_Meta_Event**) 输出，其第一个参数即为 **Sub-event Code**（如 `0x02` 为 LE Advertising Report，`0x0D` 为 LE Extended Advertising Report）。

### 2.2 Bluetooth DTM (Direct Test Mode) 控制规范
DTM 支持通过标准 2 字节 UART 指令（波特率通常为 115200 或 9600）控制芯片 PHY 层射频：
- **Reset**: `0x0000`
- **Receiver Test**: `0x01` + 频点 (0~39)
- **Transmitter Test**: `0x02` + 频点 + 长度 + 载荷模式
- **Test End**: `0x03` + 返回接收到的成功数据包数量

---

## 3. 系统架构与模块设计

```mermaid
flowchart TD
    subgraph Target BLE Device
        DUT["被测芯片 (ING918x / 无线 MCU)"]
    end

    DUT <-->|UART / H4 协议流| SerialEngine["Serial 通信核心"]

    subgraph 协议解析与业务逻辑 (Rust 后端)
        SerialEngine --> H4_Framer["H4 协议帧定界与重组器 (Framer)"]
        H4_Framer --> Hci_Decoder["HCI 协议解码器 (Decoder)"]
        Hci_Decoder --> Adv_Parser["BLE 广播数据包解析器 (Adv Parser)"]
        Hci_Decoder --> Dtm_Controller["DTM 射频测试状态机 (State Machine)"]
    end

    subgraph 前端交互 (Vue 3)
        Adv_Parser --> Adv_Scanner_View["广播扫描列表与 RSSI 监控"]
        Hci_Decoder --> Hci_Packet_Inspector["HCI 报文追踪日志 (Wireshark 级)"]
        Dtm_Controller --> Dtm_Console_View["DTM 射频控制面板 (Tx/Rx/Power)"]
    end
```

---

## 4. UI 界面与交互细节

### 4.1 HCI 报文追踪窗口 (HCI Packet Inspector)
- **类似 Wireshark 的三段式布局**：
  1. **顶部过滤器**：支持按类型过滤（`Commands` / `Events` / `ACL` / `LE Only`），按 MAC 地址或设备名过滤；
  2. **中部报文列表**：列展示序号、相对时间戳 (µs)、方向 (Tx/Rx)、Packet Type、Event/Opcode 名称、摘要 Summary（例如：`LE Adv Report: [C4:D3:21:00:11:22] RSSI: -54 dBm, Name: "ING_BLE_DEVICE"`）；
  3. **底部树状详情与原始 Hex**：展开可查看每个字段的含义（如 Access Address、Channel Index、PDU Type 等）。
- **一键导出 PCAP**：可将捕获的报文导出为标准 `.pcap` 文件，直接导入 Wireshark 进行深入蓝牙协议栈分析。

### 4.2 BLE DTM 射频测试控制台 (DTM Console)
- **发射测试 (Tx Test)**：
  - **信道选择**：物理频点 0 ~ 39（对应 2402 MHz ~ 2480 MHz），标明广播信道 37、38、39；
  - **物理层 PHY**：1M PHY, 2M PHY, Coded S=8, Coded S=2；
  - **载荷类型**：PRBS9 (伪随机码), 10101010 序列, 11110000 序列, 单载波持续发射 (CW Single Carrier)；
  - **包长设置**：0 ~ 255 字节；
  - **发射功率设置**：-20dBm ~ +10dBm（针对 ING 芯片专有寄存器自动适配）。
- **接收测试 (Rx Test)**：
  - 设置监听信道与 PHY；
  - 启动后实时轮询统计：已接收数据包数量、丢包率 (PER %)、平均 RSSI。

---

## 5. 后端接口与 MCP 工具

### Tauri IPC Commands
- `ble_dtm_start_tx(params: DtmTxParams): Promise<void>`
- `ble_dtm_start_rx(params: DtmRxParams): Promise<void>`
- `ble_dtm_end_test(): Promise<DtmResult>`
- `ble_hci_start_capture(port_name: string): Promise<void>`
- `ble_hci_export_pcap(file_path: string): Promise<boolean>`

### AI / MCP 集成工具
- `ble_analyze_advertising_payload(raw_hex: string)`: AI 自动解析并指出广播包中是否缺少广播完整名称或 Manufacturer Data 格式是否合法。
- `ble_dtm_run_automated_rf_sweep()`: 自动化运行全频点（0, 19, 39）功率与频偏自动化扫频测试并输出合格报告。
