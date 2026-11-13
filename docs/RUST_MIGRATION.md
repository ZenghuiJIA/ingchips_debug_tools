# Rust 后端迁移

## MCP/UI 共享边界与 Rust 化优先级

Rust 已经是串口会话、捕获环形日志、协议解码、HIL 计划校验/执行和 Tauri 资源状态的权威实现。后续优先把 MCP JSON-RPC 编解码、UI bridge 的快照协议、资源仲裁和事件游标继续放到 Rust，减少 Python 线程与跨进程重复缓存带来的延迟和状态漂移。

| 接口 | 当前实现 | Rust 化建议 | 原因与边界 |
| --- | --- | --- | --- |
| 串口打开/读取/捕获/协议解码 | Rust UI/runtime；Python 兼容入口 | 保持 Rust 权威，Python 只做代理 | 单一会话、低延迟、共享 UI 捕获；MCP 默认只读 |
| 串口发送/关闭/RTS-DTR 复位 | Rust UI | 保持 Rust 独占控制 | UI 持有时 MCP 返回 `resource_busy`，避免抢占和误复位 |
| MCP stdio JSON-RPC、工具描述、错误包装 | Python daemon | 迁移到 native runtime 的 Rust MCP 层 | 降低启动和每次调用开销，统一 `isError`、资源冲突和取消语义 |
| UI bridge 快照/事件游标 | Rust Tauri bridge | 保持 Rust，增加版本和会话代次 | MCP 可共享 UI 已收到的数据，不重新打开串口 |
| PyOCD/J-Link、CMSIS-Pack、SVD、HardFault 深度分析 | Python worker | 暂不迁移 | 依赖生态和厂商兼容性，迁移收益小于风险 |
| HIL 报告、事件日志、回放 | Rust runtime + 兼容 Python worker | Rust 统一序列化与报告索引 | 适合高吞吐事件流和取消，保持旧文件格式 |

MCP 的 `get_ui_state` 和 `get_serial_snapshot` 是只读接口；`open_serial_port` 默认 `access_mode=observe`，只接受已由 UI 打开的会话。`send_serial_data`、`close_serial_port`、`reset_serial` 不会绕过 UI 会话的所有权。没有桌面 bridge 时，独立 daemon 仍可用 `access_mode=control` 打开自己的串口，但这不代表可以与 UI 同时操作同一物理端口。

v1.7.0 使用 `hil-runtime` 原生执行纯串口/HIL/离线处理及 HIL ING 下载。`hil-debug-core` 提供协议和记录核心。桌面、CLI、MCP 共用相同的任务接口；需要实际 SWD/J-Link/PyOCD 的操作才通过受限 Python worker。Python worker 只接受短请求，拥有自己的超时、进程树和探针租约。

兼容 Python daemon 也采用延迟导入：基础 MCP/bridge 启动不加载 PyOCD、PyLink、CMSIS-Pack、pyserial、IntelHex 或 HIL runner；首次进入对应工具分支时才初始化依赖。这样旧客户端仍能使用原协议，同时避免普通 UI 状态和串口观察请求承担探针栈的启动与常驻内存开销。

发布包中的三个相关程序：

| 文件 | 用途 |
| --- | --- |
| `bin/hil-daemon-x86_64-pc-windows-msvc.exe` | Rust native runtime 的兼容文件名，保留旧 MCP 工具入口 |
| `bin/hil-python-worker.exe` | Rust runtime 按需调用的 SWD/探针兼容 worker |
| `bin/hil-native.exe` | Rust HIL、串口、文件和 MCP runtime |

Rust HIL 接口保留 `validate_hiltest`、`run_hiltest`、`get_hiltest_status`、`get_hiltest_events`、`stop_hiltest`、`get_hiltest_report`。任务目录仍有 plan/status/events/serial/report/JUnit/HTML。运行中关闭服务由监督器终止并标记 `INTERRUPTED`。

保留 Python 的能力：PyOCD/J-Link 连接、RTT、SWD 读写、烧录、HardFault 深度分析、某些厂商 Pack 兼容，以及用户显式选择的 Python 离线插件。Python 适配器不再管理普通 HIL 串口；同一串口由 Rust runtime 独占。

迁移限制：当前 Tauri 的 RTT、ING、网络流和部分历史兼容页面仍由原 Rust 管理器/旧 daemon 路径处理；没有实际探针时，Rust HIL 可验证配置和纯延时，但硬件步骤会明确失败。Python 正则与 Rust bytes regex 的差异在配置检查阶段报告，不静默改变匹配。

验证顺序：先运行 `cargo test --locked --workspace --lib`、`python scripts/test_native_runtime.py`、`python scripts/test_abc_backend.py` 和 `node scripts/verify_features_regression.js`，再构建 Python worker/native/desktop，最后运行冻结程序和 `scripts/verify_release.py`。未经板卡验证的性能数字只代表软件或合成测试。
