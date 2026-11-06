#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated Build & Packaging Script for Standalone HIL MCP Daemon.
Freezes src-tauri/daemon/daemon_entry.py into hil-daemon-x86_64-pc-windows-msvc.exe,
runs automated MCP handshake self-tests, synchronizes binaries, and updates agent configs & release zip.
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_ENTRY = ROOT_DIR / "src-tauri" / "daemon" / "daemon_entry.py"
OUT_EXE_NAME = "hil-daemon-x86_64-pc-windows-msvc.exe"

TARGET_PATHS = [
    ROOT_DIR / "src-tauri" / "binaries" / OUT_EXE_NAME,
    ROOT_DIR / "bin" / OUT_EXE_NAME,
    ROOT_DIR / "src-tauri" / "target" / "release" / OUT_EXE_NAME,
    ROOT_DIR / "src-tauri" / "target" / "debug" / OUT_EXE_NAME,
]

def kill_locking_processes():
    """Terminate any background instances holding locks on the target binary."""
    print("[1/5] Checking and stopping running daemon instances...")
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/f", "/im", OUT_EXE_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
        except Exception:
            pass
    print("  [OK] Process lock cleared.")

def build_executable():
    """Invoke PyInstaller to build the standalone onefile executable."""
    print(f"\n[2/5] Compiling standalone executable via PyInstaller...")
    print(f"  Source: {SRC_ENTRY}")

    if not SRC_ENTRY.exists():
        raise FileNotFoundError(f"Source entry point not found: {SRC_ENTRY}")

    dist_dir = ROOT_DIR / "build_dist"
    work_dir = ROOT_DIR / "build_work"
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    exclude_modules = [
        "PySide6",
        "shiboken6",
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "PIL",
        "pillow",
        "tkinter",
        "tcl",
        "tk",
        "unittest",
        "pytest",
        "pypdf",
        "openpyxl",
        "fastapi",
        "uvicorn",
        "starlette",
        "can",
        "canopen",
        "pyvisa",
        "fonttools",
        "contourpy",
        "kiwisolver",
        "IPython",
        "jupyter",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconfirm",
        "--clean",
        "--collect-all", "pyocd",
        "--collect-all", "cmsis_pack_manager",
        "--collect-all", "pylink",
        "--collect-all", "elftools",
        "--hidden-import", "pylink",
        "--hidden-import", "elftools",
        "--hidden-import", "pyocd.probe.pydapaccess",
        "--hidden-import", "pyocd.probe.cmsis_dap_probe",
        "--hidden-import", "pyocd.probe.jlink_probe",
        "--hidden-import", "pyocd.coresight",
        "--paths", str(SRC_ENTRY.parent),
        "--collect-all", "capstone",
        "--collect-all", "serial",
        "--collect-all", "intelhex",
        "--hidden-import", "serial",
        "--hidden-import", "serial.tools.list_ports",
        "--hidden-import", "intelhex",
        "--hidden-import", "capstone",
        "--hidden-import", "map_analyzer",
        "--hidden-import", "svd_manager",
        "--hidden-import", "hardfault_analyzer",
        "--hidden-import", "hil.worker",
        "--hidden-import", "hil.replay",
        "--hidden-import", "hil.codec",
        "--hidden-import", "hil.plugins",
        "--hidden-import", "debug_service",
        "--hidden-import", "flash_control",
        "--hidden-import", "instrumentation.analysis",
        "--hidden-import", "hil.crash",
        "--hidden-import", "instruments.power",
        "--hidden-import", "instruments.contracts",
        "--hidden-import", "yaml",
        "--hidden-import", "psutil",
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--name", "hil-python-worker",
    ]
    for mod in exclude_modules:
        cmd.extend(["--exclude-module", mod])
    cmd.append(str(SRC_ENTRY))

    start_time = time.time()
    subprocess.check_call(cmd)
    elapsed = time.time() - start_time

    built_exe = dist_dir / "hil-python-worker.exe"
    if not built_exe.exists():
        raise FileNotFoundError(f"PyInstaller build failed, expected output not found: {built_exe}")

    file_size_mb = built_exe.stat().st_size / 1024 / 1024
    print(f"  [OK] Successfully compiled hil-daemon.exe ({file_size_mb:.1f} MB in {elapsed:.1f}s)")
    return built_exe, dist_dir, work_dir

