#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HIL Python Daemon - PyOCD & MCP Server Bridge
Communicates with Tauri Rust backend over JSON-RPC 2.0 via stdin/stdout.
"""

import sys
import os
import json
import logging
import gc
import traceback
from collections import defaultdict
from typing import Dict, Any, List, Optional

import threading
import socket
import time
import struct

# Configure stderr logging (stdout is reserved strictly for JSON-RPC)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[HIL-Daemon] %(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("hil_daemon")

try:
    import pyocd
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.session import Session
    from pyocd.core.target import Target
    from pyocd.flash.file_programmer import FileProgrammer
    PYOCD_AVAILABLE = True
except Exception as e:
    logger.warning(f"PyOCD import warning: {e}")
    PYOCD_AVAILABLE = False

try:
    import pylink
    PYLINK_AVAILABLE = True
except Exception as e:
    logger.warning(f"PyLink import warning: {e}")
    PYLINK_AVAILABLE = False

try:
    from pyocd.target.pack.cmsis_pack import CmsisPack
    from pyocd.target.pack.pack_target import PackTargets
    from pyocd.target import TARGET
    CMSIS_PACK_AVAILABLE = True
except Exception as e:
    logger.warning(f"CMSIS Pack import warning: {e}")
    CMSIS_PACK_AVAILABLE = False

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except Exception as e:
    logger.warning(f"pyserial import warning: {e}")
    SERIAL_AVAILABLE = False

_DISCOVERED_PACKS = []
_PACKS_LOCK = threading.Lock()

def get_primary_packs_dir() -> str:
    """Returns the primary packs directory alongside the executable or project root."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        primary = os.path.join(exe_dir, "packs")
    else:
        # Development mode
        script_dir = os.path.dirname(os.path.abspath(__file__))
        primary = os.path.join(script_dir, "..", "..", "packs")
    primary = os.path.abspath(primary)
    try:
        os.makedirs(primary, exist_ok=True)
    except Exception:
        pass
    return primary

def discover_and_load_packs() -> List[str]:
    """Find and dynamically populate targets & algorithms from .pack files in packs/ directories."""
    global _DISCOVERED_PACKS
    if not CMSIS_PACK_AVAILABLE:
        return []

    with _PACKS_LOCK:
        candidates = []
        candidates.append(get_primary_packs_dir())
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidates.append(os.path.join(exe_dir, "packs"))
            candidates.append(os.path.join(exe_dir, "..", "packs"))
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(script_dir, "packs"))
        candidates.append(os.path.join(script_dir, "..", "packs"))
        candidates.append(os.path.join(script_dir, "..", "..", "packs"))
        cwd = os.getcwd()
        candidates.append(os.path.join(cwd, "packs"))
        release_parent = os.path.join(cwd, "release")
        if os.path.isdir(release_parent):
            for rel_sub in os.listdir(release_parent):
                if rel_sub.startswith("AI-HIL-Debugger-"):
                    candidates.append(os.path.join(release_parent, rel_sub, "packs"))
        candidates.append(r"C:\ming\python\get_svd")

        for d in candidates:
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if fname.lower().endswith(".pack"):
                    p = os.path.abspath(os.path.join(d, fname))
                    if p not in _DISCOVERED_PACKS and os.path.isfile(p):
                        try:
                            PackTargets.populate_targets_from_pack(p)
                            _DISCOVERED_PACKS.append(p)
                            logger.info(f"Loaded CMSIS-Pack: {p}")
                        except Exception as e:
                            logger.error(f"Failed to populate targets from pack {p}: {e}")

        return list(_DISCOVERED_PACKS)


def normalize_target(target_name: Optional[str]) -> Optional[str]:
    """
    Normalize target MCU string to match PyOCD or J-Link supported targets.
    Fixes cases like:
    - 'cortex-m4', 'cortex_m4', 'cortex_m3', 'cortex-m0+' -> 'cortex_m'
    - 'ing200' -> 'ing2000'
    - Case-insensitive / hyphen-insensitive matching against registered PyOCD TARGETs
    """
    if not target_name:
        return None
    raw = target_name.strip().lower().replace("-", "_")

    # Common chip alias mapping
    alias_map = {
        "ing200": "ing2000",
        "ing_200": "ing2000",
        "ing_2000": "ing2000",
        "ing918": "ing91800",
        "ing_918": "ing91800",
        "ing_91800": "ing91800",
        "ing916": "ing91600",
        "ing_916": "ing91600",
        "ing_91600": "ing91600",
    }
    if raw in alias_map:
        raw = alias_map[raw]

    # Universal ARM Cortex-M targets
    if raw.startswith("cortex_m") or raw == "cortex_m" or raw in ("cortexm", "cortexm0", "cortexm3", "cortexm4", "cortexm7"):
        return "cortex_m"

    # Match against PyOCD registered targets if available
    try:
        from pyocd.target import TARGET
        # Direct match
        if raw in TARGET:
            return raw
        # Try raw without underscores
        no_under = raw.replace("_", "")
        if no_under in TARGET:
            return no_under
        # Fuzzy match registered targets
        for key in TARGET.keys():
            if key.lower().replace("-", "").replace("_", "") == no_under:
                return key
    except Exception:
        pass

    return raw


def trim_process_memory():
    """Trim memory footprint to stay well under memory budget."""
    gc.collect()
    try:
        import ctypes
        if sys.platform == "win32":
            ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
    except Exception:
        pass


def decode_shcsr(shcsr: int) -> Dict[str, Any]:
    """Decode Cortex-M SHCSR (System Handler Control and State Register 0xE000ED24)."""
    flags = []
    explanations = []

    if shcsr & (1 << 0):
        flags.append("MEMFAULTACT")
        explanations.append("MemFault 内存管理异常中断当前正处于活动触发状态 (Active)。")
    if shcsr & (1 << 1):
        flags.append("BUSFAULTACT")
        explanations.append("BusFault 总线异常中断当前正处于活动触发状态 (Active)。")
    if shcsr & (1 << 3):
        flags.append("USGFAULTACT")
        explanations.append("UsageFault 用法异常中断当前正处于活动触发状态 (Active)。")
    if shcsr & (1 << 7):
        flags.append("SVCALLACT")
        explanations.append("SVC 异常中断当前处于活动状态。")
    if shcsr & (1 << 8):
        flags.append("MONITORACT")
        explanations.append("Debug Monitor 调试监视异常当前处于活动状态。")
    if shcsr & (1 << 10):
        flags.append("PENDSVACT")
        explanations.append("PendSV 异常当前处于活动状态 (通常为 RTOS 上下文切换)。")
    if shcsr & (1 << 11):
        flags.append("SYSTICKACT")
        explanations.append("SysTick 滴答定时器异常当前处于活动状态。")

    # Pending bits
    if shcsr & (1 << 12):
        flags.append("USGFAULTPENDED")
        explanations.append("UsageFault 异常已被挂起 (Pending)。")
    if shcsr & (1 << 13):
        flags.append("MEMFAULTPENDED")
        explanations.append("MemFault 异常已被挂起 (Pending)。")
    if shcsr & (1 << 14):
        flags.append("BUSFAULTPENDED")
        explanations.append("BusFault 异常已被挂起 (Pending)。")

    # Enable bits
    mem_ena = bool(shcsr & (1 << 16))
    bus_ena = bool(shcsr & (1 << 17))
    usg_ena = bool(shcsr & (1 << 18))

    return {
        "raw_shcsr": f"0x{shcsr:08X}",
        "memfault_enabled": mem_ena,
        "busfault_enabled": bus_ena,
        "usgfault_enabled": usg_ena,
        "flags": flags,
        "explanations": explanations
    }


def decode_cfsr(cfsr: int, mmfar: int, bfar: int) -> Dict[str, Any]:
    """Decode Cortex-M CFSR (Configurable Fault Status Register 0xE000ED28)."""
    mmfsr = cfsr & 0xFF
    bfsr = (cfsr >> 8) & 0xFF
    ufsr = (cfsr >> 16) & 0xFFFF

    flags = []
    explanations = []

    # MemManage Faults
    if mmfsr & (1 << 0):
        flags.append("IACCVIOL")
        explanations.append("IACCVIOL: 指令访问违规。处理器试图从 MPU 未授权区域或不可执行 (XN) 内存区预取指令。")
    if mmfsr & (1 << 1):
        flags.append("DACCVIOL")
        explanations.append("DACCVIOL: 数据访问违规。处理器试图读写 MPU 限制区域或非法受保护内存。")
    if mmfsr & (1 << 3):
        flags.append("MUNSTKERR")
        explanations.append("MUNSTKERR: 异常返回出栈时发生 MemManage 内存违规。堆栈指针 SP 已损坏。")
    if mmfsr & (1 << 4):
        flags.append("MSTKERR")
        explanations.append("MSTKERR: 异常入栈操作时发生 MemManage 内存违规。堆栈溢出 (Stack Overflow) 触碰到 MPU 保护警戒线。")
    if mmfsr & (1 << 5):
        flags.append("MLSPERR")
        explanations.append("MLSPERR: 浮点 FPU 懒惰压栈 (Lazy Stacking) 期间发生 MemManage 内存违规。")
    if mmfsr & (1 << 7):
        flags.append(f"MMARVALID (Address: 0x{mmfar:08X})")
        explanations.append(f"MMARVALID: MMFAR 记录了发生内存访问违规的确切物理地址: 0x{mmfar:08X}。")

    # Bus Faults
    if bfsr & (1 << 0):
        flags.append("IBUSERR")
        explanations.append("IBUSERR: 指令总线错误。在指令预取时总线返回错误。常见原因：错误的函数指针调用、跳转至无效未映射地址。")
    if bfsr & (1 << 1):
        flags.append("PRECISERR")
        explanations.append(f"PRECISERR: 精确数据总线访问错误！堆栈 PC 正好指向引发崩溃的代码指令。常见原因：未使能外设时钟 (RCC) 即访问外设寄存器、解引用野指针。")
    if bfsr & (1 << 2):
        flags.append("IMPRECISERR")
        explanations.append("IMPRECISERR: 不精确数据总线访问错误 (异步写入总线缓冲导致)。建议：临时开启 CPU 禁用写缓冲 (DISDEFWBUF=1) 将其定位为精确错误。")
    if bfsr & (1 << 3):
        flags.append("UNSTKERR")
        explanations.append("UNSTKERR: 异常返回出栈操作时发生总线错误。通常由于堆栈溢出破坏了栈帧。")
    if bfsr & (1 << 4):
        flags.append("STKERR")
        explanations.append("STKERR: 中断入栈操作时发生总线错误。通常为堆栈指针 SP 跑飞越界访问非法 RAM 区域。")
    if bfsr & (1 << 5):
        flags.append("LSPERR")
        explanations.append("LSPERR: 浮点 FPU 懒惰压栈期间发生总线错误。")
    if bfsr & (1 << 7):
        flags.append(f"BFARVALID (Address: 0x{bfar:08X})")
        explanations.append(f"BFARVALID: BFAR 记录了发生总线错误的确切崩溃物理地址: 0x{bfar:08X}。排查重点：该外设的时钟是否开启？指针是否越界？")

    # Usage Faults
    if ufsr & (1 << 0):
        flags.append("UNDEFINSTR")
        explanations.append("UNDEFINSTR: 执行了未定义机器指令。常见原因：函数指针未置位 Thumb 位 (bit0 必须为1)、Flash 数据损坏或固件未对齐。")
    if ufsr & (1 << 1):
        flags.append("INVSTATE")
        explanations.append("INVSTATE: 非法执行状态。Cortex-M 只支持 Thumb 状态 (EPSR.T=1)，程序试图切换至 ARM 32位状态或向量表地址最低位为0。")
    if ufsr & (1 << 2):
        flags.append("INVPC")
        explanations.append("INVPC: 非法 EXC_RETURN 加载。异常返回时装载了非法的 LR 值，或中断返回模式与当前硬件状态冲突。")
    if ufsr & (1 << 3):
        flags.append("NOCP")
        explanations.append("NOCP: 尝试访问未开启的协处理器 (通常是硬件 FPU)。排查：编译开启了硬件浮点，但启动代码未在 SCB->CPACR 使能 CP10/CP11！")
    if ufsr & (1 << 8):
        flags.append("UNALIGNED")
        explanations.append("UNALIGNED: 非对齐内存访问引发异常 (CCR.UNALIGN_TRP 开启)。检查多字节指针强制转换是否 2/4 字节对齐。")
    if ufsr & (1 << 9):
        flags.append("DIVBYZERO")
        explanations.append("DIVBYZERO: 除以零异常 (CCR.DIV_0_TRP 开启)。程序执行了 SDIV 或 UDIV 指令且除数为 0。")

    return {
        "raw_cfsr": f"0x{cfsr:08X}",
        "mmfsr": f"0x{mmfsr:02X}",
        "bfsr": f"0x{bfsr:02X}",
        "ufsr": f"0x{ufsr:04X}",
        "flags": flags,
        "explanations": explanations
    }


