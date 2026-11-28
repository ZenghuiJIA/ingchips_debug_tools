# v1.3.9 Arch Linux 原生 `pacman` 仓库源与全平台构建发布

## Arch Linux 原生 `pacman` 仓库支持

- 在 GitHub Actions 发布流水线中集成 `archlinux:latest` 容器打包流程，每次发版自动生成带真实 SHA256 校验的 `ai-hil-debugger-bin-<version>-1-x86_64.pkg.tar.zst` 以及 `ai-hil-debugger.db` / `ai-hil-debugger.db.tar.gz`、`ai-hil-debugger.files` / `ai-hil-debugger.files.tar.gz` 仓库索引。
- 用户可在 `/etc/pacman.conf` 中直接订阅 GitHub Releases 最新版地址，实现 `pacman -Syu ai-hil-debugger-bin` 原生安装与升级。
- 同步更新 Arch `PKGBUILD` 维护人信息与发布校验规则，确保 Windows（`.exe` / `.zip`）与 Linux（`.deb` / `.rpm` / `.AppImage` / `.tar.gz` / `.pkg.tar.zst`）全格式产物完整校验发布。