def sync_binaries(built_exe: Path, dist_dir: Path, work_dir: Path):
    """Update workspace launch locations without terminating active debugging sessions."""
    for target in TARGET_PATHS:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_suffix(".exe.new")
        try:
            shutil.copy2(built_exe, staging)
            os.replace(staging, target)
            print(f"  [COPIED] {target}")
        except PermissionError:
            if staging.exists():
                staging.unlink()
            print(f"  [IN USE] {target}; new binary remains in {built_exe}")
    # Historical releases are immutable. The new archive receives the verified binary.


def verify_mcp_protocol(exe_path: Path):
    """Bounded, hardware-free tests on the frozen process."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "__invalid_test_tool__", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        {"jsonrpc": "2.0", "id": 5, "method": "shutdown"},
    ]
    process = subprocess.Popen([str(exe_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        out, err = process.communicate("\n".join(json.dumps(r) for r in requests) + "\n", timeout=60)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError("Frozen MCP protocol test timed out")
    if process.returncode:
        raise RuntimeError(err)
    responses = [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]
    assert [r["id"] for r in responses] == [1, 2, 3, 4, 5], responses
    expected_version = json.loads((ROOT_DIR / 'package.json').read_text(encoding='utf-8'))['version']
    assert responses[0]["result"]["serverInfo"]["version"] == expected_version
    assert len(responses[1]["result"]["tools"]) >= 7
    assert responses[2]["result"]["isError"] is True
    assert responses[3]["result"] == {}
    print("[PASS] Frozen MCP initialize/notification/tools/error/ping/shutdown")


def build_native_codec():
    subprocess.run(['cargo', 'build', '--locked', '--release', '-p', 'hil-debug-core', '--bin', 'hil-protocol'], cwd=ROOT_DIR / 'src-tauri', check=True)
    source = ROOT_DIR / 'src-tauri/target/release/hil-protocol.exe'
    for directory in [ROOT_DIR / 'build_dist', ROOT_DIR / 'src-tauri/binaries', ROOT_DIR / 'bin']:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'hil-protocol.exe'
        staging = directory / 'hil-protocol.exe.new'
        shutil.copy2(source, staging)
        try:
            os.replace(staging, target)
        except PermissionError:
            staging.unlink(missing_ok=True)
            print(f'[IN USE] {target}; native codec available in {source}')


def build_native_runtime():
    subprocess.run(['cargo', 'build', '--locked', '--release', '-p', 'hil-runtime', '--bin', 'hil-native'], cwd=ROOT_DIR / 'src-tauri', check=True)
    source = ROOT_DIR / 'src-tauri/target/release/hil-native.exe'
    output = ROOT_DIR / 'build_dist/hil-native.exe'
    shutil.copy2(source, output)
    sys.path.insert(0, str(SRC_ENTRY.parent))
    import daemon_entry
    catalog = {'tools': daemon_entry.MCP_TOOLS}
    for folder in [ROOT_DIR / 'build_dist', SRC_ENTRY.parent, ROOT_DIR / 'src-tauri/binaries', ROOT_DIR / 'src-tauri/target/release', ROOT_DIR / 'src-tauri/target/debug']:
        (folder / 'mcp-tools.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
        if folder != ROOT_DIR / 'build_dist':
            shutil.copy2(ROOT_DIR / 'build_dist/hil-python-worker.exe', folder / 'hil-python-worker.exe')
            shutil.copy2(output, folder / 'hil-native.exe')
    return output


def main():
    print("=" * 65)
    print("  AI-HIL Debugger - Standalone MCP Daemon Build & Test Pipeline")
    print("=" * 65)
    try:
        build_native_codec()
        python_worker, dist_dir, work_dir = build_executable()
        native_runtime = build_native_runtime()
        verify_mcp_protocol(python_worker)
        verify_mcp_protocol(native_runtime)
        sync_binaries(native_runtime, dist_dir, work_dir)
        if "--daemon-only" not in sys.argv:
            from package_release import package
            package(daemon_source=native_runtime)
        print("\n" + "=" * 65)
        print(" [ALL COMPLETE] Standalone MCP Daemon compiled and verified!")
        print("=" * 65)
    except Exception as e:
        print(f"\n[FAILED] Error during build pipeline: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
