#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression test for RTOS Detection & Inspection Engine across real-world compiler firmware binaries.
Uses the gold standard test fixtures in test_fixtures/elf_demo/.
"""

import os
import sys
from pathlib import Path

# Add daemon directory to sys.path
DAEMON_DIR = Path(__file__).resolve().parent.parent / "src-tauri" / "daemon"
sys.path.insert(0, str(DAEMON_DIR))

from rtos_tracer import RtosTracer

TEST_DIR = Path(__file__).resolve().parent.parent / "test_fixtures" / "elf_demo"

def run_tests():
    print("=" * 60)
    print(" Running RTOS Firmware Detective Tests across ELF/AXF Samples")
    print("=" * 60)

    test_matrix = [
        ("rtx5.axf", "RTX5"),
        ("V7_RTX5OpenCache.axf", "RTX5"),
        ("threadx.axf", "ThreadX"),
        ("V7_ThreadXOpenCache.axf", "ThreadX"),
        ("uCOS-III.axf", "uCOS-III"),
        ("V7_uCOS-IIIOpenCache.axf", "uCOS-III"),
        ("V7_UCOS-II.axf", "uCOS-II"),
    ]

    all_passed = True
    for filename, expected_rtos in test_matrix:
        file_path = TEST_DIR / filename
        if not file_path.exists():
            print(f"[-] SKIP: {filename} not found.")
            continue

        res = RtosTracer.detect_rtos_from_elf(str(file_path))
        detected_rtos = res.get("rtos_type")
        is_match = (detected_rtos == expected_rtos)

        status_str = "[PASS]" if is_match else "[FAIL]"
        print(f"{status_str} File: {filename:<26} -> Detected: {detected_rtos:<10} (Expected: {expected_rtos})")
        if not is_match:
            print(f"       Details: {res}")
            all_passed = False
        else:
            print(f"       Symbols: {list(res['matched_symbols'].keys())}")

    print("=" * 60)
    if all_passed:
        print("[SUCCESS] All RTOS test fixture regressions PASSED!")
    else:
        print("[FAILED] Some RTOS test fixtures did not match expected signatures.")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
