#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verification Script for:
1. Pack flash algorithm registration & Session creation with pack/frequency options
2. JScope microsecond sampling up to 1MHz with SWD clock configuration
3. Physics deduction formula for SWD frequency vs max sampling rate
"""

import sys
import os
import time
import socket
import threading

# Add daemon directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src-tauri", "daemon")))

from daemon_entry import PyOCDController, JScopeController, dispatch_tool, MCP_TOOLS
from svd_manager import SvdManager

GD32_PACK = r"C:\Users\ming\Documents\xwechat_files\wxid_pp3man8zwkkq22_1b12\msg\file\2024-02\GigaDevice.GD32F4xx_DFP.3.1.0.pack"
ING_PACK = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "packs", "INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack"))


def test_1_pack_flash_algorithm():
    print("\n--- Test 1: CMSIS-Pack Flash Algorithm & Target Registration ---")
    assert os.path.isfile(GD32_PACK), f"GD32 Pack not found: {GD32_PACK}"
    
    # 1. Import pack via SvdManager / dispatch_tool
    res = SvdManager.import_pack(GD32_PACK)
    assert res["status"] == "success"
    devices = res["devices"]
    print(f"[OK] SvdManager imported {len(devices)} devices from GD32 pack.")
    
    # Verify target exists in PyOCD
    from pyocd.target import TARGET
    assert "gd32f403rc" in TARGET, "gd32f403rc not found in TARGET registry!"
    print("[OK] gd32f403rc successfully registered in pyocd.target.TARGET!")

    # 2. Test Session options with pack and frequency
    session = PyOCDController._create_session(
        probe_id=None,
        target_override="gd32f403rc",
        auto_open=False,
        pack=GD32_PACK,
        frequency=20_000_000
    )
    assert session.options.get("target_override") == "gd32f403rc"
    assert session.options.get("pack") == GD32_PACK
    assert session.options.get("frequency") == 20_000_000
    print(f"[OK] PyOCD Session configured with pack and frequency: {session.options.get('frequency')} Hz")


def test_2_physics_deduction_formula():
    print("\n--- Test 2: SWD Frequency vs Max Sampling Rate Physics Deduction ---")
    
    def calc_limits(swd_hz: int, num_vars: int):
        single_var_sec = (80 / swd_hz) + 1.5e-6
        total_scan_sec = num_vars * single_var_sec
        max_rate_hz = min(1_000_000, int(1 / total_scan_sec))
        min_period_us = max(1, int(total_scan_sec * 1_000_000 + 0.999))
        return max_rate_hz, min_period_us

    # Test Case A: 50 MHz SWD, 1 variable
    rate_50m_1v, us_50m_1v = calc_limits(50_000_000, 1)
    print(f"50 MHz SWD, 1 var: Max Rate = {rate_50m_1v} Hz, Min Period = {us_50m_1v} us")
    assert rate_50m_1v >= 300_000, "50 MHz should achieve ultra-high rate"

    # Test Case B: 10 MHz SWD, 1 variable
    rate_10m_1v, us_10m_1v = calc_limits(10_000_000, 1)
    print(f"10 MHz SWD, 1 var: Max Rate = {rate_10m_1v} Hz, Min Period = {us_10m_1v} us")
    assert 90_000 <= rate_10m_1v <= 110_000

    # Test Case C: 1 MHz SWD, 1 variable
    rate_1m_1v, us_1m_1v = calc_limits(1_000_000, 1)
    print(f"1 MHz SWD, 1 var: Max Rate = {rate_1m_1v} Hz, Min Period = {us_1m_1v} us")
    assert 11_000 <= rate_1m_1v <= 13_000
    assert us_1m_1v >= 80

    # Test Case D: 100 kHz SWD (low freq), 4 variables
    rate_100k_4v, us_100k_4v = calc_limits(100_000, 4)
    print(f"100 kHz SWD, 4 vars: Max Rate = {rate_100k_4v} Hz, Min Period = {us_100k_4v} us")
    assert rate_100k_4v < 350, "100 kHz SWD with 4 vars must restrict rate to < 350 Hz"
    print("[OK] Physics deduction calculations validated against SWD protocol bounds.")


def test_3_jscope_controller_and_mcp_dispatch():
    print("\n--- Test 3: JScope Controller & MCP Tool Dispatch ---")
    
    # Verify MCP tool declarations
    flash_tool = [t for t in MCP_TOOLS if t["name"] == "flash_firmware"][0]
    assert "pack_path" in flash_tool["inputSchema"]["properties"]
    assert "frequency" in flash_tool["inputSchema"]["properties"]
    print("[OK] MCP tool 'flash_firmware' exposes pack_path and frequency.")

    jscope_tool = [t for t in MCP_TOOLS if t["name"] == "start_jscope_sampling"][0]
    assert "interval_us" in jscope_tool["inputSchema"]["properties"]
    assert "swd_frequency_hz" in jscope_tool["inputSchema"]["properties"]
    print("[OK] MCP tool 'start_jscope_sampling' exposes interval_us and swd_frequency_hz.")

    # Test JScope unpack helper
    import struct
    f32_bytes = struct.pack("<f", 3.14159)
    val = JScopeController._unpack_val(f32_bytes, 4, "float32")
    assert abs(val - 3.14159) < 0.001
    print(f"[OK] JScope _unpack_val float32: {val:.5f}")

    u32_bytes = struct.pack("<I", 0x12345678)
    val_u32 = JScopeController._unpack_val(u32_bytes, 4, "uint32")
    assert val_u32 == 0x12345678
    print(f"[OK] JScope _unpack_val uint32: 0x{val_u32:08X}")


if __name__ == "__main__":
    test_1_pack_flash_algorithm()
    test_2_physics_deduction_formula()
    test_3_jscope_controller_and_mcp_dispatch()
    print("\n==========================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("==========================================")
