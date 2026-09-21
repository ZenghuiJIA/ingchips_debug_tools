#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Packages the AI-HIL Debugger into a standalone Windows release archive (ZIP).
"""

import os
import sys
import shutil
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT_DIR / "release"
PKG_NAME = "AI-HIL-Debugger-v1.0.0-windows-x64"
TARGET_DIR = RELEASE_DIR / PKG_NAME
ZIP_PATH = RELEASE_DIR / f"{PKG_NAME}.zip"

def package():
    print("=" * 60)
    print(f" Packaging Release: {PKG_NAME}")
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
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR, ignore_errors=True)
    if ZIP_PATH.exists():
        try:
            ZIP_PATH.unlink()
        except Exception:
            pass

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    (TARGET_DIR / "bin").mkdir(exist_ok=True)
    (TARGET_DIR / "scripts").mkdir(exist_ok=True)
    (TARGET_DIR / "skills").mkdir(exist_ok=True)
    (TARGET_DIR / "mcp").mkdir(exist_ok=True)

    # Copy primary executables
    print("[1/5] Copying application executables...")
    main_exe_candidates = [
        ROOT_DIR / "src-tauri" / "target" / "release" / "ai-hil-debugger.exe",
        ROOT_DIR / "src-tauri" / "target" / "release" / "AI-HIL-Debugger.exe",
        ROOT_DIR / "AI-HIL-Debugger.exe",
        ROOT_DIR / "bin" / "AI-HIL-Debugger.exe",
    ]
    main_exe = next((p for p in main_exe_candidates if p.exists()), None)
    if main_exe:
        shutil.copy2(main_exe, TARGET_DIR / "AI-HIL-Debugger.exe")
        shutil.copy2(main_exe, TARGET_DIR / "bin" / "AI-HIL-Debugger.exe")
        shutil.copy2(main_exe, ROOT_DIR / "AI-HIL-Debugger.exe")
        shutil.copy2(main_exe, ROOT_DIR / "bin" / "AI-HIL-Debugger.exe")
        print(f"  [OK] Copied {main_exe.name} -> AI-HIL-Debugger.exe ({main_exe.stat().st_size / 1024 / 1024:.1f} MB)")

    daemon_exe = ROOT_DIR / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"
    if daemon_exe.exists():
        shutil.copy2(daemon_exe, TARGET_DIR / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe")
        shutil.copy2(daemon_exe, TARGET_DIR / "hil-daemon-x86_64-pc-windows-msvc.exe")
        print(f"  [OK] Copied {daemon_exe.name} ({daemon_exe.stat().st_size / 1024 / 1024:.1f} MB)")

    # Copy batch scripts
    print("[2/5] Copying batch launchers and installers...")
    for bat_file in ["start.bat", "install_mcp.bat", "install_skill.bat", "diagnose.bat"]:
        src = ROOT_DIR / bat_file
        if src.exists():
            shutil.copy2(src, TARGET_DIR / bat_file)
            print(f"  [OK] Copied {bat_file}")

    # Copy scripts
    print("[3/5] Copying Python helper scripts...")
    for script_name in ["deploy_mcp_to_agents.py", "install_skill.py"]:
        src = ROOT_DIR / "scripts" / script_name
        if src.exists():
            shutil.copy2(src, TARGET_DIR / "scripts" / script_name)
            print(f"  [OK] Copied scripts/{script_name}")

    # Copy skills and documentation
    print("[4/5] Copying skills and documentation...")
    skill_src = ROOT_DIR / "skills" / "embedded-hil-debugger"
    if skill_src.exists():
        shutil.copytree(skill_src, TARGET_DIR / "skills" / "embedded-hil-debugger")
        print(f"  [OK] Copied skills/embedded-hil-debugger")

    mcp_readme = ROOT_DIR / "mcp" / "README.md"
    if mcp_readme.exists():
        shutil.copy2(mcp_readme, TARGET_DIR / "mcp" / "README.md")
        print(f"  [OK] Copied mcp/README.md")

    root_readme = ROOT_DIR / "README.md"
    if root_readme.exists():
        shutil.copy2(root_readme, TARGET_DIR / "README.md")
        print(f"  [OK] Copied README.md")

    license_file = ROOT_DIR / "LICENSE"
    if license_file.exists():
        shutil.copy2(license_file, TARGET_DIR / "LICENSE")
        print(f"  [OK] Copied LICENSE")

    # Compress into zip
    print(f"[5/5] Compressing package into {ZIP_PATH.name}...")
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(TARGET_DIR):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(RELEASE_DIR)
                zf.write(full_path, rel_path)

    zip_size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    print("=" * 60)
    print(f"[SUCCESS] Release packaged successfully!")
    print(f"  Directory: {TARGET_DIR}")
    print(f"  Archive:   {ZIP_PATH} ({zip_size_mb:.1f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    package()
