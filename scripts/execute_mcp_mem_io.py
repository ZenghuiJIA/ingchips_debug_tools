#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Execute Real MCP Memory Read/Write Commands via Standard JSON-RPC 2.0 MCP Protocol.
Interacts directly with the standalone daemon binary: bin/hil-daemon-x86_64-pc-windows-msvc.exe
"""

import sys
import json
import time
import subprocess
from pathlib import Path

DAEMON_EXE = Path(__file__).resolve().parent.parent / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"

def run_mcp_mem_test():
    print(f"=== [MCP Client] Connecting to Standalone MCP Server ===")
    print(f"Server Executable: {DAEMON_EXE}")
    print(f"Protocol: Model Context Protocol (MCP) JSON-RPC 2.0 over stdio\n")

    p = subprocess.Popen(
        [str(DAEMON_EXE), "--mode", "stdio-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    req_id = 0

    def send_request(method: str, params: dict) -> dict:
        nonlocal req_id
        req_id += 1
        req_obj = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        req_json = json.dumps(req_obj, ensure_ascii=False)
        print(f">> [MCP Request #{req_id}]: {method}")
        print(f"   Payload: {req_json}")
        p.stdin.write(req_json + "\n")
        p.stdin.flush()

        line = p.stdout.readline()
        if not line:
            err = p.stderr.read()
            raise RuntimeError(f"Server closed connection unexpectedly. Stderr: {err}")
        
        resp_obj = json.loads(line)
        print(f"<< [MCP Response #{req_id}]:")
        print(f"   {json.dumps(resp_obj, ensure_ascii=False, indent=2)}\n")
        return resp_obj

    def send_notification(method: str, params: dict):
        notif_obj = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        req_json = json.dumps(notif_obj, ensure_ascii=False)
        print(f">> [MCP Notification]: {method}")
        print(f"   Payload: {req_json}\n")
        p.stdin.write(req_json + "\n")
        p.stdin.flush()

    try:
        # Step 1: MCP initialize handshake
        init_res = send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "embedded-hil-mcp-tester",
                "version": "1.0.0"
            }
        })
        assert "serverInfo" in init_res.get("result", {}), "MCP initialize handshake failed"

        # Step 2: MCP initialized notification
        send_notification("notifications/initialized", {})

        # Step 3: MCP tools/list discovery
        tools_res = send_request("tools/list", {})
        tool_names = [t["name"] for t in tools_res.get("result", {}).get("tools", [])]
        print(f"Discovered Tools: {tool_names}\n")

        # Target test memory address (SRAM area)
        TEST_ADDR = 0x20000100
        TEST_VAL_1 = 0xDEADBEEF
        TEST_VAL_2 = 0x12345678

        # Step 4: [MCP Instruction 1] Read Memory before writing
        print(f"--- [TEST STEP 1] MCP 'read_memory' Instruction ---")
        read_res_1 = send_request("tools/call", {
            "name": "read_memory",
            "arguments": {
                "address": TEST_ADDR,
                "count": 16,
                "target_override": "cortex_m"
            }
        })
        content_1 = json.loads(read_res_1["result"]["content"][0]["text"])
        orig_hex = content_1.get("hex_dump", "")
        print(f"==> Address 0x{TEST_ADDR:08X} Initial Hex Dump: {orig_hex}\n")

        # Step 5: [MCP Instruction 2] Write Memory (write 0xDEADBEEF)
        print(f"--- [TEST STEP 2] MCP 'write_memory' Instruction (Write 0x{TEST_VAL_1:08X}) ---")
        write_res_1 = send_request("tools/call", {
            "name": "write_memory",
            "arguments": {
                "address": TEST_ADDR,
                "value": TEST_VAL_1,
                "target_override": "cortex_m"
            }
        })
        print(f"==> Write Result: {write_res_1['result']['content'][0]['text']}\n")

        # Step 6: [MCP Instruction 3] Read Memory to verify write 1
        print(f"--- [TEST STEP 3] MCP 'read_memory' Instruction (Verify 0x{TEST_VAL_1:08X}) ---")
        read_res_2 = send_request("tools/call", {
            "name": "read_memory",
            "arguments": {
                "address": TEST_ADDR,
                "count": 16,
                "target_override": "cortex_m"
            }
        })
        content_2 = json.loads(read_res_2["result"]["content"][0]["text"])
        verify_hex_1 = content_2.get("hex_dump", "")
        print(f"==> Readback Hex Dump: {verify_hex_1}")
        
        # Verify little-endian 0xDEADBEEF -> EF BE AD DE
        raw_bytes = content_2.get("bytes", [])
        assert raw_bytes[0] == 0xEF and raw_bytes[1] == 0xBE and raw_bytes[2] == 0xAD and raw_bytes[3] == 0xDE, \
            f"Readback mismatch! Expected [EF, BE, AD, DE], got {raw_bytes[:4]}"
        print(f"==> [VERIFIED SUCCESS] Target SRAM received and stored 0x{TEST_VAL_1:08X}!\n")

        # Step 7: [MCP Instruction 4] Write Memory (write 0x12345678)
        print(f"--- [TEST STEP 4] MCP 'write_memory' Instruction (Write 0x{TEST_VAL_2:08X}) ---")
        write_res_2 = send_request("tools/call", {
            "name": "write_memory",
            "arguments": {
                "address": TEST_ADDR,
                "value": TEST_VAL_2,
                "target_override": "cortex_m"
            }
        })
        print(f"==> Write Result: {write_res_2['result']['content'][0]['text']}\n")

        # Step 8: [MCP Instruction 5] Read Memory to verify write 2
        print(f"--- [TEST STEP 5] MCP 'read_memory' Instruction (Verify 0x{TEST_VAL_2:08X}) ---")
        read_res_3 = send_request("tools/call", {
            "name": "read_memory",
            "arguments": {
                "address": TEST_ADDR,
                "count": 16,
                "target_override": "cortex_m"
            }
        })
        content_3 = json.loads(read_res_3["result"]["content"][0]["text"])
        verify_hex_2 = content_3.get("hex_dump", "")
        print(f"==> Readback Hex Dump: {verify_hex_2}")

        # Verify little-endian 0x12345678 -> 78 56 34 12
        raw_bytes_2 = content_3.get("bytes", [])
        assert raw_bytes_2[0] == 0x78 and raw_bytes_2[1] == 0x56 and raw_bytes_2[2] == 0x34 and raw_bytes_2[3] == 0x12, \
            f"Readback mismatch! Expected [78, 56, 34, 12], got {raw_bytes_2[:4]}"
        print(f"==> [VERIFIED SUCCESS] Target SRAM received and stored 0x{TEST_VAL_2:08X}!\n")

        print("=========================================================================")
        print(" [ALL PASSED] Both MCP 'read_memory' and 'write_memory' instructions")
        print("              have executed successfully on the physical hardware target!")
        print("=========================================================================")

    finally:
        p.terminate()

if __name__ == "__main__":
    run_mcp_mem_test()
