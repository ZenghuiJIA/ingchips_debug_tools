#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HIL Python Daemon - PyOCD & MCP Server Bridge
Communicates with Tauri Rust backend over JSON-RPC 2.0 via stdin/stdout.
"""

import sys
import json
import logging
import gc
import traceback
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


def trim_process_memory():
    """Trim memory footprint to stay well under memory budget."""
    gc.collect()
    try:
        import ctypes
        if sys.platform == "win32":
            ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
    except Exception:
        pass


def decode_cfsr(cfsr: int, mmfar: int, bfar: int) -> Dict[str, Any]:
    """Decode Cortex-M CFSR (Configurable Fault Status Register)."""
    mmfsr = cfsr & 0xFF
    bfsr = (cfsr >> 8) & 0xFF
    ufsr = (cfsr >> 16) & 0xFFFF

    flags = []
    explanations = []

    # MemManage Faults
    if mmfsr & (1 << 0):
        flags.append("IACCVIOL")
        explanations.append("Instruction access violation: processor attempted an instruction fetch from a restricted region.")
    if mmfsr & (1 << 1):
        flags.append("DACCVIOL")
        explanations.append("Data access violation: load/store attempted at a restricted memory address.")
    if mmfsr & (1 << 3):
        flags.append("MUNSTKERR")
        explanations.append("MemManage unstacking error during exception return.")
    if mmfsr & (1 << 4):
        flags.append("MSTKERR")
        explanations.append("MemManage stacking error during exception entry.")
    if mmfsr & (1 << 5):
        flags.append("MLSPERR")
        explanations.append("MemManage floating-point lazy state preservation error.")
    if mmfsr & (1 << 7):
        flags.append(f"MMARVALID (Address: 0x{mmfar:08X})")
        explanations.append(f"MMFAR holds valid faulting address: 0x{mmfar:08X}.")

    # Bus Faults
    if bfsr & (1 << 0):
        flags.append("IBUSERR")
        explanations.append("Instruction bus error during instruction prefetch.")
    if bfsr & (1 << 1):
        flags.append("PRECISERR")
        explanations.append("Precise data access bus fault. Fault address is known.")
    if bfsr & (1 << 2):
        flags.append("IMPRECISERR")
        explanations.append("Imprecise data access bus fault. Fault occurred asynchronously.")
    if bfsr & (1 << 3):
        flags.append("UNSTKERR")
        explanations.append("Bus fault on unstacking during exception return.")
    if bfsr & (1 << 4):
        flags.append("STKERR")
        explanations.append("Bus fault on stacking during exception entry.")
    if bfsr & (1 << 5):
        flags.append("LSPERR")
        explanations.append("Bus fault during floating-point lazy state preservation.")
    if bfsr & (1 << 7):
        flags.append(f"BFARVALID (Address: 0x{bfar:08X})")
        explanations.append(f"BFAR holds valid bus fault address: 0x{bfar:08X}. Common causes: uninitialized peripheral clock, null pointer dereference.")

    # Usage Faults
    if ufsr & (1 << 0):
        flags.append("UNDEFINSTR")
        explanations.append("Undefined instruction executed.")
    if ufsr & (1 << 1):
        flags.append("INVSTATE")
        explanations.append("Invalid execution state (e.g. attempted to execute ARM code instead of Thumb mode).")
    if ufsr & (1 << 2):
        flags.append("INVPC")
        explanations.append("Invalid EXC_RETURN value loaded into PC on exception return.")
    if ufsr & (1 << 3):
        flags.append("NOCP")
        explanations.append("Attempted to access coprocessor / FPU without enabling coprocessor clock/access.")
    if ufsr & (1 << 8):
        flags.append("UNALIGNED")
        explanations.append("Unaligned memory access performed with alignment trap enabled.")
    if ufsr & (1 << 9):
        flags.append("DIVBYZERO")
        explanations.append("SDIV or UDIV instruction executed with divisor equal to 0.")

    return {
        "raw_cfsr": f"0x{cfsr:08X}",
        "mmfsr": f"0x{mmfsr:02X}",
        "bfsr": f"0x{bfsr:02X}",
        "ufsr": f"0x{ufsr:04X}",
        "flags": flags,
        "explanations": explanations
    }


def decode_hfsr(hfsr: int) -> Dict[str, Any]:
    """Decode Cortex-M HFSR (HardFault Status Register)."""
    flags = []
    explanations = []

    if hfsr & (1 << 1):
        flags.append("VECTTBL")
        explanations.append("Vector table read fault during exception processing.")
    if hfsr & (1 << 30):
        flags.append("FORCED")
        explanations.append("Forced HardFault: a configurable fault (MemManage, Bus, Usage) escalated to HardFault because its handler is disabled.")
    if hfsr & (1 << 31):
        flags.append("DEBUGEVT")
        explanations.append("Debug event generated a HardFault.")

    return {
        "raw_hfsr": f"0x{hfsr:08X}",
        "flags": flags,
        "explanations": explanations
    }


class PyOCDController:
    """Controller for PyOCD hardware operations."""

    @staticmethod
    def list_probes() -> List[Dict[str, Any]]:
        if not PYOCD_AVAILABLE:
            return []
        try:
            probes = ConnectHelper.get_all_connected_probes()
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
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available.")
        
        kwargs = {"auto_open": True}
        if probe_id:
            kwargs["unique_id"] = probe_id
        if target_override:
            kwargs["target_override"] = target_override

        session = ConnectHelper.session_with_chosen_probe(**kwargs)
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
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available.")
        
        count = min(count, 4096)  # Cap at 4KB
        kwargs = {"auto_open": True}
        if probe_id:
            kwargs["unique_id"] = probe_id
        if target_override:
            kwargs["target_override"] = target_override

        session = ConnectHelper.session_with_chosen_probe(**kwargs)
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
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available.")
        kwargs = {"auto_open": True}
        if probe_id:
            kwargs["unique_id"] = probe_id
        if target_override:
            kwargs["target_override"] = target_override

        session = ConnectHelper.session_with_chosen_probe(**kwargs)
        with session:
            target = session.board.target
            target.write32(address, value)
            return {"address": f"0x{address:08X}", "value": f"0x{value:08X}", "status": "success"}

    @staticmethod
    def reset_target(halt: bool = False, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available.")
        kwargs = {"auto_open": True}
        if probe_id:
            kwargs["unique_id"] = probe_id
        if target_override:
            kwargs["target_override"] = target_override

        session = ConnectHelper.session_with_chosen_probe(**kwargs)
        with session:
            target = session.board.target
            if halt:
                target.reset_and_halt()
            else:
                target.reset()
            return {"status": "success", "halted": halt}

    @staticmethod
    def flash_firmware(file_path: str, target_override: Optional[str] = None, probe_id: Optional[str] = None) -> Dict[str, Any]:
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available.")
        
        kwargs = {"auto_open": True}
        if probe_id:
            kwargs["unique_id"] = probe_id
        if target_override:
            kwargs["target_override"] = target_override

        session = ConnectHelper.session_with_chosen_probe(**kwargs)
        with session:
            programmer = FileProgrammer(session)
            programmer.program(file_path)
            session.board.target.reset()
            trim_process_memory()
            return {"status": "success", "file_path": file_path, "message": "Flashing and reset completed successfully."}

    @staticmethod
    def diagnose_hardfault(probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        """Comprehensive HardFault diagnosis."""
        regs_info = PyOCDController.read_core_registers(probe_id, target_override)
        cfsr_data = regs_info.get("cfsr_decoded", {})
        hfsr_data = regs_info.get("hfsr_decoded", {})
        core_regs = regs_info.get("core_registers", {})
        fault_regs = regs_info.get("fault_registers", {})

        pc = core_regs.get("PC", "0x00000000")
        lr = core_regs.get("LR", "0x00000000")
        msp = core_regs.get("MSP", "0x00000000")
        bfar = fault_regs.get("BFAR", "0x00000000")

        # Compile AI diagnostic summary
        diagnosis_lines = []
        diagnosis_lines.append("=== Cortex-M HardFault 智能分析诊断报告 ===")
        diagnosis_lines.append(f"崩溃发生程序计数器 (PC): {pc}")
        diagnosis_lines.append(f"返回链接寄存器 (LR/EXC_RETURN): {lr}")
        diagnosis_lines.append(f"主栈指针 (MSP): {msp}")

        if "FORCED" in hfsr_data.get("flags", []):
            diagnosis_lines.append("• 故障类型: 强制硬故障 (Forced HardFault)，由低级故障升级触发。")

        if cfsr_data.get("flags"):
            diagnosis_lines.append(f"• 触发状态标志: {', '.join(cfsr_data['flags'])}")
            for exp in cfsr_data.get("explanations", []):
                diagnosis_lines.append(f"  - {exp}")
        else:
            diagnosis_lines.append("• 未检测到可配置故障标志 (CFSR=0)，可能是中断向量表错误或非法指令栈破坏。")

        # Specific recommendations
        recommendations = []
        cfsr_flags_str = " ".join(cfsr_data.get("flags", []))
        if "BFARVALID" in cfsr_flags_str:
            recommendations.append(f"检查对地址 {bfar} 的读写操作：确认对应外设时钟（如 RCC_APB1/2/AHB）是否已在代码中使能。")
        if "INVSTATE" in cfsr_flags_str:
            recommendations.append("检查函数指针跳转：ARM Cortex-M 仅支持 Thumb 模式，请确保函数指针地址的最低有效位 (LSB) 为 1。")
        if "UNALIGNED" in cfsr_flags_str:
            recommendations.append("检查结构体或数据指针对齐：是否存在未对齐的 32 位内存访问。")
        if "NOCP" in cfsr_flags_str:
            recommendations.append("浮点运算协处理器未使能：若在中断中使用了浮点计算，请在初始化时开启 SCB->CPACR 的 CP10 与 CP11 访问权限。")

        return {
            "summary": "\n".join(diagnosis_lines),
            "recommendations": recommendations,
            "raw_dump": regs_info
        }


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

    @classmethod
    def start_rtt(cls, probe_id: Optional[str] = None, target_override: Optional[str] = None,
                  block_address: Optional[int] = None, probe_type: Optional[str] = None) -> Dict[str, Any]:
        with cls._lock:
            if cls._running:
                return {
                    "status": "already_running",
                    "tcp_port": cls._tcp_port,
                    "mode": cls._mode
                }

            # Create ephemeral TCP server for bi-directional streaming
            cls._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            cls._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            cls._server_sock.bind(("127.0.0.1", 0))
            cls._server_sock.listen(1)
            cls._tcp_port = cls._server_sock.getsockname()[1]

            # Decide probe type if not specified
            chosen_type = (probe_type or "").lower()
            if not chosen_type:
                # Check probe description
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
                "probe_type": chosen_type
            }

    @classmethod
    def _start_jlink(cls, probe_id: Optional[str], target_override: Optional[str], block_address: Optional[int]):
        cls._jlink = pylink.JLink()
        if probe_id and probe_id.isdigit():
            cls._jlink.open(int(probe_id))
        else:
            cls._jlink.open()

        chip = target_override or "Cortex-M4"
        cls._jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
        cls._jlink.connect(chip)
        cls._jlink.rtt_start(block_address)
        logger.info(f"J-Link RTT started on target {chip} (CB addr: {block_address})")

    @classmethod
    def _start_pyocd(cls, probe_id: Optional[str], target_override: Optional[str], block_address: Optional[int]):
        if not PYOCD_AVAILABLE:
            raise RuntimeError("PyOCD is not available for DAPLink RTT")

        kwargs = {"auto_open": True}
        if probe_id:
            kwargs["unique_id"] = probe_id
        if target_override:
            kwargs["target_override"] = target_override

        cls._session = ConnectHelper.session_with_chosen_probe(**kwargs)
        cls._session.open()
        logger.info(f"PyOCD session opened for RTT on probe {probe_id}")

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
        # For PyOCD, maintain scanned RTT CB state
        cb_address = None
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
                        # Search for "SEGGER RTT" in RAM (e.g. 0x20000000 - 0x20010000)
                        try:
                            start_ram = 0x20000000
                            scan_len = 0x10000 // 4  # 64KB scan range
                            words = target.read_memory_block32(start_ram, scan_len)
                            # Magic string: "SEGGER RTT\0" -> 0x47455320, etc.
                            # Scan bytes
                            raw_bytes = bytearray()
                            for w in words:
                                raw_bytes.extend(w.to_bytes(4, 'little'))
                            magic_idx = raw_bytes.find(b"SEGGER RTT")
                            if magic_idx != -1:
                                cb_address = start_ram + magic_idx
                                # Parse Up Buffer 0 info:
                                # Header: acID(16), MaxNumUp(4), MaxNumDown(4) -> 24 bytes offset to aUp[0]
                                # aUp[0]: sName(4), pBuffer(4), SizeOfBuffer(4), WrOff(4), RdOff(4), Flags(4)
                                up_buf_ptr = int.from_bytes(raw_bytes[magic_idx+28:magic_idx+32], 'little')
                                up_buf_size = int.from_bytes(raw_bytes[magic_idx+32:magic_idx+36], 'little')
                                logger.info(f"PyOCD found SEGGER RTT CB at 0x{cb_address:08X}, UpBuffer: 0x{up_buf_ptr:08X} ({up_buf_size} bytes)")
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
    _vars = []  # [{name, address, size, type}]

    _mode = None
    _jlink = None
    _session = None

    @classmethod
    def start_sampling(cls, variables: List[Dict[str, Any]], interval_ms: int = 20,
                       probe_id: Optional[str] = None, target_override: Optional[str] = None,
                       probe_type: Optional[str] = None) -> Dict[str, Any]:
        with cls._lock:
            if cls._running:
                cls.stop_sampling()

            if not variables:
                raise ValueError("No variables specified for JScope sampling")

            cls._vars = variables
            cls._interval_ms = max(5, interval_ms)

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
                    cls._mode = "jlink"
                except Exception as e:
                    logger.warning(f"JScope JLink connect failed, fallback to PyOCD: {e}")
                    kwargs = {"auto_open": True}
                    if probe_id:
                        kwargs["unique_id"] = probe_id
                    if target_override:
                        kwargs["target_override"] = target_override
                    cls._session = ConnectHelper.session_with_chosen_probe(**kwargs)
                    cls._session.open()
                    cls._mode = "pyocd"
            else:
                if not PYOCD_AVAILABLE:
                    raise RuntimeError("PyOCD not available for sampling")
                kwargs = {"auto_open": True}
                if probe_id:
                    kwargs["unique_id"] = probe_id
                if target_override:
                    kwargs["target_override"] = target_override
                cls._session = ConnectHelper.session_with_chosen_probe(**kwargs)
                cls._session.open()
                cls._mode = "pyocd"

            cls._thread = threading.Thread(target=cls._sample_worker_loop, daemon=True)
            cls._thread.start()

            return {
                "status": "started",
                "tcp_port": cls._tcp_port,
                "interval_ms": cls._interval_ms,
                "mode": cls._mode,
                "variable_count": len(cls._vars)
            }

    @classmethod
    def _sample_worker_loop(cls):
        logger.info(f"JScope sampling TCP bridge listening on port {cls._tcp_port}")
        cls._server_sock.settimeout(3.0)

        client = None
        while cls._running:
            try:
                client, addr = cls._server_sock.accept()
                logger.info(f"JScope client connected from {addr}")
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

        interval_sec = cls._interval_ms / 1000.0

        while cls._running:
            try:
                start_time = time.time()
                # Read all watched variables
                line_parts = []

                for v in cls._vars:
                    name = v["name"]
                    addr = v["raw_address"] if "raw_address" in v else int(v["address"], 16)
                    size = int(v.get("size", 4))
                    vtype = v.get("type", "int32")

                    raw_bytes = None
                    try:
                        if cls._mode == "jlink" and cls._jlink:
                            raw_bytes = bytes(cls._jlink.memory_read8(addr, size))
                        elif cls._mode == "pyocd" and cls._session:
                            target = cls._session.board.target
                            raw_bytes = bytes(target.read_memory_block8(addr, size))
                    except Exception as err:
                        logger.debug(f"Read var {name} failed: {err}")

                    if raw_bytes and len(raw_bytes) >= size:
                        val = 0
                        try:
                            if vtype == "float32" and size == 4:
                                val = struct.unpack("<f", raw_bytes[:4])[0]
                            elif vtype == "float64" and size == 8:
                                val = struct.unpack("<d", raw_bytes[:8])[0]
                            elif vtype == "int32" and size == 4:
                                val = struct.unpack("<i", raw_bytes[:4])[0]
                            elif vtype == "uint32" and size == 4:
                                val = struct.unpack("<I", raw_bytes[:4])[0]
                            elif vtype == "int16" and size >= 2:
                                val = struct.unpack("<h", raw_bytes[:2])[0]
                            elif vtype == "uint16" and size >= 2:
                                val = struct.unpack("<H", raw_bytes[:2])[0]
                            elif vtype == "int8" and size >= 1:
                                val = struct.unpack("<b", raw_bytes[:1])[0]
                            elif vtype == "uint8" and size >= 1:
                                val = struct.unpack("<B", raw_bytes[:1])[0]
                            else:
                                val = struct.unpack("<I", raw_bytes[:4])[0]
                        except Exception:
                            val = 0

                        # Format as Telemetry protocol key:value
                        if isinstance(val, float):
                            line_parts.append(f"{name}:{val:.3f}")
                        else:
                            line_parts.append(f"{name}:{val}")

                if line_parts:
                    # e.g. "motor_speed:1200 temp:38.5\n"
                    telemetry_line = " ".join(line_parts) + "\n"
                    client.sendall(telemetry_line.encode("utf-8"))

                elapsed = time.time() - start_time
                remain = interval_sec - elapsed
                if remain > 0:
                    time.sleep(remain)
            except Exception as e:
                logger.error(f"JScope sampling loop error: {e}")
                break

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
        "description": "通过 SWD 协议将本地固件文件 (.bin/.hex/.elf) 烧录至目标芯片 Flash",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "本地固件文件的绝对物理路径"},
                "target_override": {"type": "string", "description": "目标单片机芯片型号 (如 stm32f103c8)"},
                "probe_id": {"type": "string", "description": "探针 ID"}
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
        "description": "自动化全流程分析 Cortex-M 硬件硬故障 (HardFault)，提取崩溃现场并输出 AI 诊断建议",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_id": {"type": "string", "description": "探针 ID"},
                "target_override": {"type": "string", "description": "目标芯片型号"}
            }
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
                "block_address": {"type": "integer", "description": "SEGGER RTT 控制块在 RAM 中的起始物理地址 (可选)"}
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
        "description": "启动后台 SWD 高速无侵入周期变量采样 (类似 J-Scope)，通过本地 TCP 桥接输出波形数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "variables": {"type": "array", "description": "待监视变量列表"},
                "interval_ms": {"type": "integer", "description": "采样周期毫秒 (如 20)", "default": 20},
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
    "flash_firmware",
    "reset_target",
    "diagnose_hardfault",
    "start_rtt",
    "stop_rtt",
    "parse_axf_symbols",
    "start_jscope_sampling",
    "stop_jscope_sampling",
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
    elif name == "flash_firmware":
        file_path = arguments["file_path"]
        return PyOCDController.flash_firmware(file_path, target_override, probe_id)
    elif name == "reset_target":
        halt = bool(arguments.get("halt", False))
        return PyOCDController.reset_target(halt, probe_id, target_override)
    elif name == "diagnose_hardfault":
        return PyOCDController.diagnose_hardfault(probe_id, target_override)
    elif name == "start_rtt":
        probe_type = arguments.get("probe_type")
        block_addr = arguments.get("block_address")
        if isinstance(block_addr, str):
            block_addr = int(block_addr, 16 if block_addr.startswith("0x") else 10)
        return RTTController.start_rtt(probe_id, target_override, block_addr, probe_type)
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
        probe_type = arguments.get("probe_type")
        return JScopeController.start_sampling(variables, interval, probe_id, target_override, probe_type)
    elif name == "stop_jscope_sampling":
        return JScopeController.stop_sampling()
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
