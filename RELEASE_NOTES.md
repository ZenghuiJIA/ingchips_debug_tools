# Release Notes: v1.2.0

## 🚀 AI-HIL Debugger v1.2.0 发布说明

### 🌟 核心亮点与重大更新

本版本重点落地了 **网络通信流 UI 交互**、**实时波形 120Hz 极速电竞级渲染与像素降采样**、**多 RTOS 智能状态机与现场探测**、**屏幕显存实时镜像**、**Modbus RTU/ASCII 双模引擎**，以及**全方位的上位机内存深度治理**。

---

### 1. 🌐 全新网络数据流通信交互 (TCP / UDP)
- **多协议网络会话创建**：在「打开新端口」对话框中新增独立网络通信流 Tab，支持三种主流网络数据源：
  - **TCP 客户端 (TCP Client)**：主动连接远程 MCU / 以太网转换模块 / 云端转发服务的 IP 与 Port；
  - **TCP 服务端 (TCP Server)**：在本地 IP（如 `0.0.0.0` 或 `127.0.0.1`）开启监听，自动接收远程客户端接入；
  - **UDP 广播/单播 (UDP Socket)**：实现无连接高速数据包的双向收发与广播。
- **全链路收发路由透明化**：
  - 会话标签页统一管理（如 `TCP-Client:192.168.1.100:8080`、`UDP:0.0.0.0:9000`）；
  - 自动复用所有终端高级特性：HEX 编解码展示、自动校验码追加（CRC16/LRC/Sum8）、自动应答触发器与 VT100 终端均无缝支持网络数据流；
  - 接收到的网络遥测数据自动并入全局硬件数据管道，可直接在示波器中实时绘图与数学测量。

---

### 2. ⚡ 实时波形示波器：120Hz 极速高刷与可选降采样展示
- **120 FPS 极速刷新率目标调度**：
  - 顶部工具栏增加 **「刷新率」** 选择器（`⚡ 120 FPS 极速高刷`、`VSync 屏幕原生`、`60 FPS 均衡`、`30 FPS 低功耗`）；
  - 结合微定时器与 `requestAnimationFrame`，满足高刷电竞屏与超高实时性要求，实现极限丝滑的波形追踪。
- **智能 Min-Max 像素分桶降采样 (Pixel Bucket Decimation)**：
  - 新增 **「降采样」** 选择器：`智能Min-Max分桶(极速推荐)`、`全量原始点`、`2倍`、`5倍`、`10倍` 降采样；
  - **像素级极值保真算法**：当采样点数达到 2,000 ~ 50,000+ 点时，自动提取每个像素列区间的最大值与最小值绘制极值线，**100% 真实保留异常脉冲与毛刺尖峰**，同时削减 80%~95% 的 Canvas 重复描边点数，渲染耗时压减至 $<1\text{ms}$，大数据量下稳定跑满 120 FPS。

---

### 3. 🧠 多 RTOS 线程/任务自动探测与异常状态机 (RTOS Tracer)
- **支持多主流实时操作系统**：
  - **FreeRTOS**（TCB 链表遍历、任务名、状态、栈高水位线与堆栈基址计算）；
  - **RT-Thread**（线程控制块遍历与调度器状态探测）；
  - **uC/OS-II & uC/OS-III**（OSTCBPrioTbl、就绪表与任务运行态解析）；
  - **RTX5**（CMSIS-RTOS2 任务控制块结构解析）；
  - **ThreadX**（tx_thread_created_ptr 线程链表解析）。
- **自动化 ELF/AXF 符号分析**：结合固件 ELF 符号表自动计算结构体偏移量，无需板端编写额外 Trace 代码即可窥探实时多任务。
- **入库全体系黄金测试样本集**：包含 Keil/IAR/GCC 生成的各 OS 固件样本（`test_fixtures/elf_demo/`），便于自动回归验证。

---

### 4. 🖥️ 屏幕显存实时镜像查看器 (LCD Screen Mirror)
- **显存实时映射读取**：通过 SWD 链路直接从 MCU 目标板的 Framebuffer 显存地址抓取字节流；
- **多像素格式自动解码**：支持 RGB565 (16-bit)、RGB888 (24-bit)、ARGB8888 (32-bit)、Monochrome 单色点阵；
- **镜像视图与旋转**：前端实时 Canvas 解码展示 MCU 当前屏幕显示内容，支持 0°/90°/180°/270° 旋转，并可一键保存高清截图。

---

### 5. 🛠️ 工业级 Modbus 双模扩展与从机仿真
- **RTU 与 ASCII 双模支持**：全面实现 Modbus RTU (CRC16 校验) 与 Modbus ASCII (冒号起始 + 换行结束 + LRC 纵向冗余校验)；
- **全功能码支持**：01/02 (读线圈/离散量)、03/04 (读保持/输入寄存器)、05/06 (写单线圈/单寄存器)、15/16 (写多线圈/多寄存器)；
- **内置从机仿真器 (Slave Simulator)**：可直接模拟从机设备响应主站查询，支持配置从机寄存器初值。

---

### 6. 🛡️ 上位机深度内存治理与生命周期资源回收
针对 Chromium WebView2 GPU 显存膨胀与长久运行内存泄漏问题，实施系统级优化：
1. **Edge WebView2 运行时参数硬核瘦身**：
   - 注入 `--disable-gpu-memory-buffer-compositor-resources` & `--gpu-memory-buffer-compositor-resources=1`，**根除 GPU 进程占用 300MB~500MB 显存的现象**；
   - 注入 `--js-flags=--max-old-space-size=256` 并关闭冗余音频/网络遥测子进程。
2. **Canvas 120Hz 空闲智能降频 (Idle Throttling)**：
   - 超过 1.5 秒无新遥测数据到达且无鼠标交互时，渲染帧率自动回落至 10 FPS 极低功耗维持模式，彻底消除空转时的 GPU 发热与显存霸占。
3. **工具组件生命周期约束 (`<KeepAlive :max="2">`)**：
   - 仅对高频常驻工具保留缓存；离开 SVD、HardFault、RTOS、显存镜像等大型视图时自动彻底销毁，**瞬时释放 150MB~300MB 游离 DOM 与内存开销**。
4. **波形示波器切入后台自动挂起 (`onDeactivated`)**：
   - 切走时立即注销动画帧并暂停微秒级 FFT 定时器；切回时自适应秒唤醒。
5. **点开又关闭标签页的深度清理**：
   - 会话关闭时联动后端解绑波形源，彻底释放终端日志数组与 Web Worker 引用。

---

### 📦 安装包与发布产物

- **Release 压缩包**: `release/AI-HIL-Debugger-v1.2.0-windows-x64.zip` (37.1 MB)
- **包含组件**:
  - `AI-HIL-Debugger.exe` (9.3 MB)
  - `hil-daemon-x86_64-pc-windows-msvc.exe` (34.6 MB)
  - `start.bat` / `install_mcp.bat` / `install_skill.bat` / `diagnose.bat`
  - 默认 INGChips 芯片支持包及 Agent 部署脚本
- **Git 标签**: `v1.2.0`
- **代码仓库**: [ZenghuiJIA/ingchips_debug_tools](https://github.com/ZenghuiJIA/ingchips_debug_tools)
