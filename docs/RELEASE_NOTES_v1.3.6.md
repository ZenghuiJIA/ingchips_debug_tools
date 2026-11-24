# v1.3.6 应用内签名自动升级、性能瘦身与串口稳定性增强

## 应用内自动检测升级与硬件安全守卫

- 新增 `UpdateManager` 更新管理器（集成于顶栏右侧），支持启动静默检测 GitHub Releases `latest.json`、后台下载进度展示与 Minisign 签名校验。
- 新增 `open_release_page`、硬件占用守卫 `check_update_install_guard` 与安全清理入口 `prepare_for_update`：正在执行 ING 串口烧录或调试任务时禁止安装；安装前自动停止 Desktop Bridge、关闭全部串口/网络会话并清理后台 daemon 子进程树。

## 完整安装包与原子化 GitHub Actions 发布

- 补全 NSIS 安装包 `bundle.resources` 打包资源（内置 `hil-python-worker.exe`、`hil-protocol.exe`、`mcp-tools.json`、默认 CMSIS-Pack 与 `LICENSE`），同时优化绿色便携包结构避免重复打包安装器。
- 新增 `ci.yml` 日常质量门禁，并升级 `release.yml` 与发布脚本：支持签名密钥前置校验、Draft → 资产上传 → `--latest` 原子发布、防覆盖已发布版本，以及防篡改 Minisign 验签测试。

## 性能与体积优化

- 前端除默认串口页外其余 14 个标签页改为 `defineAsyncComponent` 按需懒加载，配置 `<KeepAlive>` 保活上限，并拆分 `@xterm/*` 与 `@lucide/vue` 独立 chunk（移除重复图标依赖 `lucide-vue-next`）。
- Rust 启用 `[profile.release]` LTO + 体积优化并收敛 `tokio` 特性；`MetricsCollector` 重构为增量 PID 刷新与窗口隐藏暂停轮询，移除切页时的无条件 WorkingSet 清理。

## 稳定性与交互体验升级

- 为 `McuProfiler`、`SerialTerminal` 与 `CaptureAnalysis` 补齐 `<KeepAlive>` 切页失活暂停逻辑，避免后台持续占用探针或枚举串口。
- 统一 COM 端口键名规范化（`com3`、`\\.\com3`、`COM3`），为 `waveform-points` 补充 `session_id` 会话隔离过滤，并在高频串口数据通道增加 GUI 背压限流与丢弃计数（原始 capture 日志完整保留）。
- 收紧 WebView CSP / devCsp 策略，并使用全局非阻塞 Toast 与异步确认弹窗替换全部原生阻塞 `alert()` / `confirm()`。
