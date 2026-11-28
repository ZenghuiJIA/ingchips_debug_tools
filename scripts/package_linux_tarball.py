#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Packages AI-HIL Debugger for Linux into a portable, self-contained .tar.gz archive
following standard open-source Linux release conventions (bin/, lib/, share/, udev/, install.sh).
"""

import hashlib
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT_DIR / "release"


def get_version() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        v = sys.argv[1].strip()
        return v if v.startswith("v") else f"v{v}"
    pkg = json.loads((ROOT_DIR / "package.json").read_text(encoding="utf-8"))
    v = pkg["version"]
    return v if v.startswith("v") else f"v{v}"


def main():
    version = get_version()
    pkg_name = f"AI-HIL-Debugger-{version}-linux-x86_64"
    stage_dir = RELEASE_DIR / pkg_name
    tar_path = RELEASE_DIR / f"{pkg_name}.tar.gz"

    app_bin = ROOT_DIR / "src-tauri" / "target" / "release" / "ai-hil-debugger"
    daemon_bin = ROOT_DIR / "src-tauri" / "binaries" / "hil-daemon-x86_64-unknown-linux-gnu"
    worker_bin = ROOT_DIR / "src-tauri" / "binaries" / "hil-python-worker"
    protocol_bin = ROOT_DIR / "src-tauri" / "binaries" / "hil-protocol"
    mcp_tools = ROOT_DIR / "src-tauri" / "binaries" / "mcp-tools.json"
    pack_file = ROOT_DIR / "packs" / "INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack"
    udev_rules = ROOT_DIR / "packaging" / "udev" / "99-ai-hil-debugger.rules"
    desktop_file = ROOT_DIR / "packaging" / "linux" / "ai-hil-debugger.desktop"
    icon_file = ROOT_DIR / "src-tauri" / "icons" / "128x128.png"
    install_sh = ROOT_DIR / "packaging" / "linux" / "install.sh"
    uninstall_sh = ROOT_DIR / "packaging" / "linux" / "uninstall.sh"

    required = [
        app_bin, daemon_bin, worker_bin, protocol_bin, mcp_tools,
        pack_file, udev_rules, desktop_file, icon_file, install_sh, uninstall_sh,
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing required build artifacts:\n  " + "\n  ".join(missing))

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    (stage_dir / "bin").mkdir(parents=True, exist_ok=True)
    (stage_dir / "lib" / "packs").mkdir(parents=True, exist_ok=True)
    (stage_dir / "share").mkdir(parents=True, exist_ok=True)
    (stage_dir / "udev").mkdir(parents=True, exist_ok=True)

    shutil.copy2(app_bin, stage_dir / "bin" / "ai-hil-debugger")
    shutil.copy2(daemon_bin, stage_dir / "bin" / "hil-daemon")
    shutil.copy2(worker_bin, stage_dir / "lib" / "hil-python-worker")
    shutil.copy2(protocol_bin, stage_dir / "lib" / "hil-protocol")
    shutil.copy2(mcp_tools, stage_dir / "lib" / "mcp-tools.json")
    shutil.copy2(pack_file, stage_dir / "lib" / "packs" / pack_file.name)
    shutil.copy2(udev_rules, stage_dir / "udev" / udev_rules.name)
    shutil.copy2(desktop_file, stage_dir / "share" / desktop_file.name)
    shutil.copy2(icon_file, stage_dir / "share" / "ai-hil-debugger.png")
    shutil.copy2(install_sh, stage_dir / "install.sh")
    shutil.copy2(uninstall_sh, stage_dir / "uninstall.sh")
    shutil.copy2(ROOT_DIR / "LICENSE", stage_dir / "LICENSE")
    shutil.copy2(ROOT_DIR / "README.md", stage_dir / "README.md")

    # Add a direct portable launcher at archive root
    launcher = stage_dir / "ai-hil-debugger"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'export PATH="${HERE}/bin:${HERE}/lib:${PATH}"\n'
        'exec "${HERE}/bin/ai-hil-debugger" "$@"\n',
        encoding="utf-8",
    )

    for exe in [
        launcher,
        stage_dir / "bin" / "ai-hil-debugger",
        stage_dir / "bin" / "hil-daemon",
        stage_dir / "lib" / "hil-python-worker",
        stage_dir / "lib" / "hil-protocol",
        stage_dir / "install.sh",
        stage_dir / "uninstall.sh",
    ]:
        exe.chmod(0o755)

    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(stage_dir, arcname=pkg_name)

    sha = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    (RELEASE_DIR / f"{tar_path.name}.sha256").write_text(f"{sha}  {tar_path.name}\n", encoding="utf-8")

    size_mb = tar_path.stat().st_size / 1024 / 1024
    print(f"[OK] Created {tar_path} ({size_mb:.1f} MB, sha256={sha[:12]}...)")


if __name__ == "__main__":
    main()
