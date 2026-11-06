# Rust 后端迁移

v1.7.0 使用 `hil-runtime` 原生执行纯串口/HIL/离线处理及 HIL ING 下载。`hil-debug-core` 提供协议和记录核心。桌面、CLI、MCP 共用相同的任务接口；需要实际 SWD/J-Link/PyOCD 的操作才通过受限 Python worker。Python worker 只接受短请求，拥有自己的超时、进程树和探针租约。

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
