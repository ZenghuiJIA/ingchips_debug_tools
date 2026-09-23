#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify frozen daemon executable with new features:
1. flash_firmware tool arguments with pack_path & frequency
2. start_jscope_sampling tool arguments with interval_us & swd_frequency_hz
3. svd_import_pack tool execution with GigaDevice pack
"""

import sys
import os
import json
import subprocess

DAEMON_EXE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "hil-daemon-x86_64-pc-windows-msvc.exe"))
GD32_PACK = r"C:\Users\ming\Documents\xwechat_files\wxid_pp3man8zwkkq22_1b12\msg\file\2024-02\GigaDevice.GD32F4xx_DFP.3.1.0.pack"

def run_rpc(proc, method, params, req_id):
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params
    }
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line.strip())

def main():
    print(f"Testing frozen binary: {DAEMON_EXE}")
    assert os.path.isfile(DAEMON_EXE), f"Daemon exe not found: {DAEMON_EXE}"

    proc = subprocess.Popen(
        [DAEMON_EXE, "--mode", "stdio-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    try:
        # 1. Initialize
        resp1 = run_rpc(proc, "initialize", {"protocolVersion": "2024-11-05"}, 1)
        print("1. Initialize:", resp1.get("result", {}).get("serverInfo"))
        assert resp1["result"]["serverInfo"]["name"] == "embedded-hil-debugger"

        # 2. Tools list
        resp2 = run_rpc(proc, "tools/list", {}, 2)
        tools = resp2.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        print(f"2. Tools list: {len(tools)} tools registered.")
        assert "flash_firmware" in tool_names
        assert "start_jscope_sampling" in tool_names
        assert "svd_import_pack" in tool_names

        flash_tool = [t for t in tools if t["name"] == "flash_firmware"][0]
        assert "pack_path" in flash_tool["inputSchema"]["properties"]
        assert "frequency" in flash_tool["inputSchema"]["properties"]
        print("[OK] Frozen binary flash_firmware exposes pack_path and frequency!")

        jscope_tool = [t for t in tools if t["name"] == "start_jscope_sampling"][0]
        assert "interval_us" in jscope_tool["inputSchema"]["properties"]
        assert "swd_frequency_hz" in jscope_tool["inputSchema"]["properties"]
        print("[OK] Frozen binary start_jscope_sampling exposes interval_us and swd_frequency_hz!")

        # 3. Test svd_import_pack on frozen binary
        resp3 = run_rpc(proc, "svd_import_pack", {"pack_path": GD32_PACK}, 3)
        res_pack = resp3.get("result", {})
        print(f"3. svd_import_pack on GD32: status={res_pack.get('status')}, devices={len(res_pack.get('devices', []))}")
        assert res_pack.get("status") == "success"
        assert len(res_pack.get("devices", [])) == 75

        print("\n[ALL FROZEN BINARY CHECKS PASSED!]")

    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)

if __name__ == "__main__":
    main()
