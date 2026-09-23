#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test script for HardFaultAnalyzer & Deep Diagnostic Pipeline.
"""

import sys
import os
from pathlib import Path

# Add daemon directory to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DAEMON_DIR = PROJECT_ROOT / "src-tauri" / "daemon"
sys.path.insert(0, str(DAEMON_DIR))

from hardfault_analyzer import HardFaultAnalyzer

def test_exc_return_decoding():
    print("[1/5] Testing EXC_RETURN decoding...")
    # 0xFFFFFFFD: Return to Thread using PSP, Basic 8-word frame
    r1 = HardFaultAnalyzer.decode_exc_return(0xFFFFFFFD)
    assert r1["active_sp_name"] == "PSP", f"Expected PSP, got {r1['active_sp_name']}"
    assert not r1["is_handler"], "Expected Thread mode"
    assert not r1["has_fpu_frame"], "Expected no FPU frame"
    print(f"  0xFFFFFFFD -> {r1['active_sp_name']}, {r1['description']}")

    # 0xFFFFFFF9: Return to Thread using MSP, Basic 8-word frame
    r2 = HardFaultAnalyzer.decode_exc_return(0xFFFFFFF9)
    assert r2["active_sp_name"] == "MSP", f"Expected MSP, got {r2['active_sp_name']}"
    assert not r2["is_handler"], "Expected Thread mode"
    print(f"  0xFFFFFFF9 -> {r2['active_sp_name']}, {r2['description']}")

    # 0xFFFFFFE9: Return to Thread using MSP, FPU 26-word frame
    r3 = HardFaultAnalyzer.decode_exc_return(0xFFFFFFE9)
    assert r3["active_sp_name"] == "MSP"
    assert r3["has_fpu_frame"], "Expected FPU frame"
    print(f"  0xFFFFFFE9 -> {r3['active_sp_name']}, {r3['description']}")
    print("  [PASS] EXC_RETURN decoding verified.")

def test_capstone_thumb_disassembly():
    print("\n[2/5] Testing Capstone Thumb-2 disassembly...")
    # Thumb instructions:
    # 0x4802: ldr r0, [pc, #8]
    # 0x6801: ldr r1, [r0, #0]
    # 0x4770: bx lr
    # 0xbf00: nop
    sample_thumb = bytes([0x02, 0x48, 0x01, 0x68, 0x70, 0x47, 0x00, 0xbf])

    class MockTarget:
        def read_memory_block8(self, addr, size):
            return list(sample_thumb[:size])

    target = MockTarget()
    disasm = HardFaultAnalyzer.disassemble_code(target, addr=0x08001000, count_instructions=4)
    assert len(disasm) > 0, "Disassembly returned empty"
    print(f"  Disassembled {len(disasm)} instructions:")
    for ins in disasm:
        target_mark = "➔ " if ins["is_target"] else "  "
        print(f"    {target_mark}{ins['address']}: {ins['bytes']} {ins['mnemonic']} {ins['op_str']}")
    print("  [PASS] Capstone Thumb-2 disassembly verified.")

def test_axf_context_and_address2line():
    print("\n[3/5] Testing AXF symbol & DWARF address2line resolution...")
    sample_axf = Path(r"C:\ming\ING918XX_SDK_SOURCE\examples\data_logger\output\data_logger.axf")
    if not sample_axf.exists():
        print(f"  [SKIP] AXF file not found at {sample_axf}")
        return

    ctx = HardFaultAnalyzer.load_axf_context(str(sample_axf))
    assert ctx is not None, "Failed to load AXF context"
    print(f"  AXF Loaded: {len(ctx['func_symbols'])} symbols, {len(ctx['code_ranges'])} code ranges, {len(ctx['line_entries'])} line entries")

    # Pick a symbol from ctx['func_symbols'] to test resolve_address
    test_func = None
    for sym in ctx['func_symbols']:
        if sym['size'] > 4:
            test_func = sym
            break

    if test_func:
        name = test_func['name']
        start = test_func['start']
        mid_addr = start + 2
        loc = HardFaultAnalyzer.resolve_address(mid_addr, ctx)
        print(f"  Address 0x{mid_addr:08X} resolved to: {loc['func_name']}{loc['offset_str']}")
        if loc['file_name']:
            print(f"    File: {loc['file_name']}:{loc['line']}")
        assert loc['func_name'] == name, f"Expected {name}, got {loc['func_name']}"
    print("  [PASS] AXF context and address2line verified.")

def test_deep_diagnosis_end_to_end():
    print("\n[4/5] Testing end-to-end HardFault deep diagnosis with mock session...")
    sample_axf = Path(r"C:\ming\ING918XX_SDK_SOURCE\examples\data_logger\output\data_logger.axf")
    axf_path = str(sample_axf) if sample_axf.exists() else None

    # Load symbol to get real valid code addresses if axf exists
    crash_pc = 0x02008E12
    stacked_lr = 0x02008DFC
    if axf_path:
        ctx = HardFaultAnalyzer.load_axf_context(axf_path)
        if ctx and ctx["func_symbols"]:
            if len(ctx["func_symbols"]) >= 2:
                crash_pc = ctx["func_symbols"][0]["start"] + 4
                stacked_lr = ctx["func_symbols"][1]["start"] + 4

    class MockTarget:
        part_number = "ING9188xx"
        def read_memory_block8(self, addr, size):
            # Thumb NOPs (0xbf00)
            return [0x00, 0xbf] * (size // 2 + 1)

        def read_memory_block32(self, addr, count):
            # If reading active stack frame (e.g. 0x200021A0)
            # Standard exception frame: R0, R1, R2, R3, R12, LR, PC, xPSR
            if addr == 0x200021A0:
                frame = [0, 0, 0, 0, 0, stacked_lr | 1, crash_pc | 1, 0x61000000]
                # Followed by stack words
                extra = [stacked_lr | 1, 0x20000100, 0x00000000] * 20
                res = frame + extra
                return res[:count]
            return [crash_pc | 1, stacked_lr | 1, 0x20000000] * (count // 3 + 1)

    class MockBoard:
        target = MockTarget()

    class MockSession:
        board = MockBoard()

    session = MockSession()
    core_regs = {
        "PC": f"0x{crash_pc:08X}",
        "LR": "0xFFFFFFFD",
        "MSP": "0x20004FB0",
        "PSP": "0x200021A0",
        "SP": "0x20004FB0",
        "xPSR": "0x61000000"
    }
    fault_regs = {
        "CFSR": "0x00008200",
        "HFSR": "0x40000000",
        "MMFAR": "0x00000000",
        "BFAR": "0x4002101C"
    }
    cfsr_decoded = {
        "flags": ["PRECISERR", "BFARVALID"],
        "explanations": ["Precise bus error"]
    }
    hfsr_decoded = {
        "flags": ["FORCED"],
        "explanations": ["Forced HardFault"]
    }

    result = HardFaultAnalyzer.diagnose_hardfault_deep(
        session=session,
        core_regs=core_regs,
        fault_regs=fault_regs,
        cfsr_decoded=cfsr_decoded,
        hfsr_decoded=hfsr_decoded,
        axf_path=axf_path
    )

    assert result["active_sp_name"] == "PSP"
    assert result["exception_frame"]["pc_val"] == crash_pc
    assert len(result["psp_call_stack"]) > 0
    print(f"  Active SP: {result['active_sp_name']} ({result['active_sp_val']})")
    print(f"  Stacked PC: {result['exception_frame']['pc']}")
    print(f"  PSP Frames Found: {len(result['psp_call_stack'])}")
    for f in result["psp_call_stack"][:3]:
        print(f"    Frame #{f['frame_index']}: {f['return_address']} in {f['source_info']['func_name']}")
    print("  [PASS] End-to-end deep diagnosis verified.")

def test_daemon_entry_integration():
    print("\n[5/5] Testing daemon_entry dispatch_tool...")
    import daemon_entry
    # Check that diagnose_hardfault is registered in MCP_TOOLS
    tool_entry = next((t for t in daemon_entry.MCP_TOOLS if t["name"] == "diagnose_hardfault"), None)
    assert tool_entry is not None, "diagnose_hardfault tool missing from MCP_TOOLS"
    assert "axf_path" in tool_entry["inputSchema"]["properties"], "axf_path missing from tool properties"
    print(f"  MCP Tool 'diagnose_hardfault' properties: {list(tool_entry['inputSchema']['properties'].keys())}")
    print("  [PASS] daemon_entry tool schema verified.")

if __name__ == "__main__":
    print("=== Running HardFault & Memory Diagnostic Pipeline Tests ===")
    test_exc_return_decoding()
    test_capstone_thumb_disassembly()
    test_axf_context_and_address2line()
    test_deep_diagnosis_end_to_end()
    test_daemon_entry_integration()
    print("\nALL HARDFAULT & MEMORY TESTS PASSED SUCCESSFULLY! (5/5)")
