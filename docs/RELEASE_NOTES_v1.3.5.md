# v1.3.5 串口助手与自动发布更新

## 串口与网络会话

- 延续 v1.3.4 的串口/网络标签路由、会话身份、复位并发、RTT 参数校验、capture 缓存和高速日志修复。
- 新增串口网络专项生产回归入口，覆盖网络连接/停止命令路由、监听状态和网络标签交互。
- 增强旧会话事件隔离，避免旧 worker 的接收或断开事件污染新会话。

## 构建与交付

- 新增基于 `vX.Y.Z` tag 的 GitHub Actions 发布流程。
- tag 发布自动执行前端、Rust、daemon/native 和无硬件进程回归。
- 自动构建 Windows NSIS EXE、MSI、portable ZIP，并将对应 release Markdown 作为 GitHub Release 正文。
