#!/usr/bin/env python3
"""
Build script to freeze the Python HIL daemon into a standalone Windows binary
using PyInstaller (or Nuitka if preferred).
Output target: src-tauri/binaries/hil-daemon-x86_64-pc-windows-msvc.exe
"""
import os
import sys
import subprocess
import shutil

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ENTRY = os.path.join(ROOT_DIR, "src-tauri", "daemon", "daemon_entry.py")
OUT_DIR = os.path.join(ROOT_DIR, "src-tauri", "binaries")
OUT_EXE_NAME = "hil-daemon-x86_64-pc-windows-msvc.exe"
FINAL_TARGET = os.path.join(OUT_DIR, OUT_EXE_NAME)

def build_with_pyinstaller():
    print(f"Building standalone Windows binary via PyInstaller...")
    print(f"Source: {SRC_ENTRY}")
    print(f"Target: {FINAL_TARGET}")

    dist_dir = os.path.join(ROOT_DIR, "build_dist")
    work_dir = os.path.join(ROOT_DIR, "build_work")
    os.makedirs(dist_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconfirm",
        "--clean",
        "--collect-all", "pyocd",
        "--collect-all", "cmsis_pack_manager",
        "--hidden-import", "pyocd.probe.pydapaccess",
        "--hidden-import", "pyocd.probe.cmsis_dap_probe",
        "--hidden-import", "pyocd.coresight",
        "--distpath", dist_dir,
        "--workpath", work_dir,
        "--name", "hil-daemon",
        SRC_ENTRY
    ]

    subprocess.check_call(cmd)

    built_exe = os.path.join(dist_dir, "hil-daemon.exe")
    if os.path.exists(built_exe):
        # Terminate any running instances before copying
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/f", "/im", OUT_EXE_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.makedirs(os.path.dirname(FINAL_TARGET), exist_ok=True)
        shutil.copy2(built_exe, FINAL_TARGET)
        bin_target = os.path.join(ROOT_DIR, "bin", OUT_EXE_NAME)
        os.makedirs(os.path.dirname(bin_target), exist_ok=True)
        shutil.copy2(built_exe, bin_target)
        root_target = os.path.join(ROOT_DIR, OUT_EXE_NAME)
        shutil.copy2(built_exe, root_target)
        print(f"\n[SUCCESS] Standalone binary copied to:")
        print(f"  - {FINAL_TARGET}")
        print(f"  - {bin_target}")
        print(f"  - {root_target}")
        # Clean build artifacts
        shutil.rmtree(dist_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        spec_file = os.path.join(ROOT_DIR, "hil-daemon.spec")
        if os.path.exists(spec_file):
            os.remove(spec_file)
    else:
        raise FileNotFoundError(f"Expected output binary not found: {built_exe}")

if __name__ == "__main__":
    build_with_pyinstaller()
