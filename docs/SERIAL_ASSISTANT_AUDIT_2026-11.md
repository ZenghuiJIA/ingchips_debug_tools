# 串口助手专项审查（2026-11）

## 本次检查范围

Vue 串口标签/会话、文本/HEX/VT100 展示、网络流标签、自动应答、后台 capture journal、Rust 串口会话、RTT、DTR/RTS 复位、网络流 worker、烧录交接和断开事件。未连接或操作真实串口。

## 本次修复

### 前端

- TCP Client、TCP Server、UDP 标签不再调用 `open_serial_port`/`close_serial_port`；连接和关闭分别走网络命令。
- 网络标签状态区分“TCP Server 正在监听”和“已有连接”；页面重建时恢复后端仍持有的网络会话。
- 网络标签隐藏串口波特率、端口选择和 DTR/RTS 等不适用控件。
- 空闲 capture gap 只提示一次，避免 150ms 轮询重复刷屏。
- 清屏及端口/底层 session 切换同步清理书签和采集游标。
- 高速串口 Worker 通过 Transferable ArrayBuffer 接收日志，减少主线程与 Worker 的重复拷贝。
- 断开状态发送提前拒绝，不再先做身份查询。
- serial-rx 和 serial-disconnected 使用 session_id 过滤旧连接事件，避免旧会话污染新标签。

### Rust 后端

- 复位固定原始 `PortSession` 和 transaction 许可，不会在等待过程中把 DTR/RTS 脉冲作用到同名新会话。
- DTR/RTS、协议事务、普通发送互斥；复位失败只清理原始会话。
- RTT 重复打开拒绝；连接、单次写入和端口参数增加边界检查。
- 网络和串口 worker 断开事件增加 session 身份校验；旧 worker 不能移除或通知替代会话。
- 显式关闭和 HIL 交接使用统一通知路径，重复关闭不再发送假断开事件。
- capture 缓存统一保留最近 8 个已关闭会话；活跃 session 直接持有自己的 capture，不因缓存逐出失效。
- 烧录恢复失败不再发送“串口控制权已归还”的成功事件。

## 已发现但本批未扩大修复的风险

1. **整体 I/O 截止时间**：RTT 单次连接/写入有超时，但超长 `write_all` 和 native serial writer 的完整 payload 仍不是可取消的整体 deadline。
2. **事件背压**：串口 read thread、journal、serial-rx、waveform-points 和 WebView 之间仍缺统一的丢弃计数/节流策略。capture ring 和录制队列有界，但不能推导整条 GUI 事件链的内存上限。
3. **端口资源规范化**：COM 大小写、`\\.\COMx` 别名、端口路径和 FLASH_PORT 的 key 仍存在局部格式差异；当前主要依赖调用方传入规范名称。
4. **录制 worker 生命周期**：录制写线程错误后会在 status 中保留 error；超时 stop 的 worker 回收、重新 start 与共享 error 状态仍需专项长期测试。
5. **波形事件身份**：serial-rx 已带 session_id，但 waveform-points 仍主要依赖 port 名；同名会话切换时仍建议补 session 身份。
6. **物理接线语义**：已有 DAPLink 复位时序保留历史适配约定，但 USB 品牌不能证明板级 RTS/DTR 极性；通用板型必须使用显式验证过的复位 profile。

## 验证

- 串口外观/滚动回归：7 项通过。
- 网络串口回归：3 项通过。
- 统一前端生产逻辑回归：基础、协议、HIL、烧录和串口相关测试全部通过。
- Rust workspace：`cargo check --locked`、`cargo test --locked --workspace --lib` 通过；本次串口后端共 22 项单测通过，debug-core 18 项，runtime 32 项。
- `pnpm build` 通过；`pnpm tauri build` 已生成 Windows NSIS 和 MSI 安装包。
- 真实硬件、长时间高吞吐、断电重连和 USB 热插拔未在本批执行。

## 本次安装包

- NSIS EXE：`src-tauri/target/release/bundle/nsis/ai-hil-debugger_1.3.4_x64-setup.exe`
- MSI：`src-tauri/target/release/bundle/msi/ai-hil-debugger_1.3.4_x64_en-US.msi`

安装包已完成构建和文件哈希核对，但本次未执行安装/卸载，以避免修改当前开发机系统状态。
