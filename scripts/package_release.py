#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Packages the AI-HIL Debugger into a standalone Windows release archive (ZIP).
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT_DIR / "release"

def get_release_version() -> str:
    """动态获取版本号：
    1. 优先使用命令行传入的参数 (如 python package_release.py v1.1.1)
    2. 优先尝试获取当前 commit 对应的精确 Git Tag (git describe --tags --exact-match)
    3. 尝试获取最近的 Git Tag (git describe --tags --abbrev=0)
    4. 回退读取 package.json 中的 version
    5. 保底使用 v1.0.0
    """
    # 1. 命令行参数重写
    if len(sys.argv) > 1 and sys.argv[1].strip():
        arg_ver = sys.argv[1].strip()
        if not arg_ver.startswith("v") and arg_ver[0].isdigit():
            arg_ver = f"v{arg_ver}"
        return arg_ver

    # 2. Git Tag (精确匹配)
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # 3. Git Tag (最近 tag)
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # 4. package.json 回退
    pkg_json = ROOT_DIR / "package.json"
    if pkg_json.exists():
        try:
            import json
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                v = data.get("version")
                if v:
                    return f"v{v}" if not v.startswith("v") else v
        except Exception:
            pass

    return "v1.0.0"

def get_release_paths(ver: str):
    pkg_name = f"AI-HIL-Debugger-{ver}-windows-x64"
    target_dir = RELEASE_DIR / pkg_name
    zip_path = RELEASE_DIR / f"{pkg_name}.zip"
    return pkg_name, target_dir, zip_path

def package(custom_version: str = None):
    version = custom_version or get_release_version()
    pkg_name, target_dir, zip_path = get_release_paths(version)

    print("=" * 60)
    print(f" Packaging Release: {pkg_name} (Version: {version})")
    print("=" * 60)

    # Stop any running instances locking files in release directory
    if sys.platform == "win32":
        try:
            import subprocess
            subprocess.run(["taskkill", "/f", "/im", "AI-HIL-Debugger.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["taskkill", "/f", "/im", "hil-daemon-x86_64-pc-windows-msvc.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            time.sleep(0.5)
        except Exception:
            pass

    # Clean previous output
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    if zip_path.exists():
        try:
            zip_path.unlink()
        except Exception:
            pass

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "bin").mkdir(exist_ok=True)
    (target_dir / "scripts").mkdir(exist_ok=True)
    (target_dir / "skills").mkdir(exist_ok=True)
    (target_dir / "mcp").mkdir(exist_ok=True)
    (target_dir / "packs").mkdir(exist_ok=True)

    # Copy primary executables
    print("[1/5] Copying application executables...")
    main_exe_candidates = [
        ROOT_DIR / "src-tauri" / "target" / "release" / "ai-hil-debugger.exe",
        ROOT_DIR / "src-tauri" / "target" / "release" / "AI-HIL-Debugger.exe",
        ROOT_DIR / "bin" / "AI-HIL-Debugger.exe",
    ]
    main_exe = next((p for p in main_exe_candidates if p.exists()), None)
    if main_exe:
        shutil.copy2(main_exe, target_dir / "AI-HIL-Debugger.exe")
        print(f"  [OK] Copied {main_exe.name} -> AI-HIL-Debugger.exe ({main_exe.stat().st_size / 1024 / 1024:.1f} MB)")

    daemon_exe = ROOT_DIR / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"
    if daemon_exe.exists():
        shutil.copy2(daemon_exe, target_dir / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe")
        print(f"  [OK] Copied {daemon_exe.name} ({daemon_exe.stat().st_size / 1024 / 1024:.1f} MB)")

    # Copy batch scripts
    print("[2/5] Copying batch launchers and installers...")
    for bat_file in ["start.bat", "install_mcp.bat", "install_skill.bat", "diagnose.bat"]:
        src = ROOT_DIR / "scripts" / bat_file
        if not src.exists():
            src = ROOT_DIR / bat_file
        if src.exists():
            shutil.copy2(src, target_dir / bat_file)
            print(f"  [OK] Copied {bat_file}")

    # Copy scripts
    print("[3/5] Copying Python helper scripts...")
    for script_name in ["deploy_mcp_to_agents.py", "install_skill.py"]:
        src = ROOT_DIR / "scripts" / script_name
        if src.exists():
            shutil.copy2(src, target_dir / "scripts" / script_name)
            print(f"  [OK] Copied scripts/{script_name}")

    # Copy skills and documentation
    print("[4/5] Copying skills and documentation...")
    skill_src = ROOT_DIR / "skills" / "embedded-hil-debugger"
    if skill_src.exists():
        shutil.copytree(skill_src, target_dir / "skills" / "embedded-hil-debugger")
        print(f"  [OK] Copied skills/embedded-hil-debugger")

    mcp_readme = ROOT_DIR / "mcp" / "README.md"
    if mcp_readme.exists():
        shutil.copy2(mcp_readme, target_dir / "mcp" / "README.md")
        print(f"  [OK] Copied mcp/README.md")

    root_readme = ROOT_DIR / "README.md"
    if root_readme.exists():
        shutil.copy2(root_readme, target_dir / "README.md")
        print(f"  [OK] Copied README.md")

    license_file = ROOT_DIR / "LICENSE"
    if license_file.exists():
        shutil.copy2(license_file, target_dir / "LICENSE")
        print(f"  [OK] Copied LICENSE")

    # Copy packs
    packs_src = ROOT_DIR / "packs"
    if packs_src.exists():
        for p in packs_src.glob("*.pack"):
            shutil.copy2(p, target_dir / "packs" / p.name)
            print(f"  [OK] Copied pack: {p.name}")

    # Compress into zip
    print(f"[5/5] Compressing package into {zip_path.name}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(RELEASE_DIR)
                zf.write(full_path, rel_path)

    zip_size_mb = zip_path.stat().st_size / 1024 / 1024
    print("=" * 60)
    print(f"[SUCCESS] Release packaged successfully!")
    print(f"  Directory: {target_dir}")
    print(f"  Archive:   {zip_path} ({zip_size_mb:.1f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    package()
