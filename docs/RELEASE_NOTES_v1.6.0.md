# v1.6.0 Rust 后端收敛

新增 Rust `hil-runtime`：HIL 配置校验、串口会话、游标日志、HILv1 观察、任务取消、报告、CLI/MCP 长任务和离线回放由 Rust 原生执行。Python 仅在 SWD/PyOCD/J-Link、复杂探针诊断或显式 Python 插件需要时启动。

`hil-debug-core` 继续作为协议、记录、镜像、ELF 基础索引、SVD 元数据和像素转换的共享库。HEX/BIN 检查/合并、符号和 RTOS 静态识别、SVD 自定义文件解析、帧缓冲转换增加 Rust 路由；硬件读取仍通过 Python worker。

桌面串口会话开始使用 Rust runtime 的原生读取、RX/TX 记录和会话配置，保留 Rust Tauri 适配层和网络/ING 专用路径。发布包区分 `hil-daemon-x86_64-pc-windows-msvc.exe`（兼容 Python worker）、`hil-python-worker.exe` 和 `hil-native.exe`，避免二进制覆盖。

验证覆盖 Rust 运行器、取消/超时、任务报告、资源锁、串口和协议边界、HEX/SVD/像素样本、Python worker 桥接、冻结 CLI/MCP、前端构建和发布 ZIP。未进行真实板卡、USB 拔插或高速长测；视觉验收仍受 UI 自动化连接限制。
