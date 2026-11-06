# Embedded debug plan status

按 `EMBEDDED_DEBUG_IMPLEMENTATION_PLAN.md` 的边界，本轮完成主机和 SDK 底座，真实硬件能力仍需要目标板卡验收。

| 计划批次 | 当前状态 |
| --- | --- |
| A：契约与底座 | 已实现 HILI v1 Rust 编解码、CRC、文本封装、版本/长度/序号/缺口处理；Rust/Python 离线分析入口；能力查询；功耗空注册表和数据分析接口 |
| B：SDK 与崩溃 | 已实现静态 C SDK、固定长度帧、无堆事件、CRC、丢弃计数、span/IRQ、HCR1 保留槽、Cortex-M 平台边界和离线证据校验；未绑定具体 linker/MCU |
| C：RTOS 与耗时 | 已提供 FreeRTOS 10/11 显式端口，任务实例代次、栈单位、快照容量和运行计数有效位；需在实际 FreeRTOS 工程编译/上板确认宏和 API |
| D：仪器底层 | 功耗 JSONL 时间加权积分、质量检查、PowerSupply/PowerMeasurement 状态机契约、空生产注册表；没有真实厂商驱动 |
| E：HIL 与界面 | Rust v3 全计划能力预检、独立 passive UART 消费者、窗口结束与预算断言已实现；离线分析任务支持状态/取消/结果，现有 Profiler/HardFault/回放入口接入；资源模型在 JSON 中编辑；主动固件控制、自动 crash_collect/rtos_snapshot 因无板卡命令适配而拒绝 |
| F：实机验收 | 未开始；等待 MCU、固件工程、FreeRTOS 版本、编译器、探针、UART/RTT 选择 |

## 当前可使用的主机接口

- `get_debug_capabilities`：返回 HILI、离线分析和仪器驱动能力；`hardware_verified=false`。
- `analyze_instrumentation`：输入事件数组或 HILI 文件，输出耗时质量、范围配对、时钟/序号缺口和任务快照。
- `analyze_crash_bundle`：校验 manifest、路径、文件摘要、内存区间和可选 ELF 构建匹配；离线缺页不补零。
- `analyze_power_capture`：输入规范化功耗 JSONL，做不等间隔质量检查、时间加权平均、电荷和同步电压能量积分。
- `start_debug_analysis` / `get_debug_analysis_status` / `stop_debug_analysis` / `get_debug_analysis_result`：隔离离线任务；结果不进入真实 HIL PASS。

HIL v3 仅接受显式 passive UART 观察窗口；独立消费者持续解码，不消费 HILv1 等待器的数据。power、crash_collect、rtos_snapshot 和主动控制在任何前置硬件写入前拒绝。现有 v1/v2 兼容。串口复位/BOOT 和擦写取消见 HIL_RESET_CANCEL.md。

HIL ING INI 已接入 Rust 下载器，可配置同一步进 BOOT；压测取消支持顶层 STOP/STOPPED 合约。上述主动停止仅指取消清理，不包含 HILI 插桩主动 START/STOP。停止未确认时报告 ERROR/UNKNOWN。已做协议与故障注入回归，未上板验收。

## 目标固件接入顺序

1. 选择 MCU、编译器、优化等级和 FreeRTOS 版本，提供时间源、临界区、整帧 UART/RTT 发送、缓存屏障和 retained RAM 端口。
2. 编译 `firmware/hil-instrumentation/src/` 与对应 Cortex-M/FreeRTOS port；运行 host tests 和跨语言 HILI 向量。
3. 核对链接 map：事件环、HCR1 槽、Fault 入口、常量、栈和提交路径在目标允许的存储区；确认启动文件不清零 `.noinit`。
4. 记录关闭、启用不发送、持续发送三种 RAM/ROM/时序开销；确认丢弃计数和 UART 带宽。
5. 上板验证复位留存、基本/扩展异常帧、坏 SP、FPU、CRC/分块导出、重复块、取消后保留和 HIL 启动代次。

没有上述证据时，界面只展示“实现但未上板验证”，不把分析结果标为硬件通过。

本版限制：Cortex-M 故障入口仍需目标编译器反汇编验收；FreeRTOS 端口仅以公开 API 替身编译，未对实际内核上板。SDK 故障槽保存显式字节负载，主机证据包由项目导出器提供，尚无通用 UART 崩溃导出/清除握手。耗时首版仅对单一时钟 epoch 的完整范围计算 elapsed，不提供运行时间、自身 CPU 时间或跨频段求和。电源状态机有设置/退出策略和未知状态隔离；完整 power_cycle 稳压/放电条件控制未交付，生产能力预检仍拒绝。
