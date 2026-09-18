#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Execute Real MCP Memory Read/Write Commands on Address 0x20000000
using the Standalone MCP Daemon (bin/hil-daemon-x86_64-pc-windows-msvc.exe).
"""

import json
import time
import subprocess
from pathlib import Path

DAEMON_EXE = Path(__file__).resolve().parent.parent / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"

def main():
    print("=========================================================================")
    print("      MCP (Model Context Protocol) Real Hardware Read/Write Test")
    print(f" Target Binary: {DAEMON_EXE}")
    print(" Target Address: 0x20000000")
    print("=========================================================================\n")

    p = subprocess.Popen(
        [str(DAEMON_EXE), "--mode", "stdio-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    req_id = 0

    def call_mcp(method: str, params: dict) -> dict:
        nonlocal req_id
        req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        msg = json.dumps(payload, ensure_ascii=False)
        print(f">> [MCP Request #{req_id}] {method}")
        print(f"   Payload: {msg}")
        p.stdin.write(msg + "\n")
        p.stdin.flush()

        resp_line = p.stdout.readline()
        if not resp_line:
            err = p.stderr.read()
            raise RuntimeError(f"Daemon exited unexpectedly: {err}")
        
        resp = json.loads(resp_line)
        print(f"<< [MCP Response #{req_id}]")
        print(f"   {json.dumps(resp, ensure_ascii=False, indent=2)}\n")
        time.sleep(0.3)
        return resp

    try:
        # 1. Initialize Handshake
        print("[Step 1] Initializing MCP Protocol...")
        call_mcp("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "antigravity-agent", "version": "1.0.0"}
        })

        # 2. Notification initialized
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        p.stdin.write(notif + "\n")
        p.stdin.flush()
        print(">> [MCP Notification] notifications/initialized sent\n")
        time.sleep(0.2)

        # 3. List Probes
        print("[Step 2] Probing Hardware via MCP 'list_probes'...")
        call_mcp("tools/call", {
            "name": "list_probes",
            "arguments": {}
        })

        TARGET_ADDR = 0x20000000
        TEST_WRITE_VAL = 0xA5A55A5A

        # 4. Read Initial Memory at 0x20000000
        print(f"[Step 3] MCP 'read_memory' Instruction: Reading 0x{TARGET_ADDR:08X}...")
        res_read_init = call_mcp("tools/call", {
            "name": "read_memory",
            "arguments": {
                "address": TARGET_ADDR,
                "count": 16,
                "target_override": "cortex_m"
            }
        })
        init_content = json.loads(res_read_init["result"]["content"][0]["text"])
        init_bytes = init_content.get("bytes", [])
        orig_val = init_bytes[0] | (init_bytes[1] << 8) | (init_bytes[2] << 16) | (init_bytes[3] << 24)
        print(f"==> Address 0x{TARGET_ADDR:08X} Initial Word: 0x{orig_val:08X}")
        print(f"==> Initial Hex Dump: {init_content.get('hex_dump')}\n")

        # 5. Write Memory to 0x20000000
        print(f"[Step 4] MCP 'write_memory' Instruction: Writing 0x{TEST_WRITE_VAL:08X} to 0x{TARGET_ADDR:08X}...")
        res_write = call_mcp("tools/call", {
            "name": "write_memory",
            "arguments": {
                "address": TARGET_ADDR,
                "value": TEST_WRITE_VAL,
                "target_override": "cortex_m"
            }
        })
        print(f"==> Write Result: {res_write['result']['content'][0]['text']}\n")

        # 6. Read Memory to Verify Write
        print(f"[Step 5] MCP 'read_memory' Instruction: Verifying Write at 0x{TARGET_ADDR:08X}...")
        res_read_verify = call_mcp("tools/call", {
            "name": "read_memory",
            "arguments": {
                "address": TARGET_ADDR,
                "count": 16,
                "target_override": "cortex_m"
            }
        })
        verify_content = json.loads(res_read_verify["result"]["content"][0]["text"])
        verify_bytes = verify_content.get("bytes", [])
        verify_val = verify_bytes[0] | (verify_bytes[1] << 8) | (verify_bytes[2] << 16) | (verify_bytes[3] << 24)
        print(f"==> Readback Word: 0x{verify_val:08X}")
        print(f"==> Readback Hex Dump: {verify_content.get('hex_dump')}")

        assert verify_val == TEST_WRITE_VAL, f"Value mismatch! Expected 0x{TEST_WRITE_VAL:08X}, got 0x{verify_val:08X}"
        print(f"==> [VERIFICATION PASSED] 0x{TARGET_ADDR:08X} matches written value 0x{TEST_WRITE_VAL:08X}!\n")

        # 7. Restore Original Value
        print(f"[Step 6] MCP 'write_memory' Instruction: Restoring Original Value 0x{orig_val:08X}...")
        call_mcp("tools/call", {
            "name": "write_memory",
            "arguments": {
                "address": TARGET_ADDR,
                "value": orig_val,
                "target_override": "cortex_m"
            }
        })

        # 8. Final Readback to Confirm Clean Restoration
        print(f"[Step 7] MCP 'read_memory' Instruction: Confirming Restoration...")
        res_read_restore = call_mcp("tools/call", {
            "name": "read_memory",
            "arguments": {
                "address": TARGET_ADDR,
                "count": 16,
                "target_override": "cortex_m"
            }
        })
        restore_content = json.loads(res_read_restore["result"]["content"][0]["text"])
        restore_bytes = restore_content.get("bytes", [])
        restore_val = restore_bytes[0] | (restore_bytes[1] << 8) | (restore_bytes[2] << 16) | (restore_bytes[3] << 24)
        print(f"==> Restored Word: 0x{restore_val:08X}")
        print(f"==> Restored Hex Dump: {restore_content.get('hex_dump')}")
        assert restore_val == orig_val, "Failed to restore original memory state!"
        print(f"==> [RESTORATION PASSED] Original memory state cleanly restored!\n")

        print("=========================================================================")
        print(" [ALL TESTS PASSED] Real MCP read_memory & write_memory instructions at")
        print("                    0x20000000 executed and verified on hardware!")
        print("=========================================================================")

    finally:
        p.terminate()

if __name__ == "__main__":
    main()
