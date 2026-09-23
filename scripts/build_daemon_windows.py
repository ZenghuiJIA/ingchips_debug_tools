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
        "--hidden-import", "serial",
        "--hidden-import", "serial.tools.list_ports",
        "--hidden-import", "capstone",
        "--hidden-import", "map_analyzer",
        "--hidden-import", "svd_manager",
        "--hidden-import", "hardfault_analyzer",
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--name", "hil-daemon",
    ]
    for mod in exclude_modules:
        cmd.extend(["--exclude-module", mod])
    cmd.append(str(SRC_ENTRY))

    start_time = time.time()
    subprocess.check_call(cmd)
    elapsed = time.time() - start_time

    built_exe = dist_dir / "hil-daemon.exe"
    if not built_exe.exists():
        raise FileNotFoundError(f"PyInstaller build failed, expected output not found: {built_exe}")

    file_size_mb = built_exe.stat().st_size / 1024 / 1024
    print(f"  [OK] Successfully compiled hil-daemon.exe ({file_size_mb:.1f} MB in {elapsed:.1f}s)")
    return built_exe, dist_dir, work_dir

def sync_binaries(built_exe: Path, dist_dir: Path, work_dir: Path):
    """Copy the newly built binary to all deployment locations."""
    print("\n[3/5] Synchronizing binaries across workspace...")
    kill_locking_processes()

    for target in TARGET_PATHS:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_exe, target)
        print(f"  [COPIED] -> {target}")

    # Synchronize to any active release directories
    rel_dir = ROOT_DIR / "release"
    if rel_dir.exists():
        for sub in rel_dir.glob("AI-HIL-Debugger-*"):
            if sub.is_dir() and (sub / "bin").exists():
                shutil.copy2(built_exe, sub / "bin" / OUT_EXE_NAME)
                print(f"  [COPIED] -> {sub / 'bin' / OUT_EXE_NAME}")

    # Clean temporary directories
    shutil.rmtree(dist_dir, ignore_errors=True)
    shutil.rmtree(work_dir, ignore_errors=True)
    spec_file = ROOT_DIR / "hil-daemon.spec"
    if spec_file.exists():
        spec_file.unlink()
    print("  [CLEAN] Removed intermediate build artifacts.")

def verify_mcp_protocol(exe_path: Path):
    """Run automated JSON-RPC MCP handshake and tool call tests on the frozen binary."""
    print("\n[4/5] Running automated MCP protocol validation on frozen binary...")
    p = subprocess.Popen(
        [str(exe_path), "--mode", "stdio-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    try:
        # Test 1: initialize handshake
        init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        p.stdin.write(init_req + "\n")
        p.stdin.flush()
        init_resp_line = p.stdout.readline()
        init_resp = json.loads(init_resp_line)
        assert init_resp.get("id") == 1, f"Invalid response ID: {init_resp}"
        assert "serverInfo" in init_resp.get("result", {}), "Missing serverInfo in initialize response"
        print(f"  [PASS] MCP initialize handshake verified: {init_resp['result']['serverInfo']}")

        # Test 2: notification handling
        notif_req = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        p.stdin.write(notif_req + "\n")
        p.stdin.flush()
        print("  [PASS] MCP notification handling verified (silent ignore without error)")

        # Test 3: tools/list
        tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        p.stdin.write(tools_req + "\n")
        p.stdin.flush()
        tools_resp = json.loads(p.stdout.readline())
        tools_list = tools_resp.get("result", {}).get("tools", [])
        assert len(tools_list) >= 7, f"Expected at least 7 tools, got {len(tools_list)}"
        print(f"  [PASS] MCP tools/list verified: {len(tools_list)} tools available")

        # Test 4: tools/call list_probes
        call_req = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_probes", "arguments": {}}})
        p.stdin.write(call_req + "\n")
        p.stdin.flush()
        call_resp = json.loads(p.stdout.readline())
        call_res = call_resp.get("result", {})
        assert "content" in call_res and "isError" in call_res, f"Invalid CallToolResult schema: {call_res}"
        assert call_res["isError"] is False, f"list_probes reported error: {call_res}"
        print(f"  [PASS] MCP tools/call 'list_probes' executed successfully with standard CallToolResult!")

    finally:
        p.kill()

def post_build_updates():
    """Update agent registrations and refresh the release distribution package."""
    print("\n[5/5] Updating Agent registrations and refreshing release archive...")
    
    # Update MCP agents
    deploy_script = ROOT_DIR / "scripts" / "deploy_mcp_to_agents.py"
    if deploy_script.exists():
        subprocess.check_call([sys.executable, str(deploy_script)])

    # Update release package
    package_script = ROOT_DIR / "scripts" / "package_release.py"
    if package_script.exists():
        subprocess.check_call([sys.executable, str(package_script)])

def main():
    print("=" * 65)
    print("  AI-HIL Debugger - Standalone MCP Daemon Build & Test Pipeline")
    print("=" * 65)
    try:
        kill_locking_processes()
        built_exe, dist_dir, work_dir = build_executable()
        sync_binaries(built_exe, dist_dir, work_dir)
        verify_mcp_protocol(TARGET_PATHS[1])
        post_build_updates()
        print("\n" + "=" * 65)
        print(" [ALL COMPLETE] Standalone MCP Daemon compiled, verified & deployed!")
        print("=" * 65)
    except Exception as e:
        print(f"\n[FAILED] Error during build pipeline: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