def decode_hfsr(hfsr: int) -> Dict[str, Any]:
    """Decode Cortex-M HFSR (HardFault Status Register 0xE000ED2C)."""
    flags = []
    explanations = []

    if hfsr & (1 << 1):
        flags.append("VECTTBL")
        explanations.append("VECTTBL: 在异常向量表读取期间发生总线错误。向量表起始基地址 (VTOR) 配置错误或指向了无效 Flash/RAM。")
    if hfsr & (1 << 30):
        flags.append("FORCED")
        explanations.append("FORCED: 强制升级为 HardFault！原本由可配置异常 (MemManage, BusFault, UsageFault) 引发，但因未开启相应中断使能或中断优先级不足而被强制升级。请重点检查 CFSR 中的根本原因。")
    if hfsr & (1 << 31):
        flags.append("DEBUGEVT")
        explanations.append("DEBUGEVT: 调试事件引发的硬故障 (断点或观察点触发)。")

    return {
        "raw_hfsr": f"0x{hfsr:08X}",
        "flags": flags,
        "explanations": explanations
    }


class PyOCDController:
    """Controller for PyOCD hardware operations."""

    @classmethod
    def _create_session(cls, probe_id: Optional[str] = None, target_override: Optional[str] = None,
                        auto_open: bool = True, pack: Optional[str] = None, frequency: Optional[int] = None):
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available.")
        discover_and_load_packs()
        if pack and os.path.isfile(pack):
            try:
                from pyocd.target.pack.pack_target import PackTargets
                PackTargets.populate_targets_from_pack(pack)
                logger.info(f"Session populating targets from pack: {pack}")
            except Exception as e:
                logger.warning(f"Could not populate targets from pack {pack}: {e}")
        probes = ConnectHelper.get_all_connected_probes(blocking=False, unique_id=probe_id)
        if not probes:
            target_msg = f" matching ID '{probe_id}'" if probe_id else ""
            raise RuntimeError(f"No debug probe connected{target_msg}.")
        probe = probes[0]
        options = {}
        if target_override:
            options["target_override"] = normalize_target(target_override)
        if pack:
            options["pack"] = pack
        if frequency:
            options["frequency"] = int(frequency)
        return Session(probe, auto_open=auto_open, options=options)

    @staticmethod
    def list_probes() -> List[Dict[str, Any]]:
        if not PYOCD_AVAILABLE:
            return []
        try:
            probes = ConnectHelper.get_all_connected_probes(blocking=False)
            result = []
            for p in probes:
                cls_name = type(p).__name__.lower()
                desc = getattr(p, "description", "").lower()
                vendor = getattr(p, "vendor_name", "").lower()
                product = getattr(p, "product_name", "").lower()

                if "jlink" in cls_name or "jlink" in desc or "segger" in vendor or "segger" in desc:
                    probe_type = "jlink"
                    type_label = "J-Link"
                elif "cmsis" in cls_name or "dap" in cls_name or "cmsis" in desc or "dap" in desc:
                    probe_type = "daplink"
                    type_label = "CMSIS-DAP"
                elif "stlink" in cls_name or "stlink" in desc:
                    probe_type = "stlink"
                    type_label = "ST-Link"
                else:
                    probe_type = "generic"
                    type_label = "SWD/JTAG Probe"

                result.append({
                    "unique_id": p.unique_id,
                    "description": p.description,
                    "vendor_name": getattr(p, "vendor_name", ""),
                    "product_name": getattr(p, "product_name", ""),
                    "probe_type": probe_type,
                    "type_label": type_label,
                })
            return result
        except Exception as e:
            logger.error(f"Error listing probes: {e}")
            return []

    @staticmethod
    def read_core_registers(probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            was_running = target.is_running()
            if was_running:
                target.halt()

            # Standard ARM Cortex-M core registers
            reg_names = [f"r{i}" for i in range(13)] + ["sp", "lr", "pc", "xpsr", "msp", "psp"]
            core_regs = {}
            for name in reg_names:
                try:
                    val = target.read_core_register(name)
                    core_regs[name.upper()] = f"0x{val:08X}"
                except Exception:
                    core_regs[name.upper()] = "N/A"

            # SCB Fault Status Registers
            SCB_CFSR  = 0xE000ED28
            SCB_HFSR  = 0xE000ED2C
            SCB_MMFAR = 0xE000ED34
            SCB_BFAR  = 0xE000ED38

            cfsr = target.read32(SCB_CFSR)
            hfsr = target.read32(SCB_HFSR)
            mmfar = target.read32(SCB_MMFAR)
            bfar = target.read32(SCB_BFAR)

            cfsr_decoded = decode_cfsr(cfsr, mmfar, bfar)
            hfsr_decoded = decode_hfsr(hfsr)

            # Auto resume if it was originally running
            if was_running:
                try:
                    target.resume()
                except Exception:
                    pass

            return {
                "target": target.part_number or "Cortex-M",
                "core_registers": core_regs,
                "fault_registers": {
                    "CFSR": f"0x{cfsr:08X}",
                    "HFSR": f"0x{hfsr:08X}",
                    "MMFAR": f"0x{mmfar:08X}",
                    "BFAR": f"0x{bfar:08X}",
                },
                "cfsr_decoded": cfsr_decoded,
                "hfsr_decoded": hfsr_decoded,
            }

    @staticmethod
    def read_memory(address: int, count: int, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        count = min(count, 4096)  # Cap at 4KB
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            data = target.read_memory_block8(address, count)
            hex_dump = " ".join(f"{b:02X}" for b in data)
            return {
                "address": f"0x{address:08X}",
                "count": count,
                "bytes": list(data),
                "hex_dump": hex_dump
            }

    @staticmethod
    def write_memory(address: int, value: int, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            target.write32(address, value)
            return {"address": f"0x{address:08X}", "value": f"0x{value:08X}", "status": "success"}

    @staticmethod
    def write_memory_byte(address: int, value: int, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            target.write8(address, value & 0xFF)
            return {"address": f"0x{address:08X}", "value": f"0x{value & 0xFF:02X}", "status": "success"}

    @staticmethod
    def dump_memory_to_file(address: int, count: int, file_path: str, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            chunk_size = 4096
            bytes_written = 0
            with open(file_path, "wb") as f:
                while bytes_written < count:
                    to_read = min(chunk_size, count - bytes_written)
                    chunk = target.read_memory_block8(address + bytes_written, to_read)
                    f.write(bytes(chunk))
                    bytes_written += to_read

            return {
                "status": "success",
                "address": f"0x{address:08X}",
                "count": bytes_written,
                "file_path": file_path
            }

    @staticmethod
    def load_file_to_memory(address: int, file_path: str, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        with open(file_path, "rb") as f:
            data = f.read()

        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            chunk_size = 4096
            written = 0
            while written < len(data):
                chunk = list(data[written:written + chunk_size])
                target.write_memory_block8(address + written, chunk)
                written += len(chunk)

            return {
                "status": "success",
                "address": f"0x{address:08X}",
                "count": len(data),
                "file_path": file_path
            }

    @staticmethod
    def reset_target(halt: bool = False, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            if halt:
                target.reset_and_halt()
            else:
                target.reset()
            return {"status": "success", "halted": halt}

    @staticmethod
    def flash_firmware(file_path: str, target_override: Optional[str] = None, probe_id: Optional[str] = None,
                       pack_path: Optional[str] = None, frequency: Optional[int] = None) -> Dict[str, Any]:
        session = PyOCDController._create_session(probe_id, target_override, pack=pack_path, frequency=frequency)
        with session:
            programmer = FileProgrammer(session)
            programmer.program(file_path)
            session.board.target.reset()
            trim_process_memory()
            pack_desc = f" (using pack: {os.path.basename(pack_path)})" if pack_path else ""
            freq_desc = f" @ {frequency // 1_000_000}MHz" if frequency and frequency >= 1_000_000 else ""
            return {
                "status": "success",
                "file_path": file_path,
                "pack_path": pack_path,
                "message": f"Flashing and reset completed successfully{pack_desc}{freq_desc}."
            }

    @staticmethod
    def diagnose_hardfault(probe_id: Optional[str] = None, target_override: Optional[str] = None, axf_path: Optional[str] = None) -> Dict[str, Any]:
        """Comprehensive HardFault diagnosis with call stack unwinding, EXC_RETURN decode, and address2line."""
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            was_running = target.is_running()
            if was_running:
                target.halt()

            # Standard ARM Cortex-M core registers
            reg_names = [f"r{i}" for i in range(13)] + ["sp", "lr", "pc", "xpsr", "msp", "psp"]
            core_regs = {}
            for name in reg_names:
                try:
                    val = target.read_core_register(name)
                    core_regs[name.upper()] = f"0x{val:08X}"
                except Exception:
                    core_regs[name.upper()] = "N/A"

            # SCB Fault Status Registers
            SCB_SHCSR = 0xE000ED24
            SCB_CFSR  = 0xE000ED28
            SCB_HFSR  = 0xE000ED2C
            SCB_MMFAR = 0xE000ED34
            SCB_BFAR  = 0xE000ED38

            shcsr = target.read32(SCB_SHCSR)
            cfsr = target.read32(SCB_CFSR)
            hfsr = target.read32(SCB_HFSR)
            mmfar = target.read32(SCB_MMFAR)
            bfar = target.read32(SCB_BFAR)

            shcsr_decoded = decode_shcsr(shcsr)
            cfsr_decoded = decode_cfsr(cfsr, mmfar, bfar)
            hfsr_decoded = decode_hfsr(hfsr)

            regs_info = {
                "target": target.part_number or "Cortex-M",
                "core_registers": core_regs,
                "fault_registers": {
                    "SHCSR": f"0x{shcsr:08X}",
                    "CFSR": f"0x{cfsr:08X}",
                    "HFSR": f"0x{hfsr:08X}",
                    "MMFAR": f"0x{mmfar:08X}",
                    "BFAR": f"0x{bfar:08X}",
                },
                "shcsr_decoded": shcsr_decoded,
                "cfsr_decoded": cfsr_decoded,
                "hfsr_decoded": hfsr_decoded,
            }

            deep_analysis = None
            try:
                from hardfault_analyzer import HardFaultAnalyzer
                deep_analysis = HardFaultAnalyzer.diagnose_hardfault_deep(
                    session=session,
                    core_regs=core_regs,
                    fault_regs=regs_info["fault_registers"],
                    cfsr_decoded=cfsr_decoded,
                    hfsr_decoded=hfsr_decoded,
                    axf_path=axf_path
                )
            except Exception as ex:
                logger.error(f"Error performing deep HardFault analysis: {ex}", exc_info=True)
                deep_analysis = {"error": str(ex)}

            if was_running:
                try:
                    target.resume()
                except Exception:
                    pass

        pc = core_regs.get("PC", "0x00000000")
        lr = core_regs.get("LR", "0x00000000")
        msp = core_regs.get("MSP", "0x00000000")
        psp = core_regs.get("PSP", "0x00000000")
        bfar = regs_info["fault_registers"].get("BFAR", "0x00000000")

        # Compile AI diagnostic summary
        diagnosis_lines = []
        diagnosis_lines.append("=== Cortex-M HardFault 智能分析诊断报告 ===")
        diagnosis_lines.append(f"当前程序计数器 (PC): {pc}")
        diagnosis_lines.append(f"返回链接寄存器 (LR/EXC_RETURN): {lr}")
        diagnosis_lines.append(f"主栈指针 (MSP): {msp}")
        diagnosis_lines.append(f"进程栈指针 (PSP): {psp}")

        if deep_analysis and deep_analysis.get("active_stack_desc"):
            diagnosis_lines.append(f"• {deep_analysis['active_stack_desc']}")
        if deep_analysis and deep_analysis.get("crash_point_desc"):
            diagnosis_lines.append(f"• {deep_analysis['crash_point_desc']}")

        if "FORCED" in hfsr_decoded.get("flags", []):
            diagnosis_lines.append("• 故障类型: 强制硬故障 (Forced HardFault)，由低级故障升级触发。")

        if cfsr_decoded.get("flags"):
            diagnosis_lines.append(f"• 触发状态标志: {', '.join(cfsr_decoded['flags'])}")
            for exp in cfsr_decoded.get("explanations", []):
                diagnosis_lines.append(f"  - {exp}")
        else:
            diagnosis_lines.append("• 未检测到可配置故障标志 (CFSR=0)，可能是中断向量表错误或非法指令栈破坏。")

        # Specific recommendations
        recommendations = []
        cfsr_flags_str = " ".join(cfsr_decoded.get("flags", []))
        if "BFARVALID" in cfsr_flags_str:
            recommendations.append(f"检查对地址 {bfar} 的读写操作：确认对应外设时钟（如 RCC_APB1/2/AHB）是否已在代码中使能。")
        if "INVSTATE" in cfsr_flags_str:
            recommendations.append("检查函数指针跳转：ARM Cortex-M 仅支持 Thumb 模式，请确保函数指针地址的最低有效位 (LSB) 为 1。")
        if "UNALIGNED" in cfsr_flags_str:
            recommendations.append("检查结构体或数据指针对齐：是否存在未对齐的 32 位内存访问。")
        if "NOCP" in cfsr_flags_str:
            recommendations.append("浮点运算协处理器未使能：若在中断中使用了浮点计算，请在初始化时开启 SCB->CPACR 的 CP10 与 CP11 访问权限。")

        result = {
            "summary": "\n".join(diagnosis_lines),
            "recommendations": recommendations,
            "raw_dump": regs_info
        }
        if deep_analysis:
            result["deep_analysis"] = deep_analysis
        return result

    @staticmethod
    def detect_rtos_kernel(elf_path: str) -> Dict[str, Any]:
        """Detect underlying RTOS and inspect kernel symbol blocks from ELF/AXF file."""
        from rtos_tracer import RtosTracer
        return RtosTracer.detect_rtos_from_elf(elf_path)

    @staticmethod
    def capture_lcd_framebuffer(address: int, width: int, height: int, pixel_format: str = "rgb565",
                                probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        """Capture LCD display buffer from MCU RAM and convert to PNG Base64."""
        from lcd_mirror import LcdMirror
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            return LcdMirror.capture_framebuffer(target, address, width, height, pixel_format)


class RTTController:
    """
    Segger RTT Controller supporting both J-Link (via pylink-square) and DAPLink (via PyOCD).
    Exposes a local TCP socket bridge so Tauri or any terminal can stream bi-directional RTT traffic.
    """
    _lock = threading.Lock()
    _running = False
    _thread = None
    _server_sock = None
    _client_sock = None
    _tcp_port = 0

    _mode = None  # 'jlink' or 'pyocd'
    _jlink = None
    _session = None

    _ram_start = 0x20000000
    _ram_size = 0x20000
    _block_address = None

    @classmethod
    def start_rtt(cls, probe_id: Optional[str] = None, target_override: Optional[str] = None,
                  block_address: Optional[int] = None, probe_type: Optional[str] = None,
                  ram_start: Optional[int] = None, ram_size: Optional[int] = None) -> Dict[str, Any]:
        with cls._lock:
            if cls._running:
                return {
                    "status": "already_running",
                    "tcp_port": cls._tcp_port,
                    "mode": cls._mode
                }

            cls._block_address = block_address
            cls._ram_start = int(ram_start) if ram_start is not None else 0x20000000
            cls._ram_size = max(0x1000, int(ram_size) if ram_size is not None else 0x20000)

            # Create ephemeral TCP server for bi-directional streaming
            cls._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            cls._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            cls._server_sock.bind(("127.0.0.1", 0))
            cls._server_sock.listen(1)
            cls._tcp_port = cls._server_sock.getsockname()[1]

            # Decide probe type if not specified
            chosen_type = (probe_type or "").lower()
            if not chosen_type:
                for p in PyOCDController.list_probes():
                    if not probe_id or p["unique_id"] == probe_id:
                        chosen_type = p.get("probe_type", "generic")
                        break

            cls._running = True

            if chosen_type == "jlink" and PYLINK_AVAILABLE:
                try:
                    cls._start_jlink(probe_id, target_override, block_address)
                    cls._mode = "jlink"
                except Exception as e:
                    logger.warning(f"J-Link RTT start failed, trying PyOCD fallback: {e}")
                    cls._start_pyocd(probe_id, target_override, block_address)
                    cls._mode = "pyocd"
            else:
                cls._start_pyocd(probe_id, target_override, block_address)
                cls._mode = "pyocd"

            # Launch background streaming worker thread
            cls._thread = threading.Thread(target=cls._rtt_worker_loop, daemon=True)
            cls._thread.start()

            return {
                "status": "started",
                "tcp_port": cls._tcp_port,
                "mode": cls._mode,
                "probe_type": chosen_type,
                "ram_start": f"0x{cls._ram_start:08X}",
                "ram_size": f"0x{cls._ram_size:X}"
            }

    @classmethod
    def _start_jlink(cls, probe_id: Optional[str], target_override: Optional[str], block_address: Optional[int]):
        cls._jlink = pylink.JLink()
        if probe_id and probe_id.isdigit():
            cls._jlink.open(int(probe_id))
        else:
            cls._jlink.open()

        chip = normalize_target(target_override) or "cortex_m"
        cls._jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
        cls._jlink.connect(chip)
        cb_addr = block_address if block_address else cls._block_address
        cls._jlink.rtt_start(cb_addr)
        logger.info(f"J-Link RTT started on target {chip} (CB addr: {cb_addr})")

    @classmethod
    def _start_pyocd(cls, probe_id: Optional[str], target_override: Optional[str], block_address: Optional[int]):
        norm_target = normalize_target(target_override) or "cortex_m"
        cls._session = PyOCDController._create_session(probe_id, norm_target, auto_open=True)
        cls._session.open()
        logger.info(f"PyOCD session opened for RTT on target {norm_target}")

    @classmethod
    def _rtt_worker_loop(cls):
        """Worker thread that accepts TCP client and pumps bytes between RTT and TCP socket."""
        logger.info(f"RTT TCP Bridge listening on 127.0.0.1:{cls._tcp_port}")
        cls._server_sock.settimeout(3.0)

        # 1. Accept client connection (Rust backend or local tool)
        client = None
        while cls._running:
            try:
                client, addr = cls._server_sock.accept()
                logger.info(f"RTT TCP Bridge connected by client: {addr}")
                client.setblocking(False)
                cls._client_sock = client
                break
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error accepting RTT TCP client: {e}")
                break

        if not client:
            logger.warning("No RTT client connected, shutting down worker.")
            cls.stop_rtt()
            return

        # 2. RTT streaming loop
        cb_address = cls._block_address
        up_buf_ptr = None
        up_buf_size = 0

        while cls._running:
            try:
                # A. Read outgoing RTT data from Target MCU -> send to TCP Client
                if cls._mode == "jlink" and cls._jlink:
                    try:
                        data = cls._jlink.rtt_read(0, 1024)
                        if data:
                            client.sendall(bytes(data))
                    except Exception as e:
                        logger.debug(f"JLink RTT read error: {e}")

                elif cls._mode == "pyocd" and cls._session:
                    target = cls._session.board.target
                    if cb_address is None:
                        # Scan RAM range for "SEGGER RTT" signature in chunks (up to cls._ram_size)
                        try:
                            start_ram = cls._ram_start
                            total_len = cls._ram_size
                            chunk_size = 0x8000  # 32KB per scan chunk
                            offset = 0

                            while offset < total_len and cb_address is None:
                                cur_addr = start_ram + offset
                                cur_len = min(chunk_size, total_len - offset)
                                words = target.read_memory_block32(cur_addr, cur_len // 4)
                                raw_bytes = bytearray()
                                for w in words:
                                    raw_bytes.extend(w.to_bytes(4, 'little'))
                                magic_idx = raw_bytes.find(b"SEGGER RTT")
                                if magic_idx != -1:
                                    cb_address = cur_addr + magic_idx
                                    up_buf_ptr = int.from_bytes(raw_bytes[magic_idx+28:magic_idx+32], 'little')
                                    up_buf_size = int.from_bytes(raw_bytes[magic_idx+32:magic_idx+36], 'little')
                                    logger.info(f"PyOCD found SEGGER RTT CB at 0x{cb_address:08X} (UpBuffer: 0x{up_buf_ptr:08X}, size {up_buf_size}B)")
                                    break
                                offset += cur_len
                        except Exception as e:
                            logger.debug(f"Scanning for RTT CB failed: {e}")

                    if cb_address and up_buf_ptr and up_buf_size > 0:
                        try:
                            # Read WrOff and RdOff: offset 24 + 12 = 36 from cb_address
                            wr_off = target.read32(cb_address + 36)
                            rd_off = target.read32(cb_address + 40)
                            if wr_off != rd_off:
                                if wr_off > rd_off:
                                    to_read = wr_off - rd_off
                                    data = target.read_memory_block8(up_buf_ptr + rd_off, to_read)
                                    target.write32(cb_address + 40, wr_off)
                                else:
                                    to_read1 = up_buf_size - rd_off
                                    d1 = target.read_memory_block8(up_buf_ptr + rd_off, to_read1)
                                    d2 = target.read_memory_block8(up_buf_ptr, wr_off) if wr_off > 0 else []
                                    data = d1 + d2
                                    target.write32(cb_address + 40, wr_off)

                                if data:
                                    client.sendall(bytes(data))
                        except Exception as e:
                            logger.debug(f"PyOCD RTT read cycle: {e}")

                # B. Read incoming data from TCP Client -> write into Target MCU RTT Down Buffer
                try:
                    client_data = client.recv(1024)
                    if client_data:
                        if cls._mode == "jlink" and cls._jlink:
                            cls._jlink.rtt_write(0, list(client_data))
                except (BlockingIOError, socket.error):
                    pass

                time.sleep(0.01)  # 10ms polling interval
            except Exception as e:
                logger.error(f"RTT streaming loop exception: {e}")
                break

        logger.info("RTT worker loop finished.")
        cls.stop_rtt()

    @classmethod
    def stop_rtt(cls) -> Dict[str, Any]:
        with cls._lock:
            cls._running = False
            if cls._client_sock:
                try:
                    cls._client_sock.close()
                except Exception:
                    pass
                cls._client_sock = None

            if cls._server_sock:
                try:
                    cls._server_sock.close()
                except Exception:
                    pass
                cls._server_sock = None

            if cls._jlink:
                try:
                    cls._jlink.rtt_stop()
                    cls._jlink.close()
                except Exception:
                    pass
                cls._jlink = None

            if cls._session:
                try:
                    cls._session.close()
                except Exception:
                    pass
                cls._session = None

            cls._tcp_port = 0
            cls._mode = None
            trim_process_memory()
            return {"status": "stopped"}


def format_bytes(size: int) -> str:
    """Format byte size into human-readable string."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    else:
        return f"{size / (1024 * 1024):.2f} MB"


class FirmwareResourceAnalyzer:
    """
    Analyzes embedded ARM Cortex-M firmware (.axf / .elf / binary ELF) for total RAM/ROM footprint,
    compiler toolchain detection (GCC, ARMCC, ARMClang), section layout, and module-level attribution.
    """

    @staticmethod
    def analyze(
        file_path: str,
        chip_flash_size: Optional[int] = None,
        chip_ram_size: Optional[int] = None,
        max_symbols_per_module: int = 25
    ) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Firmware file not found: {file_path}")

        from map_analyzer import MapFileAnalyzer
        if file_path.lower().endswith(".map") or MapFileAnalyzer.is_map_file(file_path):
            return MapFileAnalyzer.analyze(file_path, chip_flash_size, chip_ram_size, max_symbols_per_module)

        # Check for companion .map file
        base_name = os.path.splitext(file_path)[0]
        dir_name = os.path.dirname(file_path)
        candidates = [
            base_name + ".map",
            os.path.join(dir_name, "listing", os.path.basename(base_name) + ".map"),
            os.path.join(dir_name, "..", "listing", os.path.basename(base_name) + ".map")
        ]
        for c in candidates:
            if os.path.isfile(c):
                try:
                    logger.info(f"Found companion map file for {file_path}: {c}")
                    res = MapFileAnalyzer.analyze(c, chip_flash_size, chip_ram_size, max_symbols_per_module)
                    res["file_path"] = file_path
                    res["file_name"] = os.path.basename(file_path)
                    return res
                except Exception as e:
                    logger.warning(f"Failed to parse companion map {c}: {e}, falling back to ELF parser")

        try:
            from elftools.elf.elffile import ELFFile
            from elftools.elf.sections import SymbolTableSection
        except ImportError:
            raise RuntimeError("pyelftools is not installed in Python daemon.")

        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        file_name = os.path.basename(file_path)

        with open(file_path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF":
                raise ValueError(f"Invalid ELF/AXF binary: header magic is {magic!r}, expected '\\x7fELF'")
            f.seek(0)
            elf = ELFFile(f)

            # 1. Toolchain & Architecture Detection
            toolchain_type = "generic"
            toolchain_name = "Generic ELF Toolchain"
            raw_producer = ""

            comment_sec = elf.get_section_by_name(".comment")
            if comment_sec:
                try:
                    cdata = comment_sec.data().decode("utf-8", errors="ignore")
                    first_line = cdata.split("\n")[0].split("\x00")[0].strip()
                    raw_producer = first_line
                    if "GCC" in cdata or "GNU" in cdata:
                        toolchain_type = "gcc"
                        toolchain_name = f"GNU Arm GCC ({first_line})"
                    elif "ARM Compiler for Embedded 6" in cdata or "armclang" in cdata:
                        toolchain_type = "armclang"
                        toolchain_name = "Arm Compiler 6 (armclang)"
                    elif "ARM Compiler 5" in cdata or "ArmLink" in cdata or "ARM Linker" in cdata:
                        toolchain_type = "armcc"
                        toolchain_name = "Arm Compiler 5 (armcc / armlink)"
                except Exception:
                    pass

            if elf.has_dwarf_info():
                try:
                    di = elf.get_dwarf_info()
                    for cu in di.iter_CUs():
                        top_die = cu.get_top_DIE()
                        prod = top_die.attributes.get("DW_AT_producer")
                        if prod:
                            p_val = prod.value.decode("utf-8", errors="ignore")
                            if not raw_producer:
                                raw_producer = p_val
                            if toolchain_type == "generic":
                                if "GNU" in p_val or "GCC" in p_val:
                                    toolchain_type = "gcc"
                                    toolchain_name = f"GNU GCC ({p_val[:60]})"
                                elif "Arm Compiler 6" in p_val or "clang" in p_val:
                                    toolchain_type = "armclang"
                                    toolchain_name = "Arm Compiler 6 (armclang)"
                                elif "ARM Compiler" in p_val or "ArmC" in p_val:
                                    toolchain_type = "armcc"
                                    toolchain_name = "Arm Compiler 5 (armcc)"
                            break
                except Exception:
                    pass

            arch = elf.header.get("e_machine", "EM_ARM")
            arch_name = "ARM Cortex-M" if arch == "EM_ARM" else str(arch)

            # 2. Section Classification
            sections_info = []
            code_bytes = 0
            ro_data_bytes = 0
            rw_data_bytes = 0
            zi_data_bytes = 0

            for s in elf.iter_sections():
                name = s.name
                size = s["sh_size"]
                flags = s["sh_flags"]
                stype = s["sh_type"]
                addr = s["sh_addr"]

                if size == 0:
                    continue

                alloc = bool(flags & 0x2)      # SHF_ALLOC
                exec_instr = bool(flags & 0x4) # SHF_EXECINSTR
                write = bool(flags & 0x1)      # SHF_WRITE

                category = "Other"
                target = "None"

                if alloc:
                    if exec_instr:
                        category = "Code"
                        target = "ROM"
                        code_bytes += size
                    elif write:
                        if stype == "SHT_NOBITS":
                            category = "ZI-Data"
                            target = "RAM"
                            zi_data_bytes += size
                        else:
                            category = "RW-Data"
                            target = "ROM+RAM"
                            rw_data_bytes += size
                    else:
                        category = "RO-Data"
                        target = "ROM"
                        ro_data_bytes += size

                flags_str = ""
                if alloc: flags_str += "A"
                if write: flags_str += "W"
                if exec_instr: flags_str += "X"

                sections_info.append({
                    "name": name or f"[sec_{len(sections_info)}]",
                    "type": stype,
                    "address": f"0x{addr:08X}",
                    "raw_address": addr,
                    "size": size,
                    "size_str": format_bytes(size),
                    "flags": flags_str,
                    "category": category,
                    "target": target
                })

            rom_total_bytes = code_bytes + ro_data_bytes + rw_data_bytes
            ram_total_bytes = rw_data_bytes + zi_data_bytes

            # 3. DWARF Compile Unit Indexing (Range Map)
            cu_func_ranges = []
            if elf.has_dwarf_info():
                try:
                    di = elf.get_dwarf_info()
                    for cu in di.iter_CUs():
                        top_die = cu.get_top_DIE()
                        name_attr = top_die.attributes.get("DW_AT_name")
                        if not name_attr:
                            continue
                        full_path = name_attr.value.decode("utf-8", errors="ignore").replace("\\", "/")
                        file_base = os.path.basename(full_path)

                        for die in cu.iter_DIEs():
                            if die.tag == "DW_TAG_subprogram":
                                low = die.attributes.get("DW_AT_low_pc")
                                high = die.attributes.get("DW_AT_high_pc")
                                if low and high:
                                    l_val = low.value
                                    h_val = high.value
                                    if getattr(high, "form", "").startswith("DW_FORM_data"):
                                        h_val = l_val + h_val
                                    cu_func_ranges.append((l_val, h_val, file_base, full_path))
                except Exception:
                    pass

            cu_func_ranges.sort(key=lambda x: x[0])

            def find_cu_for_address(addr: int) -> Optional[tuple]:
                for l_val, h_val, f_base, f_path in cu_func_ranges:
                    if l_val <= addr < h_val:
                        return f_base, f_path
                return None

            # 4. Symbol & Module Attribution
            modules_map = defaultdict(lambda: {
                "name": "",
                "full_path": "",
                "code": 0,
                "ro_data": 0,
                "rw_data": 0,
                "zi_data": 0,
                "symbols": []
            })

            symtab = None
            for s in elf.iter_sections():
                if isinstance(s, SymbolTableSection):
                    symtab = s
                    break

            current_file_base = "system_lib"
            current_file_path = "[System / Core Library]"
            total_symbols_count = 0

            if symtab:
                for sym in symtab.iter_symbols():
                    st_type = sym["st_info"]["type"]
                    st_size = sym["st_size"]
                    st_value = sym["st_value"]
                    name = sym.name

                    if not name or name.startswith("$"):
                        continue

                    if st_type == "STT_FILE":
                        current_file_path = name.replace("\\", "/")
                        current_file_base = os.path.basename(current_file_path)
                        continue

                    if st_size > 0:
                        shndx = sym["st_shndx"]
                        if isinstance(shndx, int) and shndx < elf.num_sections():
                            sec = elf.get_section(shndx)
                            flags = sec["sh_flags"]
                            stype = sec["sh_type"]

                            alloc = bool(flags & 0x2)
                            exec_instr = bool(flags & 0x4)
                            write = bool(flags & 0x1)

                            if alloc:
                                total_symbols_count += 1
                                target_file_base = current_file_base
                                target_file_path = current_file_path

                                if exec_instr:
                                    matched_cu = find_cu_for_address(st_value)
                                    if matched_cu:
                                        target_file_base, target_file_path = matched_cu

                                mod_entry = modules_map[target_file_base]
                                mod_entry["name"] = target_file_base
                                if not mod_entry["full_path"] or mod_entry["full_path"] == "[System / Core Library]":
                                    mod_entry["full_path"] = target_file_path

                                sym_category = "Other"
                                if exec_instr:
                                    mod_entry["code"] += st_size
                                    sym_category = "Code"
                                elif write:
                                    if stype == "SHT_NOBITS":
                                        mod_entry["zi_data"] += st_size
                                        sym_category = "ZI-Data"
                                    else:
                                        mod_entry["rw_data"] += st_size
                                        sym_category = "RW-Data"
                                else:
                                    mod_entry["ro_data"] += st_size
                                    sym_category = "RO-Data"

                                mod_entry["symbols"].append({
                                    "name": name,
                                    "kind": "func" if exec_instr else "object",
                                    "address": f"0x{st_value:08X}",
                                    "raw_address": st_value,
                                    "size": st_size,
                                    "size_str": format_bytes(st_size),
                                    "category": sym_category
                                })

            module_list = []
            for mod_key, mod_val in modules_map.items():
                m_code = mod_val["code"]
                m_ro = mod_val["ro_data"]
                m_rw = mod_val["rw_data"]
                m_zi = mod_val["zi_data"]
                m_rom = m_code + m_ro + m_rw
                m_ram = m_rw + m_zi

                mod_symbols = sorted(mod_val["symbols"], key=lambda s: s["size"], reverse=True)

                module_list.append({
                    "name": mod_val["name"] or mod_key,
                    "full_path": mod_val["full_path"] or mod_key,
                    "code": m_code,
                    "ro_data": m_ro,
                    "rw_data": m_rw,
                    "zi_data": m_zi,
                    "rom_total": m_rom,
                    "ram_total": m_ram,
                    "code_str": format_bytes(m_code),
                    "ro_data_str": format_bytes(m_ro),
                    "rw_data_str": format_bytes(m_rw),
                    "zi_data_str": format_bytes(m_zi),
                    "rom_total_str": format_bytes(m_rom),
                    "ram_total_str": format_bytes(m_ram),
                    "rom_percent": round((m_rom / rom_total_bytes * 100), 2) if rom_total_bytes > 0 else 0.0,
                    "ram_percent": round((m_ram / ram_total_bytes * 100), 2) if ram_total_bytes > 0 else 0.0,
                    "symbols_count": len(mod_symbols),
                    "symbols": mod_symbols[:max_symbols_per_module]
                })

            module_list.sort(key=lambda m: m["rom_total"], reverse=True)

            flash_usage_percent = None
            ram_usage_percent = None
            flash_free_bytes = None
            ram_free_bytes = None

            if chip_flash_size and chip_flash_size > 0:
                flash_usage_percent = round((rom_total_bytes / chip_flash_size) * 100, 2)
                flash_free_bytes = max(0, chip_flash_size - rom_total_bytes)

            if chip_ram_size and chip_ram_size > 0:
                ram_usage_percent = round((ram_total_bytes / chip_ram_size) * 100, 2)
                ram_free_bytes = max(0, chip_ram_size - ram_total_bytes)

            summary = {
                "code_bytes": code_bytes,
                "ro_data_bytes": ro_data_bytes,
                "rw_data_bytes": rw_data_bytes,
                "zi_data_bytes": zi_data_bytes,
                "rom_total_bytes": rom_total_bytes,
                "ram_total_bytes": ram_total_bytes,
                "code_str": format_bytes(code_bytes),
                "ro_data_str": format_bytes(ro_data_bytes),
                "rw_data_str": format_bytes(rw_data_bytes),
                "zi_data_str": format_bytes(zi_data_bytes),
                "rom_total_str": format_bytes(rom_total_bytes),
                "ram_total_str": format_bytes(ram_total_bytes),
                "rom_code_ratio": round(code_bytes / rom_total_bytes * 100, 1) if rom_total_bytes > 0 else 0.0,
                "rom_ro_ratio": round(ro_data_bytes / rom_total_bytes * 100, 1) if rom_total_bytes > 0 else 0.0,
                "rom_rw_ratio": round(rw_data_bytes / rom_total_bytes * 100, 1) if rom_total_bytes > 0 else 0.0,
                "ram_rw_ratio": round(rw_data_bytes / ram_total_bytes * 100, 1) if ram_total_bytes > 0 else 0.0,
                "ram_zi_ratio": round(zi_data_bytes / ram_total_bytes * 100, 1) if ram_total_bytes > 0 else 0.0,
                "chip_flash_size": chip_flash_size,
                "chip_ram_size": chip_ram_size,
                "chip_flash_str": format_bytes(chip_flash_size) if chip_flash_size else None,
                "chip_ram_str": format_bytes(chip_ram_size) if chip_ram_size else None,
                "flash_usage_percent": flash_usage_percent,
                "ram_usage_percent": ram_usage_percent,
                "flash_free_bytes": flash_free_bytes,
                "ram_free_bytes": ram_free_bytes,
                "flash_free_str": format_bytes(flash_free_bytes) if flash_free_bytes is not None else None,
                "ram_free_str": format_bytes(ram_free_bytes) if ram_free_bytes is not None else None,
                "padding_total": 0,
                "padding_total_str": "0 B",
                "parse_status": {"warnings": 0, "inferred": 0, "format": "ELF / DWARF"}
            }

            # Top metrics
            all_funcs = []
            all_objs = []
            for m in module_list:
                for s in m.get("symbols", []):
                    if s.get("type") in ("Function", "Code"):
                        all_funcs.append(s)
                    else:
                        all_objs.append(s)
            all_funcs.sort(key=lambda x: x.get("size", 0), reverse=True)
            all_objs.sort(key=lambda x: x.get("size", 0), reverse=True)

            top_metrics = {
                "max_function": all_funcs[0] if all_funcs else {"name": "N/A", "size": 0, "size_str": "0 B"},
                "max_object": all_objs[0] if all_objs else {"name": "N/A", "size": 0, "size_str": "0 B"},
                "total_padding": {"size": 0, "size_str": "0 B"},
                "heap_stack_gap": {"size": max(0, ram_free_bytes or 0), "size_str": format_bytes(ram_free_bytes or 0), "low_margin": (ram_free_bytes or 0) < 2048}
            }

            # Treemap
            flash_treemap = {
                "name": "FLASH",
                "size": rom_total_bytes,
                "categories": [
                    {
                        "name": ".text (Code)",
                        "type": "code",
                        "color": "#3b82f6",
                        "size": code_bytes,
                        "size_str": format_bytes(code_bytes),
                        "percent": summary["rom_code_ratio"],
                        "items": [{"name": m["name"], "size": m["code"], "size_str": m["code_str"], "type": "code", "object": m["full_path"]} for m in module_list if m["code"] > 0][:12]
                    },
                    {
                        "name": ".rodata (RO)",
                        "type": "ro",
                        "color": "#a855f7",
                        "size": ro_data_bytes,
                        "size_str": format_bytes(ro_data_bytes),
                        "percent": summary["rom_ro_ratio"],
                        "items": [{"name": m["name"], "size": m["ro_data"], "size_str": m["ro_data_str"], "type": "ro", "object": m["full_path"]} for m in module_list if m["ro_data"] > 0][:12]
                    },
                    {
                        "name": ".data_init (RW)",
                        "type": "rw",
                        "color": "#f97316",
                        "size": rw_data_bytes,
                        "size_str": format_bytes(rw_data_bytes),
                        "percent": summary["rom_rw_ratio"],
                        "items": [{"name": m["name"], "size": m["rw_data"], "size_str": m["rw_data_str"], "type": "rw", "object": m["full_path"]} for m in module_list if m["rw_data"] > 0][:8]
                    },
                    {
                        "name": "Padding",
                        "type": "padding",
                        "color": "#64748b",
                        "size": 0,
                        "size_str": "0 B",
                        "percent": 0.0,
                        "items": []
                    }
                ]
            }

            ram_treemap = {
                "name": "RAM",
                "size": ram_total_bytes,
                "categories": [
                    {
                        "name": ".data (RW)",
                        "type": "rw",
                        "color": "#f97316",
                        "size": rw_data_bytes,
                        "size_str": format_bytes(rw_data_bytes),
                        "percent": summary["ram_rw_ratio"],
                        "items": [{"name": m["name"], "size": m["rw_data"], "size_str": m["rw_data_str"], "type": "rw", "object": m["full_path"]} for m in module_list if m["rw_data"] > 0][:8]
                    },
                    {
                        "name": ".bss (ZI)",
                        "type": "zi",
                        "color": "#22c55e",
                        "size": zi_data_bytes,
                        "size_str": format_bytes(zi_data_bytes),
                        "percent": summary["ram_zi_ratio"],
                        "items": [{"name": m["name"], "size": m["zi_data"], "size_str": m["zi_data_str"], "type": "zi", "object": m["full_path"]} for m in module_list if m["zi_data"] > 0][:12]
                    },
                    {
                        "name": "Free Gap (可用)",
                        "type": "free",
                        "color": "#1e293b",
                        "size": max(0, ram_free_bytes or 0),
                        "size_str": format_bytes(ram_free_bytes or 0),
                        "percent": round(max(0, ram_free_bytes or 0) / (chip_ram_size or 65536) * 100, 1),
                        "items": [{"name": "未分配自由 SRAM", "size": max(0, ram_free_bytes or 0), "size_str": format_bytes(ram_free_bytes or 0), "type": "free", "object": "System RAM"}]
                    }
                ]
            }

            # Linear memory
            flash_blocks = [
                {"name": s["name"], "start": s["address"], "size": s["size"], "size_str": s["size_str"], "type": s["category"].lower().replace("-", "_"), "section": s["name"], "object": s.get("object", "")}
                for s in sections_info if s.get("target") in ("ROM", "ROM+RAM") and s.get("size", 0) > 0
            ]
            ram_blocks = [
                {"name": ".data (RW)", "type": "rw", "size": rw_data_bytes, "size_str": format_bytes(rw_data_bytes), "growth": "none"},
                {"name": ".bss (ZI)", "type": "zi", "size": zi_data_bytes, "size_str": format_bytes(zi_data_bytes), "growth": "none"},
                {"name": f"Free Gap ({format_bytes(ram_free_bytes or 0)})", "type": "free", "size": max(0, ram_free_bytes or 0), "size_str": format_bytes(ram_free_bytes or 0), "warning": (ram_free_bytes or 0) < 2048, "growth": "none"}
            ]

            hierarchy_tree = [
                {
                    "id": "flash",
                    "label": "FLASH",
                    "size": rom_total_bytes,
                    "size_str": format_bytes(rom_total_bytes),
                    "type": "region",
                    "children": [
                        {"id": "flash_code", "label": ".text (代码)", "size": code_bytes, "size_str": format_bytes(code_bytes), "type": "code"},
                        {"id": "flash_ro", "label": ".rodata (只读数据)", "size": ro_data_bytes, "size_str": format_bytes(ro_data_bytes), "type": "ro"},
                        {"id": "flash_rw_init", "label": ".data_init (数据初值)", "size": rw_data_bytes, "size_str": format_bytes(rw_data_bytes), "type": "rw"}
                    ]
                },
                {
                    "id": "ram",
                    "label": "RAM",
                    "size": ram_total_bytes,
                    "size_str": format_bytes(ram_total_bytes),
                    "type": "region",
                    "children": [
                        {"id": "ram_data", "label": ".data (全局变量)", "size": rw_data_bytes, "size_str": format_bytes(rw_data_bytes), "type": "rw"},
                        {"id": "ram_bss", "label": ".bss (零初始化)", "size": zi_data_bytes, "size_str": format_bytes(zi_data_bytes), "type": "zi"},
                        {"id": "ram_free", "label": "Free Gap (空闲)", "size": max(0, ram_free_bytes or 0), "size_str": format_bytes(ram_free_bytes or 0), "type": "free"}
                    ]
                }
            ]

            trim_process_memory()

            return {
                "file_path": file_path,
                "file_name": file_name,
                "file_size": file_size,
                "file_size_str": format_bytes(file_size),
                "toolchain": {
                    "type": toolchain_type,
                    "name": toolchain_name,
                    "raw_producer": raw_producer
                },
                "architecture": arch_name,
                "summary": summary,
                "top_metrics": top_metrics,
                "linear_memory": {
                    "flash_base": "0x00000000",
                    "flash_end": f"0x{rom_total_bytes:08X}",
                    "flash_blocks": flash_blocks[:60],
                    "ram_base": "0x20000000",
                    "ram_end": f"0x{(0x20000000 + (chip_ram_size or 65536)):08X}",
                    "ram_blocks": ram_blocks
                },
                "treemap": {
                    "flash": flash_treemap,
                    "ram": ram_treemap
                },
                "hierarchy": hierarchy_tree,
                "sections": sections_info,
                "modules": module_list,
                "total_modules_count": len(module_list),
                "total_symbols_count": total_symbols_count
            }


class AxfSymbolParser:
    """
    Parser for Keil MDK .axf and GCC .elf files using pyelftools.
    Extracts global and static variables located in RAM with name, address, size and suggested type.
    """
    @staticmethod
    def parse_symbols(file_path: str, filter_keyword: Optional[str] = None, max_results: int = 200) -> Dict[str, Any]:
        try:
            from elftools.elf.elffile import ELFFile
            from elftools.elf.sections import SymbolTableSection
        except ImportError:
            raise RuntimeError("pyelftools is not installed in Python daemon.")

        symbols = []
        filter_kw = (filter_keyword or "").lower()

        with open(file_path, "rb") as f:
            elffile = ELFFile(f)
            
            # Locate symbol table
            symtab = None
            for section in elffile.iter_sections():
                if isinstance(section, SymbolTableSection):
                    symtab = section
                    break

            if not symtab:
                return {"file_path": file_path, "symbols": [], "count": 0, "message": "No symbol table found in AXF/ELF file."}

            for sym in symtab.iter_symbols():
                name = sym.name
                if not name or name.startswith("$") or name.startswith("."):
                    continue

                # Filter global/object variables (STT_OBJECT or STB_GLOBAL/STB_LOCAL located in RAM)
                addr = sym['st_value']
                size = sym['st_size']
                sym_type = sym['st_info']['type']
                sym_bind = sym['st_info']['bind']

                # Typically ARM Cortex-M SRAM is 0x20000000 - 0x200FFFFF or 0x10000000 - 0x100FFFFF or 0x30000000
                is_ram = (
                    (0x20000000 <= addr < 0x20100000) or
                    (0x10000000 <= addr < 0x10100000) or
                    (0x30000000 <= addr < 0x30100000)
                )

                if is_ram and size > 0 and sym_type in ('STT_OBJECT', 'STT_NOTYPE', 'STT_COMMON'):
                    if filter_kw and filter_kw not in name.lower():
                        continue

                    # Suggest format by size
                    suggested_type = "uint32"
                    if size == 1:
                        suggested_type = "uint8"
                    elif size == 2:
                        suggested_type = "uint16"
                    elif size == 4:
                        # If name contains float/temp/speed/angle, could default to float32
                        lower_n = name.lower()
                        if any(k in lower_n for k in ["flt", "float", "speed", "temp", "cur", "vol", "angle"]):
                            suggested_type = "float32"
                        else:
                            suggested_type = "int32"
                    elif size == 8:
                        suggested_type = "float64"

                    symbols.append({
                        "name": name,
                        "address": f"0x{addr:08X}",
                        "raw_address": addr,
                        "size": size,
                        "type": suggested_type,
                        "bind": sym_bind
                    })

                    if len(symbols) >= max_results:
                        break

        # Sort by address
        symbols.sort(key=lambda s: s["raw_address"])
        return {
            "file_path": file_path,
            "count": len(symbols),
            "symbols": symbols
        }


class JScopeController:
    """
    JScope-like background memory sampling engine.
    Periodically polls watched RAM variables over SWD and streams telemetry text to a local TCP socket.
    """
    _lock = threading.Lock()
    _running = False
    _thread = None
    _server_sock = None
    _client_sock = None
    _tcp_port = 0
    _interval_ms = 20
    _interval_us = 20000
    _interval_sec = 0.02
    _swd_frequency_hz = 10_000_000
    _vars = []  # [{name, address, size, type}]

    _mode = None
    _jlink = None
    _session = None

    @classmethod
    def start_sampling(cls, variables: List[Dict[str, Any]], interval_ms: int = 20,
                       probe_id: Optional[str] = None, target_override: Optional[str] = None,
                       probe_type: Optional[str] = None, interval_us: Optional[int] = None,
                       swd_frequency_hz: Optional[int] = None) -> Dict[str, Any]:
        with cls._lock:
            if cls._running:
                cls.stop_sampling()

            if not variables:
                raise ValueError("No variables specified for JScope sampling")

            cls._vars = variables
            if interval_us is not None and interval_us > 0:
                cls._interval_us = max(1, interval_us)
                cls._interval_sec = cls._interval_us / 1_000_000.0
                cls._interval_ms = max(1, int(round(cls._interval_us / 1000.0)))
            else:
                cls._interval_ms = max(1, interval_ms)
                cls._interval_sec = cls._interval_ms / 1000.0
                cls._interval_us = cls._interval_ms * 1000

            cls._swd_frequency_hz = int(swd_frequency_hz) if swd_frequency_hz and swd_frequency_hz > 0 else 10_000_000

            # Create TCP server
            cls._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            cls._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            cls._server_sock.bind(("127.0.0.1", 0))
            cls._server_sock.listen(1)
            cls._tcp_port = cls._server_sock.getsockname()[1]

            chosen_type = (probe_type or "").lower()
            if not chosen_type:
                for p in PyOCDController.list_probes():
                    if not probe_id or p["unique_id"] == probe_id:
                        chosen_type = p.get("probe_type", "generic")
                        break

            cls._running = True

            if chosen_type == "jlink" and PYLINK_AVAILABLE:
                try:
                    cls._jlink = pylink.JLink()
                    if probe_id and probe_id.isdigit():
                        cls._jlink.open(int(probe_id))
                    else:
                        cls._jlink.open()
                    cls._jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
                    cls._jlink.connect(target_override or "Cortex-M4")
                    # Set J-Link SWD clock frequency in kHz
                    speed_khz = max(100, cls._swd_frequency_hz // 1000)
                    try:
                        cls._jlink.set_speed(speed_khz)
                        logger.info(f"JScope J-Link SWD speed set to {speed_khz} kHz ({cls._swd_frequency_hz} Hz)")
                    except Exception as e:
                        logger.warning(f"Could not set J-Link speed: {e}")
                    cls._mode = "jlink"
                except Exception as e:
                    logger.warning(f"JScope JLink connect failed, fallback to PyOCD: {e}")
                    cls._session = PyOCDController._create_session(probe_id, target_override, auto_open=True, frequency=cls._swd_frequency_hz)
                    cls._session.open()
                    cls._mode = "pyocd"
            else:
                cls._session = PyOCDController._create_session(probe_id, target_override, auto_open=True, frequency=cls._swd_frequency_hz)
                cls._session.open()
                logger.info(f"JScope PyOCD SWD frequency set to {cls._swd_frequency_hz} Hz")
                cls._mode = "pyocd"

            cls._thread = threading.Thread(target=cls._sample_worker_loop, daemon=True)
            cls._thread.start()

            return {
                "status": "started",
                "tcp_port": cls._tcp_port,
                "interval_ms": cls._interval_ms,
                "interval_us": cls._interval_us,
                "swd_frequency_hz": cls._swd_frequency_hz,
                "mode": cls._mode,
                "variable_count": len(cls._vars)
            }

    @staticmethod
    def _unpack_val(raw_bytes: bytes, size: int, vtype: str) -> Any:
        if not raw_bytes or len(raw_bytes) < size:
            return 0
        try:
            if vtype == "float32" and size == 4:
                return struct.unpack("<f", raw_bytes[:4])[0]
            elif vtype == "float64" and size == 8:
                return struct.unpack("<d", raw_bytes[:8])[0]
            elif vtype == "int32" and size == 4:
                return struct.unpack("<i", raw_bytes[:4])[0]
            elif vtype == "uint32" and size == 4:
                return struct.unpack("<I", raw_bytes[:4])[0]
            elif vtype == "int16" and size >= 2:
                return struct.unpack("<h", raw_bytes[:2])[0]
            elif vtype == "uint16" and size >= 2:
                return struct.unpack("<H", raw_bytes[:2])[0]
            elif vtype == "int64" and size >= 8:
                return struct.unpack("<q", raw_bytes[:8])[0]
            elif vtype == "uint64" and size >= 8:
                return struct.unpack("<Q", raw_bytes[:8])[0]
            elif vtype == "int8" and size >= 1:
                return struct.unpack("<b", raw_bytes[:1])[0]
            elif vtype == "uint8" and size >= 1:
                return struct.unpack("<B", raw_bytes[:1])[0]
            else:
                return struct.unpack("<I", raw_bytes[:4])[0] if len(raw_bytes) >= 4 else int.from_bytes(raw_bytes, "little")
        except Exception:
            return 0

    @classmethod
    def _sample_worker_loop(cls):
        logger.info(f"JScope sampling TCP bridge listening on port {cls._tcp_port} (Period: {cls._interval_us}us)")
        cls._server_sock.settimeout(3.0)

        client = None
        while cls._running:
            try:
                client, addr = cls._server_sock.accept()
                logger.info(f"JScope client connected from {addr}")
                client.setblocking(False)
                cls._client_sock = client
                break
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"JScope accept error: {e}")
                break

        if not client:
            cls.stop_sampling()
            return

        interval_sec = cls._interval_sec
        buffer_chunks = []
        last_flush_time = time.perf_counter()
        next_sample_time = time.perf_counter()

        # Cache variables and mode pointers
        mode = cls._mode
        jlink = cls._jlink
        target = cls._session.board.target if cls._session else None

        processed_vars = []
        for v in cls._vars:
            name = v["name"]
            addr = v["raw_address"] if "raw_address" in v else int(v["address"], 16)
            size = int(v.get("size", 4))
            vtype = v.get("type", "int32")
            processed_vars.append((name, addr, size, vtype))

        while cls._running:
            try:
                line_parts = []

                # Fast read watched variables
                for name, addr, size, vtype in processed_vars:
                    val = 0
                    try:
                        if mode == "jlink" and jlink:
                            if size == 4 and vtype in ("uint32", "int32", "float32"):
                                val_u32 = jlink.memory_read32(addr, 1)[0]
                                if vtype == "float32":
                                    val = struct.unpack("<f", struct.pack("<I", val_u32))[0]
                                elif vtype == "int32":
                                    val = struct.unpack("<i", struct.pack("<I", val_u32))[0]
                                else:
                                    val = val_u32
                            else:
                                raw_bytes = bytes(jlink.memory_read8(addr, size))
                                val = cls._unpack_val(raw_bytes, size, vtype)
                        elif mode == "pyocd" and target:
                            if size == 4 and vtype in ("uint32", "int32", "float32"):
                                val_u32 = target.read32(addr)
                                if vtype == "float32":
                                    val = struct.unpack("<f", struct.pack("<I", val_u32))[0]
                                elif vtype == "int32":
                                    val = struct.unpack("<i", struct.pack("<I", val_u32))[0]
                                else:
                                    val = val_u32
                            else:
                                raw_bytes = bytes(target.read_memory_block8(addr, size))
                                val = cls._unpack_val(raw_bytes, size, vtype)
                    except Exception as err:
                        logger.debug(f"Read var {name} failed: {err}")
                        val = 0

                    if isinstance(val, float):
                        line_parts.append(f"{name}:{val:.3f}")
                    else:
                        line_parts.append(f"{name}:{val}")

                if line_parts:
                    buffer_chunks.append(" ".join(line_parts) + "\n")

                # Batched flushing to prevent socket bottleneck at high sampling rates
                now_perf = time.perf_counter()
                if (now_perf - last_flush_time >= 0.005) or len(buffer_chunks) >= 50 or interval_sec >= 0.005:
                    if buffer_chunks:
                        out_data = "".join(buffer_chunks).encode("utf-8")
                        try:
                            client.sendall(out_data)
                        except (BlockingIOError, socket.error):
                            pass
                        buffer_chunks.clear()
                    last_flush_time = now_perf

                # Microsecond-precision pacing
                next_sample_time += interval_sec
                current_time = time.perf_counter()
                sleep_needed = next_sample_time - current_time

                if sleep_needed > 0.002:
                    time.sleep(sleep_needed - 0.001)
                    while time.perf_counter() < next_sample_time:
                        pass
                elif sleep_needed > 0:
                    while time.perf_counter() < next_sample_time:
                        pass
                else:
                    # Catch-up if fallen behind
                    if -sleep_needed > 2 * interval_sec:
                        next_sample_time = current_time

            except Exception as e:
                logger.error(f"JScope sampling loop error: {e}")
                break

        # Flush remaining buffer before exiting
        if buffer_chunks and client:
            try:
                client.sendall("".join(buffer_chunks).encode("utf-8"))
            except Exception:
                pass

        cls.stop_sampling()

    @classmethod
    def stop_sampling(cls) -> Dict[str, Any]:
        with cls._lock:
            cls._running = False
            if cls._client_sock:
                try:
                    cls._client_sock.close()
                except Exception:
                    pass
                cls._client_sock = None

            if cls._server_sock:
                try:
                    cls._server_sock.close()
                except Exception:
                    pass
                cls._server_sock = None

            if cls._jlink:
                try:
                    cls._jlink.close()
                except Exception:
                    pass
                cls._jlink = None

            if cls._session:
                try:
                    cls._session.close()
                except Exception:
                    pass
                cls._session = None

            cls._tcp_port = 0
            cls._mode = None
            trim_process_memory()
            return {"status": "stopped"}


class SerialController:
    """多串口并发管理与智能端口调度控制器。
    支持同时打开多个串口进行独立收发，当仅有一个串口活动时支持免传 port_name 智能路由。
    """
    _lock = threading.Lock()
    _ports: Dict[str, Any] = {}          # port_name -> serial.Serial
    _rx_buffers: Dict[str, bytearray] = {} # port_name -> bytearray
    _rx_threads: Dict[str, threading.Thread] = {}
    _running_flags: Dict[str, bool] = {}
    _last_active_port: Optional[str] = None

    @classmethod
    def list_ports(cls) -> List[Dict[str, Any]]:
        """枚举系统当前所有可用串口及状态。"""
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial 未安装或不可用")

        ports = serial.tools.list_ports.comports()
        result = []
        with cls._lock:
            for p in sorted(ports, key=lambda x: x.device):
                is_open = p.device in cls._ports and cls._ports[p.device].is_open
                result.append({
                    "port": p.device,
                    "description": p.description or "",
                    "hwid": p.hwid or "",
                    "is_open": is_open,
                    "is_default": (p.device == cls._last_active_port) if cls._last_active_port else False
                })
        return result

    @classmethod
    def _read_worker(cls, port_name: str, ser: Any):
        """后台持续读取线程，存入环形/定长缓存队列。"""
        while cls._running_flags.get(port_name, False):
            try:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    if data:
                        with cls._lock:
                            buf = cls._rx_buffers.setdefault(port_name, bytearray())
                            buf.extend(data)
                            # 保持最大 1MB 缓存，防止内存无限上涨
                            if len(buf) > 1024 * 1024:
                                del buf[:len(buf) - 1024 * 1024]
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.warning(f"Serial worker read error on {port_name}: {e}")
                break

    @classmethod
    def open_port(
        cls,
        port_name: str,
        baudrate: int = 115200,
        data_bits: int = 8,
        stop_bits: float = 1,
        parity: str = "N",
        timeout: float = 0.5
    ) -> Dict[str, Any]:
        """打开指定串口。"""
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial 未安装或不可用")

        port_name = port_name.strip().upper() if port_name.upper().startswith("COM") else port_name.strip()
        with cls._lock:
            if port_name in cls._ports and cls._ports[port_name].is_open:
                cls._last_active_port = port_name
                return {
                    "status": "already_open",
                    "port": port_name,
                    "baudrate": cls._ports[port_name].baudrate,
                    "message": f"串口 {port_name} 已经处于打开状态"
                }

            # 解析串口参数
            parity_map = {
                "N": serial.PARITY_NONE,
                "E": serial.PARITY_EVEN,
                "O": serial.PARITY_ODD,
                "M": serial.PARITY_MARK,
                "S": serial.PARITY_SPACE
            }
            p_val = parity_map.get(parity.upper(), serial.PARITY_NONE)

            stopbits_map = {
                1: serial.STOPBITS_ONE,
                1.5: serial.STOPBITS_ONE_POINT_FIVE,
                2: serial.STOPBITS_TWO
            }
            s_val = stopbits_map.get(stop_bits, serial.STOPBITS_ONE)

            ser = serial.Serial(
                port=port_name,
                baudrate=baudrate,
                bytesize=data_bits,
                parity=p_val,
                stopbits=s_val,
                timeout=timeout
            )

            cls._ports[port_name] = ser
            cls._rx_buffers[port_name] = bytearray()
            cls._running_flags[port_name] = True
            cls._last_active_port = port_name

            t = threading.Thread(target=cls._read_worker, args=(port_name, ser), daemon=True)
            cls._rx_threads[port_name] = t
            t.start()

            active_ports = [p for p, s in cls._ports.items() if s.is_open]
            return {
                "status": "opened",
                "port": port_name,
                "baudrate": baudrate,
                "data_bits": data_bits,
                "stop_bits": stop_bits,
                "parity": parity,
                "total_open_ports": len(active_ports),
                "open_ports": active_ports
            }

    @classmethod
    def _resolve_port_name(cls, port_name: Optional[str] = None) -> str:
        """智能解析目标串口：
        1. 如果指定了 port_name 且已打开，直接使用。
        2. 如果未指定：
           - 若当前仅打开了一个串口，自动匹配使用该串口；
           - 若打开了多个串口，优先回退到最近活跃的串口 _last_active_port（若仍在打开列表中）；
           - 否则抛出明确提示，引导用户选择具体串口。
        """
        open_list = [p for p, s in cls._ports.items() if s.is_open]
        if not open_list:
            raise RuntimeError("当前未打开任何串口，请先调用 open_serial_port 打开目标串口")

        if port_name:
            target = port_name.strip().upper() if port_name.upper().startswith("COM") else port_name.strip()
            if target in open_list:
                return target
            raise RuntimeError(f"指定的串口 {port_name} 未打开。当前已打开的串口列表: {open_list}")

        # 未指定端口
        if len(open_list) == 1:
            return open_list[0]

        if cls._last_active_port and cls._last_active_port in open_list:
            return cls._last_active_port

        raise RuntimeError(f"当前打开了多个串口 {open_list}，请在参数中指定 port_name 以明确操作目标")

    @classmethod
    def close_port(cls, port_name: Optional[str] = None) -> Dict[str, Any]:
        """关闭串口。若仅打开一个串口可不传 port_name。"""
        with cls._lock:
            target = cls._resolve_port_name(port_name)
            cls._running_flags[target] = False
            ser = cls._ports.pop(target, None)
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            cls._rx_buffers.pop(target, None)
            cls._rx_threads.pop(target, None)
            if cls._last_active_port == target:
                remaining = [p for p, s in cls._ports.items() if s.is_open]
                cls._last_active_port = remaining[-1] if remaining else None

            remaining_ports = [p for p, s in cls._ports.items() if s.is_open]
            return {
                "status": "closed",
                "port": target,
                "remaining_open_ports": remaining_ports
            }

    @classmethod
    def send_data(
        cls,
        data: str,
        port_name: Optional[str] = None,
        is_hex: bool = False,
        append_crlf: bool = False
    ) -> Dict[str, Any]:
        """向串口发送数据。未指定 port_name 且只打开单个串口时自动免选。"""
        with cls._lock:
            target = cls._resolve_port_name(port_name)
            ser = cls._ports[target]
            cls._last_active_port = target

            if is_hex:
                hex_cleaned = "".join(data.split())
                payload = bytes.fromhex(hex_cleaned)
            else:
                text_to_send = data
                if append_crlf and not text_to_send.endswith("\r\n"):
                    if text_to_send.endswith("\n"):
                        text_to_send = text_to_send[:-1] + "\r\n"
                    else:
                        text_to_send += "\r\n"
                payload = text_to_send.encode("utf-8", errors="replace")

            bytes_written = ser.write(payload)
            ser.flush()

            return {
                "status": "sent",
                "port": target,
                "bytes_written": bytes_written,
                "is_hex": is_hex
            }

    @classmethod
    def read_data(
        cls,
        port_name: Optional[str] = None,
        max_bytes: int = 4096,
        timeout: float = 0.5,
        format_type: str = "text",
        clear_buffer: bool = True
    ) -> Dict[str, Any]:
        """从串口接收缓存或总线读取数据。未指定 port_name 且只打开单个串口时自动免选。"""
        target = cls._resolve_port_name(port_name)

        # 稍微等待数据到达
        start_wait = time.perf_counter()
        while time.perf_counter() - start_wait < timeout:
            with cls._lock:
                buf = cls._rx_buffers.get(target, bytearray())
                if len(buf) > 0:
                    break
            time.sleep(0.02)

        with cls._lock:
            cls._last_active_port = target
            buf = cls._rx_buffers.get(target, bytearray())
            read_len = min(len(buf), max_bytes)
            raw = bytes(buf[:read_len])
            if clear_buffer:
                del buf[:read_len]

        if format_type.lower() == "hex":
            formatted_data = raw.hex().upper()
        else:
            formatted_data = raw.decode("utf-8", errors="replace")

        return {
            "port": target,
            "bytes_read": len(raw),
            "format": format_type,
            "data": formatted_data,
            "has_more": len(buf) > 0
        }


# MCP Tools Definitions
MCP_TOOLS = [
    {
        "name": "list_probes",
        "description": "列出所有连接至宿主机的 DAPLink / CMSIS-DAP / JLink 硬件调试器探针",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "read_core_registers",
        "description": "读取 ARM Cortex-M 核心寄存器与 SCB 故障寄存器 (CFSR/HFSR/BFAR/MMFAR)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_id": {"type": "string", "description": "调试器探针 Unique ID (可选)"},
                "target_override": {"type": "string", "description": "目标芯片型号 (如 stm32f407vg)"}
            }
        }
    },
    {
        "name": "read_memory",
        "description": "读取目标单片机内存地址空间数据 (返回 HEX Dump 与字节数据)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "起始内存地址，例如 0x20000000"},
                "count": {"type": "integer", "description": "读取字节数，最大 4096", "default": 64},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address"]
        }
    },
    {
        "name": "write_memory",
        "description": "写入 32 位值到目标单片机指定内存地址",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "内存地址"},
                "value": {"type": "integer", "description": "32位无符号数值"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address", "value"]
        }
    },
    {
        "name": "flash_firmware",
        "description": "通过 SWD 协议将本地固件文件 (.bin/.hex/.elf) 烧录至目标芯片 Flash (支持外部 CMSIS-Pack 下载算法)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "本地固件文件的绝对物理路径"},
                "target_override": {"type": "string", "description": "目标单片机芯片型号 (如 gd32f403rc / stm32f103c8)"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "pack_path": {"type": "string", "description": "CMSIS-Pack (.pack) 文件绝对物理路径 (用于加载芯片专有 Flash 下载算法)"},
                "frequency": {"type": "integer", "description": "SWD 烧录工作时钟频率 (Hz，如 10000000)"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "reset_target",
        "description": "通过 SWD 硬件/软件复位目标单片机",
        "inputSchema": {
            "type": "object",
            "properties": {
                "halt": {"type": "boolean", "description": "复位后是否保持挂起 (Halt)", "default": False},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            }
        }
    },
    {
        "name": "diagnose_hardfault",
        "description": "自动化全流程分析 Cortex-M 硬件硬故障 (HardFault)，提取崩溃现场、回溯双栈调用链、解析源文件行并输出 AI 诊断建议",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"},
                "axf_path": {"type": "string", "description": "固件 ELF/AXF 文件绝对路径 (用于反汇编、解析调用栈符号与源码行)"}
            }
        }
    },
    {
        "name": "detect_rtos_kernel",
        "description": "深度探测固件中的嵌入式操作系统 (FreeRTOS, RTX5, ThreadX, uCOS-II, uCOS-III, RT-Thread) 并分析内核控制块符号地址",
        "inputSchema": {
            "type": "object",
            "properties": {
                "elf_path": {"type": "string", "description": "固件 ELF/AXF/OUT 文件的绝对物理路径"}
            },
            "required": ["elf_path"]
        }
    },
    {
        "name": "start_rtt",
        "description": "启动 SEGGER RTT 实时数据传输引擎 (支持 J-Link 及 DAPLink 探针)，建立本地高速双向流通信",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_id": {"type": "string", "description": "探针 Unique ID (可选)"},
                "target_override": {"type": "string", "description": "目标芯片型号 (如 Cortex-M4)"},
                "probe_type": {"type": "string", "description": "探针驱动类型: 'jlink' 或 'daplink'"},
                "block_address": {"type": "integer", "description": "SEGGER RTT 控制块在 RAM 中的起始物理地址 (可选)"},
                "ram_start": {"type": "integer", "description": "目标芯片 RAM 内存扫描起始地址 (如 0x20000000，可选)"},
                "ram_size": {"type": "integer", "description": "目标芯片 RAM 内存扫描范围大小 (如 0x10000 表示 64KB，可选)"}
            }
        }
    },
    {
        "name": "stop_rtt",
        "description": "停止 SEGGER RTT 传输并释放调试探针句柄与网络端口",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "parse_axf_symbols",
        "description": "解析 Keil MDK .axf 或 GCC .elf 固件，提取 SRAM 全局变量符号 (名称/地址/大小/类型)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": ".axf 或 .elf 绝对物理路径"},
                "filter_keyword": {"type": "string", "description": "变量名过滤关键字 (可选)"},
                "max_results": {"type": "integer", "description": "最大提取符号数", "default": 200}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "start_jscope_sampling",
        "description": "启动后台 SWD 高速无侵入周期变量采样 (类似 J-Scope)，支持微秒至毫秒级周期 (最高1MHz)，通过本地 TCP 桥接输出波形数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "variables": {"type": "array", "description": "待监视变量列表"},
                "interval_ms": {"type": "integer", "description": "采样周期毫秒 (如 20)", "default": 20},
                "interval_us": {"type": "integer", "description": "微秒级采样周期 (1 至 1000000 µs，优先于 interval_ms)"},
                "swd_frequency_hz": {"type": "integer", "description": "SWD 接口时钟频率 (Hz，如 10000000 代表 10MHz)", "default": 10000000},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"},
                "probe_type": {"type": "string", "description": "探针类型: 'jlink' 或 'daplink'"}
            },
            "required": ["variables"]
        }
    },
    {
        "name": "stop_jscope_sampling",
        "description": "停止 J-Scope 变量采样",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "write_memory_byte",
        "description": "写入单个字节 (8位数值) 到目标单片机指定内存地址",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "内存物理地址"},
                "value": {"type": "integer", "description": "8位无符号数值 (0-255)"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address", "value"]
        }
    },
    {
        "name": "dump_memory_to_file",
        "description": "将目标单片机指定内存地址范围 (Flash 或 RAM) 转储导出为本地 .bin 文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "起始内存地址，例如 0x08000000 或 0x20000000"},
                "count": {"type": "integer", "description": "导出的总字节数"},
                "file_path": {"type": "string", "description": "输出 .bin 文件的绝对物理路径"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address", "count", "file_path"]
        }
    },
    {
        "name": "load_file_to_memory",
        "description": "将本地二进制文件 (.bin) 加载写入至单片机指定 RAM 地址",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "目标 RAM 起始物理地址"},
                "file_path": {"type": "string", "description": "本地 .bin 文件物理路径"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address", "file_path"]
        }
    },
    {
        "name": "analyze_firmware_resources",
        "description": "深度分析嵌入式固件 (.axf/.elf) 的 Flash/ROM 与 SRAM 资源占用情况。根据 GCC、ARMCC、ARMClang 等不同编译器输出规则，提取总 Code/RO/RW/ZI 内存、各模块源文件及函数的资源占用与占比，并支持目标芯片容量评估与优化诊断",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "本地 .axf 或 .elf 固件文件的绝对物理路径"},
                "chip_flash_size": {"type": "integer", "description": "目标芯片 Flash 容量 (可选，字节数，如 524288 表示 512KB)"},
                "chip_ram_size": {"type": "integer", "description": "目标芯片 SRAM 容量 (可选，字节数，如 65536 表示 64KB)"},
                "max_symbols_per_module": {"type": "integer", "description": "每个模块返回的最大符号数 (默认 25)", "default": 25}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "svd_get_devices",
        "description": "获取已加载 CMSIS-Pack 中定义的所有芯片型号 (ING91800, ING91600, ING2000 等) 及其内存基地址与容量",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "svd_get_peripherals",
        "description": "解析并返回指定芯片的 SVD 外设列表 (外设名称、基地址、描述、组名)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "芯片型号，如 ING91800"},
                "custom_svd_path": {"type": "string", "description": "自定义外部 .svd 物理路径 (可选)"}
            },
            "required": ["device_name"]
        }
    },
    {
        "name": "svd_get_registers",
        "description": "获取指定外设的全部寄存器定义，包含偏移、绝对地址、访问权限 (RO/RW/WO)、复位值及 32 位位域 (Fields)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "芯片型号"},
                "peripheral_name": {"type": "string", "description": "外设名称，如 UART0"},
                "custom_svd_path": {"type": "string", "description": "自定义外部 .svd 物理路径 (可选)"}
            },
            "required": ["device_name", "peripheral_name"]
        }
    },
    {
        "name": "svd_read_register",
        "description": "通过 SWD 硬件读取目标单片机指定 SVD 寄存器 32 位值",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "寄存器物理绝对地址"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address"]
        }
    },
    {
        "name": "svd_read_all_registers",
        "description": "批量读取外设的一组寄存器 32 位值",
        "inputSchema": {
            "type": "object",
            "properties": {
                "addresses": {"type": "array", "items": {"type": "integer"}, "description": "寄存器绝对地址列表"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["addresses"]
        }
    },
    {
        "name": "svd_write_register",
        "description": "通过 SWD 硬件向目标单片机指定 SVD 寄存器写入 32 位值",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "寄存器物理绝对地址"},
                "value": {"type": "integer", "description": "32位无符号数值"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address", "value"]
        }
    },
    {
        "name": "svd_write_field",
        "description": "按位域 (Bitfield) 安全修改硬件寄存器并回写 (Read-Modify-Write)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "integer", "description": "寄存器物理绝对地址"},
                "bit_offset": {"type": "integer", "description": "位域起始偏移 (0-31)"},
                "bit_width": {"type": "integer", "description": "位域宽度 (1-32)"},
                "field_value": {"type": "integer", "description": "欲写入的位域数值"},
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            },
            "required": ["address", "bit_offset", "bit_width", "field_value"]
        }
    },
    {
        "name": "svd_import_pack",
        "description": "动态导入 CMSIS-Pack (.pack) 文件并解析其内置的芯片、Flash 算法与 SVD 外设定义",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_path": {"type": "string", "description": "CMSIS-Pack 文件完整物理路径 (.pack)"}
            },
            "required": ["pack_path"]
        }
    },
    {
        "name": "list_serial_ports",
        "description": "列出系统当前所有可用的物理与虚拟串口设备及其打开状态和默认/活跃标识",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "open_serial_port",
        "description": "打开指定的串口进行通信（支持波特率、数据位、停止位、校验位配置，支持多串口并行会话）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_name": {"type": "string", "description": "串口端口号（如 COM3 或 /dev/ttyUSB0）"},
                "baudrate": {"type": "integer", "description": "波特率 (默认 115200)", "default": 115200},
                "data_bits": {"type": "integer", "description": "数据位 (5, 6, 7, 8，默认 8)", "default": 8},
                "stop_bits": {"type": "number", "description": "停止位 (1, 1.5, 2，默认 1)", "default": 1},
                "parity": {"type": "string", "description": "校验位 ('N'=None, 'E'=Even, 'O'=Odd, 'M'=Mark, 'S'=Space，默认 'N')", "default": "N"},
                "timeout": {"type": "number", "description": "读取超时秒数 (默认 0.5)", "default": 0.5}
            },
            "required": ["port_name"]
        }
    },
    {
        "name": "close_serial_port",
        "description": "关闭指定串口释放系统句柄。若系统当前仅打开了一个串口，可不传 port_name 自动关闭该串口",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_name": {"type": "string", "description": "要关闭的串口端口号（如 COM3，单串口时可选）"}
            }
        }
    },
    {
        "name": "send_serial_data",
        "description": "向串口发送数据（支持文本字符串与 HEX 十六进制字节串）。若系统仅打开一个串口，无需指定 port_name 自动智能发送；若打开多个串口支持指定 port_name 或默认使用最近活跃串口",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "要发送的文本内容或 HEX 字符串 (如 'AT\\r\\n' 或 'AA BB 01 02')"},
                "port_name": {"type": "string", "description": "目标串口端口号（如 COM3，单串口时可选）"},
                "is_hex": {"type": "boolean", "description": "是否为十六进制 HEX 字节串模式 (默认 false)", "default": False},
                "append_crlf": {"type": "boolean", "description": "是否自动在末尾追加 \\r\\n 换行符 (仅文本模式有效，默认 false)", "default": False}
            },
            "required": ["data"]
        }
    },
    {
        "name": "read_serial_data",
        "description": "从串口接收缓存区读取最新数据。若系统仅打开一个串口，无需指定 port_name 自动智能读取；若打开多个串口支持指定 port_name",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_name": {"type": "string", "description": "目标串口端口号（如 COM3，单串口时可选）"},
                "max_bytes": {"type": "integer", "description": "最大读取字节数 (默认 4096)", "default": 4096},
                "timeout": {"type": "number", "description": "等待数据到达超时秒数 (默认 0.5)", "default": 0.5},
                "format": {"type": "string", "description": "数据返回格式: 'text' (UTF-8字符串) 或 'hex' (大写HEX串，默认 'text')", "default": "text"},
                "clear_buffer": {"type": "boolean", "description": "读取后是否清空已读数据 (默认 true)", "default": True}
            }
        }
    }
]

MCP_SERVER_NAME = "embedded-hil-debugger"
MCP_SERVER_VERSION = "1.0.0"
MCP_DEFAULT_PROTOCOL_VERSION = "2024-11-05"

# 兼容旧调用方式：直接以工具名作为 JSON-RPC method
DIRECT_TOOL_METHODS = [
    "list_probes",
    "read_core_registers",
    "read_memory",
    "write_memory",
    "write_memory_byte",
    "dump_memory_to_file",
    "load_file_to_memory",
    "flash_firmware",
    "reset_target",
    "diagnose_hardfault",
    "start_rtt",
    "stop_rtt",
    "parse_axf_symbols",
    "start_jscope_sampling",
    "stop_jscope_sampling",
    "analyze_firmware_resources",
    "svd_get_devices",
    "svd_get_peripherals",
    "svd_get_registers",
    "svd_read_register",
    "svd_read_all_registers",
    "svd_write_register",
    "svd_write_field",
    "svd_import_pack",
    "list_serial_ports",
    "open_serial_port",
    "close_serial_port",
    "send_serial_data",
    "read_serial_data",
]


def wrap_tool_result(payload: Any) -> Dict[str, Any]:
    """把工具原始返回值包装成 MCP CallToolResult。"""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def wrap_tool_error(message: str) -> Dict[str, Any]:
    """工具级失败按 MCP 约定用 isError 上报，而不是 JSON-RPC error。"""
    return {"content": [{"type": "text", "text": message}], "isError": True}


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Dispatch tool call to corresponding handler."""
    probe_id = arguments.get("probe_id")
    target_override = arguments.get("target_override")

    if name == "list_probes":
        return PyOCDController.list_probes()
    elif name == "read_core_registers":
        return PyOCDController.read_core_registers(probe_id, target_override)
    elif name == "read_memory":
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        count = int(arguments.get("count", 64))
        return PyOCDController.read_memory(address, count, probe_id, target_override)
    elif name == "write_memory":
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        value = arguments["value"]
        if isinstance(value, str):
            value = int(value, 16 if value.startswith("0x") else 10)
        return PyOCDController.write_memory(address, value, probe_id, target_override)
    elif name == "write_memory_byte":
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        value = arguments["value"]
        if isinstance(value, str):
            value = int(value, 16 if value.startswith("0x") else 10)
        return PyOCDController.write_memory_byte(address, value, probe_id, target_override)
    elif name == "dump_memory_to_file":
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        count = int(arguments["count"])
        file_path = arguments["file_path"]
        return PyOCDController.dump_memory_to_file(address, count, file_path, probe_id, target_override)
    elif name == "load_file_to_memory":
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        file_path = arguments["file_path"]
        return PyOCDController.load_file_to_memory(address, file_path, probe_id, target_override)
    elif name == "flash_firmware":
        file_path = arguments["file_path"]
        pack_path = arguments.get("pack_path")
        freq = arguments.get("frequency")
        if isinstance(freq, str):
            freq = int(freq, 16 if freq.startswith("0x") else 10)
        return PyOCDController.flash_firmware(file_path, target_override, probe_id, pack_path=pack_path, frequency=freq)
    elif name == "reset_target":
        halt = bool(arguments.get("halt", False))
        return PyOCDController.reset_target(halt, probe_id, target_override)
    elif name == "diagnose_hardfault":
        axf_path = arguments.get("axf_path")
        return PyOCDController.diagnose_hardfault(probe_id, target_override, axf_path)
    elif name == "detect_rtos_kernel":
        elf_path = arguments["elf_path"]
        return PyOCDController.detect_rtos_kernel(elf_path)
    elif name == "capture_lcd_framebuffer":
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        width = int(arguments.get("width", 320))
        height = int(arguments.get("height", 240))
        pixel_format = arguments.get("pixel_format", "rgb565")
        return PyOCDController.capture_lcd_framebuffer(address, width, height, pixel_format, probe_id, target_override)
    elif name == "start_rtt":
        probe_type = arguments.get("probe_type")
        block_addr = arguments.get("block_address")
        if isinstance(block_addr, str):
            block_addr = int(block_addr, 16 if block_addr.startswith("0x") else 10)
        ram_start = arguments.get("ram_start")
        if isinstance(ram_start, str):
            ram_start = int(ram_start, 16 if ram_start.startswith("0x") else 10)
        ram_size = arguments.get("ram_size")
        if isinstance(ram_size, str):
            ram_size = int(ram_size, 16 if ram_size.startswith("0x") else 10)
        return RTTController.start_rtt(probe_id, target_override, block_addr, probe_type, ram_start=ram_start, ram_size=ram_size)
    elif name == "stop_rtt":
        return RTTController.stop_rtt()
    elif name == "parse_axf_symbols":
        file_path = arguments["file_path"]
        kw = arguments.get("filter_keyword")
        max_r = int(arguments.get("max_results", 200))
        return AxfSymbolParser.parse_symbols(file_path, kw, max_r)
    elif name == "start_jscope_sampling":
        variables = arguments["variables"]
        interval = int(arguments.get("interval_ms", 20))
        interval_us = arguments.get("interval_us")
        if interval_us is not None:
            interval_us = int(interval_us)
        swd_freq = arguments.get("swd_frequency_hz")
        if swd_freq is not None:
            swd_freq = int(swd_freq)
        probe_type = arguments.get("probe_type")
        return JScopeController.start_sampling(variables, interval, probe_id, target_override, probe_type,
                                              interval_us=interval_us, swd_frequency_hz=swd_freq)
    elif name == "stop_jscope_sampling":
        return JScopeController.stop_sampling()
    elif name == "analyze_firmware_resources":
        file_path = arguments["file_path"]
        chip_flash = arguments.get("chip_flash_size")
        if isinstance(chip_flash, str):
            chip_flash = int(chip_flash, 16 if chip_flash.startswith("0x") else 10)
        chip_ram = arguments.get("chip_ram_size")
        if isinstance(chip_ram, str):
            chip_ram = int(chip_ram, 16 if chip_ram.startswith("0x") else 10)
        max_syms = int(arguments.get("max_symbols_per_module", 25))
        return FirmwareResourceAnalyzer.analyze(file_path, chip_flash, chip_ram, max_syms)
    elif name == "svd_get_devices":
        from svd_manager import SvdManager
        return SvdManager.list_devices()
    elif name == "svd_get_peripherals":
        from svd_manager import SvdManager
        device_name = arguments["device_name"]
        custom_svd = arguments.get("custom_svd_path")
        return SvdManager.get_peripherals(device_name, custom_svd)
    elif name == "svd_get_registers":
        from svd_manager import SvdManager
        device_name = arguments["device_name"]
        peripheral_name = arguments["peripheral_name"]
        custom_svd = arguments.get("custom_svd_path")
        return SvdManager.get_registers(device_name, peripheral_name, custom_svd)
    elif name == "svd_read_register":
        from svd_manager import SvdManager
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        return SvdManager.read_register(address, probe_id, target_override)
    elif name == "svd_read_all_registers":
        from svd_manager import SvdManager
        addresses = arguments["addresses"]
        int_addrs = [int(a, 16 if isinstance(a, str) and a.startswith("0x") else 10) for a in addresses]
        return SvdManager.read_all_registers(int_addrs, probe_id, target_override)
    elif name == "svd_write_register":
        from svd_manager import SvdManager
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        value = arguments["value"]
        if isinstance(value, str):
            value = int(value, 16 if value.startswith("0x") else 10)
        return SvdManager.write_register(address, value, probe_id, target_override)
    elif name == "svd_write_field":
        from svd_manager import SvdManager
        address = arguments["address"]
        if isinstance(address, str):
            address = int(address, 16 if address.startswith("0x") else 10)
        bit_offset = int(arguments["bit_offset"])
        bit_width = int(arguments["bit_width"])
        field_val = arguments["field_value"]
        if isinstance(field_val, str):
            field_val = int(field_val, 16 if field_val.startswith("0x") else 10)
        return SvdManager.write_field(address, bit_offset, bit_width, field_val, probe_id, target_override)
    elif name == "svd_import_pack":
        from svd_manager import SvdManager
        pack_path = arguments["pack_path"]
        return SvdManager.import_pack(pack_path)
    elif name == "list_serial_ports":
        return SerialController.list_ports()
    elif name == "open_serial_port":
        port_name = arguments["port_name"]
        baudrate = int(arguments.get("baudrate", 115200))
        data_bits = int(arguments.get("data_bits", 8))
        stop_bits = float(arguments.get("stop_bits", 1))
        parity = str(arguments.get("parity", "N"))
        timeout = float(arguments.get("timeout", 0.5))
        return SerialController.open_port(
            port_name=port_name,
            baudrate=baudrate,
            data_bits=data_bits,
            stop_bits=stop_bits,
            parity=parity,
            timeout=timeout
        )
    elif name == "close_serial_port":
        port_name = arguments.get("port_name")
        return SerialController.close_port(port_name=port_name)
    elif name == "send_serial_data":
        data = arguments["data"]
        port_name = arguments.get("port_name")
        is_hex = bool(arguments.get("is_hex", False))
        append_crlf = bool(arguments.get("append_crlf", False))
        return SerialController.send_data(
            data=data,
            port_name=port_name,
            is_hex=is_hex,
            append_crlf=append_crlf
        )
    elif name == "read_serial_data":
        port_name = arguments.get("port_name")
        max_bytes = int(arguments.get("max_bytes", 4096))
        timeout = float(arguments.get("timeout", 0.5))
        fmt = str(arguments.get("format", "text"))
        clear_buf = bool(arguments.get("clear_buffer", True))
        return SerialController.read_data(
            port_name=port_name,
            max_bytes=max_bytes,
            timeout=timeout,
            format_type=fmt,
            clear_buffer=clear_buf
        )
    else:
        raise ValueError(f"Unknown MCP tool: {name}")


def main():
    logger.info("Starting HIL Python Daemon (JSON-RPC 2.0 / MCP Server)...")
    trim_process_memory()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                # EOF: Parent process closed pipe, exit gracefully
                logger.info("stdin closed, exiting daemon.")
                break

            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                    "id": None
                }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                continue

            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params") or {}

            # MCP 通知（无 id）不需要应答，静默处理
            if req_id is None:
                continue

            # Handle JSON-RPC / MCP Methods
            try:
                if method == "initialize":
                    # 回显客户端请求的协议版本，避免 SDK 因版本不在支持列表而拒绝连接
                    requested = params.get("protocolVersion")
                    result = {
                        "protocolVersion": requested or MCP_DEFAULT_PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
                    }
                elif method == "ping":
                    result = {}
                elif method == "tools/list" or method == "list_tools":
                    result = {"tools": MCP_TOOLS}
                elif method == "tools/call" or method == "call_tool":
                    tool_name = params.get("name")
                    tool_args = params.get("arguments") or {}
                    # MCP 要求返回 CallToolResult；工具级失败用 isError 上报
                    try:
                        result = wrap_tool_result(dispatch_tool(tool_name, tool_args))
                    except Exception as tool_error:
                        logger.error(f"Tool '{tool_name}' failed: {tool_error}")
                        result = wrap_tool_error(f"{tool_name}: {tool_error}")
                elif method in DIRECT_TOOL_METHODS:
                    # 保留旧的“工具名即 method”调用方式，返回裸结果
                    result = dispatch_tool(method, params)
                else:
                    raise ValueError(f"Method not found: {method}")

                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id
                }
            except Exception as e:
                logger.error(f"Error handling method '{method}': {e}\n{traceback.format_exc()}")
                response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": str(e),
                        "data": traceback.format_exc()
                    },
                    "id": req_id
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Top-level loop error: {e}")

    logger.info("HIL Python Daemon terminated.")


if __name__ == "__main__":
    main()
