# v1.7.0 Embedded Debug implementation plan

本次补齐 HIL 的 ING INI 串口下载路径：计划预检不再要求 SWD 探针，下载和取消在 Rust 后端执行，并按页/扇区边界停止。压测取消支持可配置 STOP/STOPPED 协议，只有当前请求之后、同一串口会话收到确认才会报告目标已停止；超时、断线和未知状态会进入 ERROR 并保留取证状态。

补齐自动化串口复位与进入 BOOT：必须提供已核对的 RTS/DTR 接线配置，取消时释放控制线，Boot 成功另行断言。HIL 烧录取消改为当前页/扇区完成边界停止后续擦写，确认清理与 HALTED 后才报告 CANCELLED；未知结果持久化隔离并阻止后续写入，详见 HIL_RESET_CANCEL.md。

依据 `EMBEDDED_DEBUG_IMPLEMENTATION_PLAN.md` 落地首批 A–E 主机和固件底座：Rust `hil-debug-core` 增加 HILI v1 帧、CRC、版本/长度/序号/缺口和文本封装；新增静态 C 插桩 SDK、Cortex-M 故障保存边界与 FreeRTOS 10/11 显式适配；新增离线插桩耗时/任务分析、证据包校验、功耗 JSONL 时间加权分析和电源/仪器接口契约。

Rust `hil-runtime` 负责原生 HIL、UART 会话、任务监督、报告、镜像/符号/SVD/像素离线处理；Python worker 保留 PyOCD/J-Link/RTT、深度故障和显式 Python 插件。新增嵌入式离线分析入口，不连接设备、不暂停目标、不把数据标为硬件通过。HIL v3 的电源、主动固件控制和未适配目标动作在执行前拒绝。

固件 SDK 的 HILI C 核心通过主机编译测试；真实 MCU、链接脚本、FreeRTOS 版本、保留 RAM、时钟和 UART/RTT 端口需要后续上板验收。功耗仪和电源生产驱动保持空注册表，逻辑分析仪和数据断点不在范围内。

验证包含 Rust workspace 测试、HILI 跨字节向量、固件 SDK 编译、插桩/崩溃/功耗回归、native runtime、前端构建和冻结发布检查。没有真实板卡证据的功能明确标记为未上板验证。
