#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HardFaultAnalyzer:
Advanced ARM Cortex-M HardFault Diagnostic & Call Stack Analysis Engine.
- Decodes EXC_RETURN to determine active stack pointer (MSP vs PSP)
- Extracts hardware exception stack frame (Stacked PC, LR, R0-R3, R12, xPSR)
- Unwinds and traces call stacks for both MSP and PSP
- Resolves code addresses to source file and line number using DWARF line tables (address2line)
- Disassembles Thumb/Thumb-2 machine instructions using Capstone 5.0 with crash PC highlighting
"""

import os
import sys
import struct
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hil_daemon.hardfault")

try:
    import capstone
    CAPSTONE_AVAILABLE = True
except Exception as e:
    logger.warning(f"Capstone import warning: {e}")
    CAPSTONE_AVAILABLE = False

try:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection
    ELFTOOLS_AVAILABLE = True
except Exception as e:
    logger.warning(f"pyelftools import warning: {e}")
    ELFTOOLS_AVAILABLE = False


class HardFaultAnalyzer:
    """
    Cortex-M HardFault & Exception Stack Analyzer.
    """

    @classmethod
    def decode_exc_return(cls, lr: int) -> Dict[str, Any]:
        """
        Decode Cortex-M EXC_RETURN value in LR register.
        Bit 0: Reserved (1)
        Bit 1: Reserved (0 on M3/M4/M7, 1 on others)
        Bit 2: Stack pointer used to restore state:
               0 = Main Stack Pointer (MSP)
               1 = Process Stack Pointer (PSP)
        Bit 3: Execution mode return:
               0 = Handler Mode (nested exception)
               1 = Thread Mode
        Bit 4: Stack frame type:
               0 = Extended Floating Point Frame (26 words / 104 bytes: S0-S15, FPSCR stacked)
               1 = Standard Frame (8 words / 32 bytes)
        """
        is_psp = bool(lr & 0x04)
        is_thread = bool(lr & 0x08)
        is_standard_frame = bool(lr & 0x10)

        stack_name = "PSP" if is_psp else "MSP"
        mode_name = "Thread Mode (线程/任务模式)" if is_thread else "Handler Mode (中断/异常嵌套模式)"
        frame_type = "标准 8 寄存器栈帧 (32 字节)" if is_standard_frame else "FPU 浮点扩展 26 寄存器栈帧 (104 字节)"

        desc = f"发生故障时运行在 {stack_name} ({mode_name})，使用 {frame_type}"
        return {
            "raw_hex": f"0x{lr:08X}",
            "active_sp_name": stack_name,
            "is_psp": is_psp,
            "is_thread_mode": is_thread,
            "is_handler": not is_thread,
            "is_standard_frame": is_standard_frame,
            "has_fpu_frame": not is_standard_frame,
            "mode_name": mode_name,
            "frame_type": frame_type,
            "description": desc,
        }

    @classmethod
    def extract_exception_frame(cls, target, sp_val: int, has_fpu: bool = False) -> Dict[str, Any]:
        """
        Extract the Cortex-M hardware exception frame pushed by hardware onto active SP.
        Frame layout:
        +0x00: R0
        +0x04: R1
        +0x08: R2
        +0x0C: R3
        +0x10: R12
        +0x14: LR (return address of caller function before exception)
        +0x18: PC (address of instruction that generated the exception!)
        +0x1C: xPSR
        """
        word_count = 26 if has_fpu else 8
        try:
            words = target.read_memory_block32(sp_val, word_count)
        except Exception as e:
            logger.warning(f"Failed to read exception frame at 0x{sp_val:08X}: {e}")
            words = [0] * word_count

        r0 = words[0] if len(words) > 0 else 0
        r1 = words[1] if len(words) > 1 else 0
        r2 = words[2] if len(words) > 2 else 0
        r3 = words[3] if len(words) > 3 else 0
        r12 = words[4] if len(words) > 4 else 0
        lr = words[5] if len(words) > 5 else 0
        pc = words[6] if len(words) > 6 else 0
        xpsr = words[7] if len(words) > 7 else 0

        clean_pc = pc & ~1
        clean_lr = lr & ~1

        return {
            "sp_address": f"0x{sp_val:08X}",
            "stacked_r0": f"0x{r0:08X}",
            "stacked_r1": f"0x{r1:08X}",
            "stacked_r2": f"0x{r2:08X}",
            "stacked_r3": f"0x{r3:08X}",
            "stacked_r12": f"0x{r12:08X}",
            "stacked_lr": f"0x{lr:08X}",
            "stacked_pc": f"0x{pc:08X}",
            "stacked_xpsr": f"0x{xpsr:08X}",
            # Standard names matching frontend interface
            "r0": f"0x{r0:08X}",
            "r1": f"0x{r1:08X}",
            "r2": f"0x{r2:08X}",
            "r3": f"0x{r3:08X}",
            "r12": f"0x{r12:08X}",
            "lr": f"0x{lr:08X}",
            "pc": f"0x{pc:08X}",
            "xpsr": f"0x{xpsr:08X}",
            "raw_words": [f"0x{w:08X}" for w in words],
            "pc_val": clean_pc,
            "lr_val": clean_lr,
            "sp_val": sp_val,
        }

    @classmethod
    def load_axf_context(cls, axf_path: str) -> Optional[Dict[str, Any]]:
        """
        Load symbols, code segments, and DWARF line table entries from AXF/ELF file.
        """
        if not ELFTOOLS_AVAILABLE or not axf_path or not os.path.exists(axf_path):
            return None

        try:
            with open(axf_path, "rb") as f:
                elf = ELFFile(f)

                # 1. Code segments (PT_LOAD with execute flag or .text sections)
                code_ranges: List[Tuple[int, int]] = []
                for seg in elf.iter_segments():
                    if seg["p_type"] == "PT_LOAD" and (seg["p_flags"] & 1):  # PF_X = 1
                        code_ranges.append((seg["p_vaddr"], seg["p_vaddr"] + seg["p_memsz"]))

                if not code_ranges:
                    for sec in elf.iter_sections():
                        if sec.name in (".text", "ER_ROM") or (sec["sh_flags"] & 4):  # SHF_EXECINSTR = 4
                            code_ranges.append((sec["sh_addr"], sec["sh_addr"] + sec["sh_size"]))

                # 2. Function Symbols
                func_symbols: List[Dict[str, Any]] = []
                symtab = None
                for sec in elf.iter_sections():
                    if isinstance(sec, SymbolTableSection):
                        symtab = sec
                        break

                if symtab:
                    for sym in symtab.iter_symbols():
                        if sym["st_info"]["type"] == "STT_FUNC" and sym["st_size"] > 0:
                            raw_val = sym["st_value"] & ~1  # Clear Thumb bit
                            func_symbols.append({
                                "name": sym.name,
                                "start": raw_val,
                                "end": raw_val + sym["st_size"],
                                "size": sym["st_size"],
                            })
                    func_symbols.sort(key=lambda s: s["start"])

                # 3. DWARF Line Programs Cache
                line_entries: List[Dict[str, Any]] = []
                if elf.has_dwarf_info():
                    dwarf = elf.get_dwarf_info()
                    for cu in dwarf.iter_CUs():
                        lp = dwarf.line_program_for_CU(cu)
                        if not lp:
                            continue
                        
                        file_entries = lp.header["file_entry"]
                        dir_entries = lp.header.get("include_directory", [])

                        prev_entry = None
                        for entry in lp.get_entries():
                            state = entry.state
                            if state and not state.end_sequence:
                                if prev_entry:
                                    p_state = prev_entry.state
                                    f_idx = p_state.file - 1
                                    fname = "unknown"
                                    fdir = ""
                                    if 0 <= f_idx < len(file_entries):
                                        fe = file_entries[f_idx]
                                        fname = fe.name.decode("utf-8", "ignore")
                                        if fe.dir_index > 0 and (fe.dir_index - 1) < len(dir_entries):
                                            fdir = dir_entries[fe.dir_index - 1].decode("utf-8", "ignore")

                                    full_path = os.path.normpath(os.path.join(fdir, fname)) if fdir else fname
                                    line_entries.append({
                                        "start": p_state.address,
                                        "end": state.address,
                                        "file": full_path,
                                        "file_name": os.path.basename(full_path),
                                        "line": p_state.line,
                                        "column": p_state.column,
                                    })
                                prev_entry = entry
                            elif state and state.end_sequence:
                                prev_entry = None

                    line_entries.sort(key=lambda e: e["start"])

                return {
                    "axf_path": axf_path,
                    "axf_name": os.path.basename(axf_path),
                    "code_ranges": code_ranges,
                    "func_symbols": func_symbols,
                    "line_entries": line_entries,
                }
        except Exception as e:
            logger.error(f"Error loading AXF context {axf_path}: {e}")
            return None

    @classmethod
    def resolve_address(cls, addr: int, axf_ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        address2line: Resolve code address to function name, offset, source file, and line number.
        """
        clean_addr = addr & ~1  # Strip Thumb bit
        result = {
            "address": f"0x{addr:08X}",
            "clean_address": f"0x{clean_addr:08X}",
            "clean_addr": clean_addr,
            "func_name": "unknown_function",
            "offset": 0,
            "offset_str": "+0x0",
            "file": None,
            "file_name": None,
            "line": None,
            "column": None,
            "source_snippet": None,
        }

        if not axf_ctx:
            return result

        # 1. Match Function Symbol
        func_symbols = axf_ctx.get("func_symbols", [])
        for sym in func_symbols:
            if sym["start"] <= clean_addr < sym["end"]:
                result["func_name"] = sym["name"]
                result["offset"] = clean_addr - sym["start"]
                result["offset_str"] = f"+0x{result['offset']:X}"
                break

        # 2. Match DWARF Line Number
        line_entries = axf_ctx.get("line_entries", [])
        # Binary or linear search
        for le in line_entries:
            if le["start"] <= clean_addr < le["end"]:
                result["file"] = le["file"]
                result["file_name"] = le["file_name"]
                result["line"] = le["line"]
                result["column"] = le["column"]
                break

        # 3. Read Local Source Snippet if file exists
        if result["file"] and result["line"]:
            snippet = cls._get_source_snippet(result["file"], result["line"])
            if snippet:
                result["source_snippet"] = snippet

        return result

    @classmethod
    def _get_source_snippet(cls, file_path: str, line_no: int, radius: int = 4) -> Optional[List[Dict[str, Any]]]:
        """Read surrounding source lines from local file if accessible."""
        if not file_path:
            return None
        # Try relative or absolute path
        candidates = [file_path]
        if not os.path.isabs(file_path):
            candidates.append(os.path.abspath(file_path))

        target_file = None
        for c in candidates:
            if os.path.exists(c) and os.path.isfile(c):
                target_file = c
                break

        if not target_file:
            return None

        try:
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()

            start_idx = max(0, line_no - 1 - radius)
            end_idx = min(len(all_lines), line_no + radius)
            snippet = []
            for idx in range(start_idx, end_idx):
                curr_line = idx + 1
                snippet.append({
                    "line": curr_line,
                    "code": all_lines[idx].rstrip("\r\n"),
                    "is_fault_line": (curr_line == line_no),
                })
            return snippet
        except Exception as e:
            logger.debug(f"Failed to read snippet for {target_file}: {e}")
            return None

    @classmethod
    def disassemble_code(cls, target, addr: int, count_instructions: int = 10, axf_ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Disassemble Thumb/Thumb-2 instructions around target address using Capstone 5.0.
        Highlights the instruction matching addr.
        """
        if not CAPSTONE_AVAILABLE:
            return []

        clean_addr = addr & ~1
        # Read 32 bytes before and 32 bytes after
        start_addr = max(0, clean_addr - 16)
        fetch_len = 48  # 48 bytes covers ~24 Thumb instructions

        code_bytes = None
        # Try reading from target hardware first
        if target:
            try:
                code_bytes = bytes(target.read_memory_block8(start_addr, fetch_len))
            except Exception as e:
                logger.debug(f"Target read memory for disasm failed at 0x{start_addr:08X}: {e}")

        # Fallback to reading from AXF file
        if not code_bytes and axf_ctx and axf_ctx.get("axf_path"):
            try:
                with open(axf_ctx["axf_path"], "rb") as f:
                    elf = ELFFile(f)
                    for seg in elf.iter_segments():
                        if seg["p_type"] == "PT_LOAD" and seg["p_vaddr"] <= start_addr < seg["p_vaddr"] + seg["p_filesz"]:
                            offset = start_addr - seg["p_vaddr"]
                            seg_data = seg.data()
                            code_bytes = seg_data[offset:offset + fetch_len]
                            break
            except Exception as e:
                logger.debug(f"AXF segment read for disasm failed: {e}")

        if not code_bytes:
            return []

        instructions = []
        try:
            md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
            md.detail = True
            for insn in md.disasm(code_bytes, start_addr):
                is_target = (insn.address == clean_addr)
                instructions.append({
                    "address": f"0x{insn.address:08X}",
                    "raw_address": insn.address,
                    "mnemonic": insn.mnemonic,
                    "op_str": insn.op_str,
                    "bytes": " ".join(f"{b:02X}" for b in insn.bytes),
                    "is_target": is_target,
                })
        except Exception as e:
            logger.warning(f"Capstone disassembly failed at 0x{start_addr:08X}: {e}")

        return instructions

    @classmethod
    def unwind_stack(cls, target, sp_val: int, max_words: int, is_active_stack: bool, exc_frame: Dict[str, Any], axf_ctx: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Unwind a stack (MSP or PSP) to extract the calling sequence.
        """
        frames: List[Dict[str, Any]] = []

        # Read stack words
        try:
            stack_words = target.read_memory_block32(sp_val, max_words)
        except Exception as e:
            logger.warning(f"Failed to read stack at 0x{sp_val:08X}: {e}")
            stack_words = []

        # Check code boundaries
        code_ranges = axf_ctx.get("code_ranges", []) if axf_ctx else []
        def is_in_code_range(val: int) -> bool:
            cval = val & ~1
            if code_ranges:
                return any(start <= cval < end for (start, end) in code_ranges)
            # Default typical Cortex-M Flash / ROM addresses
            return (0x00000000 <= cval < 0x20000000) or (0x08000000 <= cval < 0x08200000) or (0x02000000 <= cval < 0x02200000)

        frame_idx = 0

        # If this is the active stack, Frame #0 is the hardware stacked PC (where crash occurred)
        if is_active_stack and exc_frame.get("pc_val"):
            crash_pc = exc_frame["pc_val"]
            res = cls.resolve_address(crash_pc, axf_ctx)
            disasm = cls.disassemble_code(target, crash_pc, count_instructions=8, axf_ctx=axf_ctx)
            frames.append({
                "frame_index": frame_idx,
                "frame_idx": frame_idx,
                "role": "CRASH_PC",
                "label": "异常崩溃触发点 (Fault PC)",
                "address": f"0x{(sp_val + 24):08X}",
                "return_address": f"0x{crash_pc:08X}",
                "clean_address": res["clean_address"],
                "func_name": res["func_name"],
                "offset_str": res["offset_str"],
                "file": res["file"],
                "file_name": res["file_name"],
                "line": res["line"],
                "column": res["column"],
                "source_snippet": res["source_snippet"],
                "source_info": res,
                "disassembly": disasm,
                "stack_offset": "+0x18",
                "is_crash_instruction": True,
            })
            frame_idx += 1

            # Frame #1 is the stacked LR (caller return address)
            stacked_lr = exc_frame.get("lr_val", 0)
            if is_in_code_range(stacked_lr):
                res_lr = cls.resolve_address(stacked_lr, axf_ctx)
                disasm_lr = cls.disassemble_code(target, stacked_lr, count_instructions=6, axf_ctx=axf_ctx)
                frames.append({
                    "frame_index": frame_idx,
                    "frame_idx": frame_idx,
                    "role": "CALLER_LR",
                    "label": "直接调用者返回点 (Caller Return)",
                    "address": f"0x{(sp_val + 20):08X}",
                    "return_address": f"0x{stacked_lr:08X}",
                    "clean_address": res_lr["clean_address"],
                    "func_name": res_lr["func_name"],
                    "offset_str": res_lr["offset_str"],
                    "file": res_lr["file"],
                    "file_name": res_lr["file_name"],
                    "line": res_lr["line"],
                    "column": res_lr["column"],
                    "source_snippet": res_lr["source_snippet"],
                    "source_info": res_lr,
                    "disassembly": disasm_lr,
                    "stack_offset": "+0x14",
                    "is_crash_instruction": False,
                })
                frame_idx += 1

        # Now scan remaining stack words to reconstruct outer caller frames
        seen_addrs = set()
        if is_active_stack and exc_frame.get("pc_val"):
            seen_addrs.add(exc_frame["pc_val"] & ~1)
        if is_active_stack and exc_frame.get("lr_val"):
            seen_addrs.add(exc_frame["lr_val"] & ~1)

        # Skip the exception frame words if active stack
        start_word_idx = 8 if is_active_stack else 0
        for i in range(start_word_idx, len(stack_words)):
            w = stack_words[i]
            if (w & 1) and is_in_code_range(w):
                clean_w = w & ~1
                if clean_w in seen_addrs:
                    continue
                seen_addrs.add(clean_w)

                res = cls.resolve_address(w, axf_ctx)
                # Disassemble if not found source line or if it is first few frames
                disasm = cls.disassemble_code(target, w, count_instructions=5, axf_ctx=axf_ctx) if frame_idx < 4 or not res["line"] else []
                stack_offset_bytes = i * 4
                frames.append({
                    "frame_index": frame_idx,
                    "frame_idx": frame_idx,
                    "role": "STACK_FRAME",
                    "label": f"调用帧 #{frame_idx}",
                    "address": f"0x{(sp_val + stack_offset_bytes):08X}",
                    "return_address": f"0x{clean_w:08X}",
                    "clean_address": res["clean_address"],
                    "func_name": res["func_name"],
                    "offset_str": res["offset_str"],
                    "file": res["file"],
                    "file_name": res["file_name"],
                    "line": res["line"],
                    "column": res["column"],
                    "source_snippet": res["source_snippet"],
                    "source_info": res,
                    "disassembly": disasm,
                    "stack_offset": f"+0x{stack_offset_bytes:03X}",
                    "is_crash_instruction": False,
                })
                frame_idx += 1

                if frame_idx >= 25:  # Limit backtrace depth to 25 frames
                    break

        return frames

    @classmethod
    def diagnose_hardfault_deep(cls, session, core_regs: Dict[str, str], fault_regs: Dict[str, str],
                                cfsr_decoded: Dict[str, Any], hfsr_decoded: Dict[str, Any],
                                axf_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive HardFault diagnosis:
        - Decodes EXC_RETURN
        - Extracts hardware exception frame
        - Unwinds MSP & PSP call stacks
        - Resolves DWARF source lines
        - Disassembles Thumb-2 code
        """
        target = session.board.target

        # 1. Parse register values
        lr_str = core_regs.get("LR", "0x00000000")
        pc_str = core_regs.get("PC", "0x00000000")
        msp_str = core_regs.get("MSP", "0x00000000")
        psp_str = core_regs.get("PSP", "0x00000000")

        lr_val = int(lr_str, 16) if lr_str.startswith("0x") else 0
        pc_val = int(pc_str, 16) if pc_str.startswith("0x") else 0
        msp_val = int(msp_str, 16) if msp_str.startswith("0x") else 0
        psp_val = int(psp_str, 16) if psp_str.startswith("0x") else 0

        # 2. Decode EXC_RETURN
        exc_return_info = cls.decode_exc_return(lr_val)
        active_sp_name = exc_return_info["active_sp_name"]
        active_sp_val = psp_val if exc_return_info["is_psp"] else msp_val

        # 3. Extract hardware exception stack frame
        exc_frame = cls.extract_exception_frame(target, active_sp_val, has_fpu=exc_return_info["has_fpu_frame"])

        # 4. Load AXF context if provided
        axf_ctx = cls.load_axf_context(axf_path) if axf_path else None

        # 5. Unwind both stacks
        # Unwind PSP (usually thread task stack)
        psp_frames = cls.unwind_stack(
            target=target,
            sp_val=psp_val,
            max_words=256,
            is_active_stack=(active_sp_name == "PSP"),
            exc_frame=exc_frame,
            axf_ctx=axf_ctx
        )

        # Unwind MSP (usually interrupt/main stack)
        msp_frames = cls.unwind_stack(
            target=target,
            sp_val=msp_val,
            max_words=128,
            is_active_stack=(active_sp_name == "MSP"),
            exc_frame=exc_frame,
            axf_ctx=axf_ctx
        )

        # 6. Disassemble the crash PC instruction
        crash_pc = exc_frame["pc_val"] if exc_frame["pc_val"] != 0 else pc_val
        crash_disasm = cls.disassemble_code(target, crash_pc, count_instructions=8, axf_ctx=axf_ctx)
        crash_loc = cls.resolve_address(crash_pc, axf_ctx)

        # 7. Disassemble current PC in register (often HardFault_Handler loop)
        handler_disasm = cls.disassemble_code(target, pc_val, count_instructions=4, axf_ctx=axf_ctx) if pc_val != crash_pc else []

        # 8. Summary formulation
        active_stack_desc = (
            f"异常压栈指针: 【{active_sp_name}】 (地址: 0x{active_sp_val:08X})\n"
            f"EXC_RETURN: {exc_return_info['raw_hex']} ({exc_return_info['description']})"
        )

        crash_point_desc = (
            f"真实崩溃指令地址 (Stacked PC): 0x{crash_pc:08X} "
            f"({crash_loc['func_name']}{crash_loc['offset_str']})"
        )
        if crash_loc.get("file_name") and crash_loc.get("line"):
            crash_point_desc += f" -> {crash_loc['file_name']}:{crash_loc['line']}"

        return {
            "exc_return": exc_return_info,
            "active_sp_name": active_sp_name,
            "active_sp_val": f"0x{active_sp_val:08X}",
            "exception_frame": exc_frame,
            "crash_location": crash_loc,
            "crash_disassembly": crash_disasm,
            "handler_pc": f"0x{pc_val:08X}",
            "handler_disassembly": handler_disasm,
            "psp_call_stack": psp_frames,
            "msp_call_stack": msp_frames,
            "axf_loaded": bool(axf_ctx),
            "axf_path": axf_path,
            "active_stack_desc": active_stack_desc,
            "crash_point_desc": crash_point_desc,
        }
