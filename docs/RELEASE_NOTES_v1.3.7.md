# v1.3.7 Linux 多发行版打包支持与双平台并行发布流水线

## Linux 跨平台支持与全格式打包

- 隔离 `windows-sys` 依赖与平台路径逻辑，使 Rust 工作区、Tauri 桌面端、独立 `hil-daemon` / `hil-python-worker` / `hil-protocol` 完整支持 Linux `x86_64`。
- 新增 Linux 打包配置与构建脚本：支持生成 `.deb`（Debian/Ubuntu）、`.rpm`（Fedora/RHEL）、`.AppImage`（通用便携单文件及自动更新签名）以及包含完整依赖与安装脚本的 `.tar.gz` 便携压缩包。
- 新增 Arch Linux AUR 双模板（源码编译版 `ai-hil-debugger` 与预编译版 `ai-hil-debugger-bin`），支持通过 `makepkg -si` 原生安装与卸载。
- 随安装包与支持包内置 `99-ai-hil-debugger.rules` udev 规则，覆盖 DAPLink / CMSIS-DAP、SEGGER J-Link、ST-Link 及常见 USB 转串口设备。

## GitHub Actions 双平台并行 CI/CD

- `ci.yml` 升级为 `windows-2022` 与 `ubuntu-24.04` 双平台并行检查。
- `release.yml` 升级为 `windows-2022` 与 `ubuntu-24.04` 并行构建、自动校验各格式包完整性与 `latest.json` 多平台更新条目，并原子化发布至 GitHub Release。
