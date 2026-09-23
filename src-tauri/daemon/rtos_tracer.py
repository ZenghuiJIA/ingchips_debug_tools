#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTOS Kernel & Task Detective Engine:
Automatically detects the underlying RTOS (FreeRTOS, RTX5, ThreadX, uCOS-II, uCOS-III, RT-Thread)
from firmware ELF/AXF symbol tables and extracts task lists, priorities, and stack consumption.
"""

import os
import sys
import struct
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hil_daemon.rtos")

try:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection
    ELFTOOLS_AVAILABLE = True
except Exception as e:
    logger.warning(f"pyelftools import warning in rtos_tracer: {e}")
    ELFTOOLS_AVAILABLE = False


class RtosTracer:
    """Non-intrusive RTOS Detection & Inspection Engine."""

    # Characteristic symbol signatures for various RTOSes
    RTOS_SIGNATURES = {
        "FreeRTOS": ["pxReadyTasksLists", "pxCurrentTCB", "uxCurrentNumberOfTasks", "xSchedulerRunning"],
        "RTX5": ["osRtxInfo", "osRtxConfig", "os_idle_thread_cb"],
        "ThreadX": ["_tx_thread_created_ptr", "_tx_thread_current_ptr", "_tx_timer_system_clock"],
        "uCOS-II": ["OSTCBTbl", "OSTCBCur", "OSCPUUsage", "OSTaskCtr"],
        "uCOS-III": ["OSTaskDbgListPtr", "OSTCBCurPtr", "OSCfg_ISRStk"],
        "RT-Thread": ["rt_thread_priority_table", "rt_current_thread", "rt_object_container"],
    }

    @classmethod
    def detect_rtos_from_elf(cls, elf_path: str) -> Dict[str, Any]:
        """
        Scans ELF/AXF symbol tables to identify active RTOS and locate key control blocks.
        """
        if not ELFTOOLS_AVAILABLE or not elf_path or not os.path.exists(elf_path):
            return {
                "detected": False,
                "rtos_type": "Unknown",
                "matched_symbols": {},
                "error": "ELF file does not exist or pyelftools not available."
            }

        try:
            with open(elf_path, "rb") as f:
                elf = ELFFile(f)
                symtab = None
                for sec in elf.iter_sections():
                    if isinstance(sec, SymbolTableSection):
                        symtab = sec
                        break

                if not symtab:
                    return {
                        "detected": False,
                        "rtos_type": "None (No Symbol Table)",
                        "matched_symbols": {},
                    }

                found_symbols: Dict[str, int] = {}
                for sym in symtab.iter_symbols():
                    if sym.name:
                        found_symbols[sym.name] = sym["st_value"]

                # Match against RTOS signatures
                scores: Dict[str, int] = {}
                for rtos_name, sig_list in cls.RTOS_SIGNATURES.items():
                    score = sum(1 for s in sig_list if s in found_symbols)
                    scores[rtos_name] = score

                best_rtos = max(scores, key=scores.get)
                best_score = scores[best_rtos]

                if best_score > 0:
                    matched = {
                        s: f"0x{found_symbols[s]:08X}"
                        for s in cls.RTOS_SIGNATURES[best_rtos]
                        if s in found_symbols
                    }
                    return {
                        "detected": True,
                        "rtos_type": best_rtos,
                        "confidence": f"{best_score}/{len(cls.RTOS_SIGNATURES[best_rtos])}",
                        "matched_symbols": matched,
                        "all_rtos_scores": scores,
                    }
                else:
                    return {
                        "detected": False,
                        "rtos_type": "Bare Metal / Custom OS",
                        "matched_symbols": {},
                        "all_rtos_scores": scores,
                    }
        except Exception as e:
            logger.error(f"Error scanning ELF for RTOS signatures: {e}")
            return {
                "detected": False,
                "rtos_type": "Error",
                "error": str(e),
                "matched_symbols": {}
            }
