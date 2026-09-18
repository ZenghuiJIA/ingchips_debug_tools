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
                result.append({
                    "unique_id": p.unique_id,
                    "description": p.description,
                    "vendor_name": getattr(p, "vendor_name", ""),
                    "product_name": getattr(p, "product_name", ""),
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
