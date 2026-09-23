#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MapFileAnalyzer:
Parses Keil MDK (ARMCC/ARMClang) and GNU GCC linker map files into structured
memory layout, treemap data, hierarchy tree, top metrics, module tables, and section tables.
"""

import os
import re
import math
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

def format_bytes(n: int) -> str:
    if n is None:
        return "N/A"
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.2f} KB"
    else:
        return f"{n / (1024 * 1024):.2f} MB"

class MapFileAnalyzer:
    @staticmethod
    def is_map_file(file_path: str) -> bool:
        if file_path.lower().endswith(".map"):
            return True
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(1024)
                if "ARM Linker" in head or "Memory Configuration" in head or "Linker script" in head:
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def analyze(
        cls,
        file_path: str,
        chip_flash_size: Optional[int] = None,
        chip_ram_size: Optional[int] = None,
        max_symbols_per_module: int = 25
    ) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Map file not found: {file_path}")

        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        file_name = os.path.basename(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Check format
        if "ARM Linker" in content or "Memory Map of the image" in content:
            return cls._parse_keil_map(file_path, file_name, file_size, content, chip_flash_size, chip_ram_size, max_symbols_per_module)
        elif "Memory Configuration" in content or "Linker script and memory map" in content:
            return cls._parse_gcc_map(file_path, file_name, file_size, content, chip_flash_size, chip_ram_size, max_symbols_per_module)
        else:
            # Fallback attempt as Keil
            return cls._parse_keil_map(file_path, file_name, file_size, content, chip_flash_size, chip_ram_size, max_symbols_per_module)

    @classmethod
    def _parse_keil_map(
        cls,
        file_path: str,
        file_name: str,
        file_size: int,
        content: str,
        chip_flash_size: Optional[int],
        chip_ram_size: Optional[int],
        max_symbols_per_module: int
    ) -> Dict[str, Any]:
        lines = content.splitlines()

        # Detect toolchain from first line
        toolchain_type = "armcc"
        toolchain_name = "Keil ARMCC / ARMClang Linker"
        raw_producer = lines[0].strip() if lines else ""
        if "ARM Linker, 5" in raw_producer:
            toolchain_name = f"Arm Compiler 5 (armcc / {raw_producer})"
        elif "ARM Linker, 6" in raw_producer or "LLD" in raw_producer:
            toolchain_type = "armclang"
            toolchain_name = f"Arm Compiler 6 (armclang / {raw_producer})"

        # 1. Parse Global Symbols
        in_symbols = False
        symbols_by_obj = defaultdict(list)
        all_functions = []
        all_objects = []

        # 2. Parse Memory Map of the image
        in_mem_map = False
        cur_region = None
        regions = {} # region_name -> dict

        # 3. Parse Grand Totals
        code_bytes = 0
        ro_data_bytes = 0
        rw_data_bytes = 0
        zi_data_bytes = 0
        padding_bytes = 0
        found_grand_totals = False

        for line in lines:
            sline = line.strip()

            # --- Global Symbols Section ---
            if sline.startswith("Global Symbols"):
                in_symbols = True
                continue
            if in_symbols:
                if sline.startswith("========================") or sline.startswith("Memory Map of the image"):
                    in_symbols = False
                else:
                    # Format: Symbol Name  Value  [Ov]  Type  Size  Object(Section)
                    # e.g.: Exception_Handler 0x00004b09 Thumb Code 18 sdk_main.o(i.Exception_Handler)
                    m = re.match(r"^\s*([A-Za-z0-9_\$\.]+)\s+(0x[0-9a-fA-F]+)\s+(?:(?:ARM|Thumb)\s+Code|Data|Number|Zero)\s+(\d+)\s+([^\s]+)", line)
                    if m:
                        sym_name = m.group(1)
                        sym_addr = int(m.group(2), 16)
                        sym_size = int(m.group(3))
                        obj_sec = m.group(4)
                        
                        obj_match = re.match(r"^([^()]+)(?:\(([^)]+)\))?", obj_sec)
                        obj_file = obj_match.group(1) if obj_match else obj_sec
                        sec_name = obj_match.group(2) if (obj_match and obj_match.group(2)) else ""

                        is_code = "Code" in line
                        sym_entry = {
                            "name": sym_name,
                            "address": f"0x{sym_addr:08X}",
                            "raw_address": sym_addr,
                            "size": sym_size,
                            "size_str": format_bytes(sym_size),
                            "type": "Function" if is_code else "Object",
                            "section": sec_name,
                            "object": obj_file
                        }
                        symbols_by_obj[obj_file].append(sym_entry)

                        if is_code and sym_size > 0:
                            all_functions.append(sym_entry)
                        elif not is_code and sym_size > 0 and sym_addr >= 0x20000000:
                            all_objects.append(sym_entry)

            # --- Memory Map of the image ---
            if "Memory Map of the image" in sline:
                in_mem_map = True
                continue
            if in_mem_map:
                if sline.startswith("========================"):
                    in_mem_map = False
                    continue

                if sline.startswith("Execution Region"):
                    m = re.search(r"Execution Region\s+(\w+)\s+\(Base:\s*(0x[0-9a-fA-F]+),\s*Size:\s*(0x[0-9a-fA-F]+)", sline)
                    if m:
                        cur_region = m.group(1)
                        regions[cur_region] = {
                            "name": cur_region,
                            "base": m.group(2),
                            "base_int": int(m.group(2), 16),
                            "size": m.group(3),
                            "size_int": int(m.group(3), 16),
                            "entries": []
                        }
                    continue

                if cur_region and sline.startswith("0x"):
                    parts = sline.split()
                    if len(parts) >= 3 and parts[2] == "PAD":
                        sz = int(parts[1], 16)
                        padding_bytes += sz
                        regions[cur_region]["entries"].append({
                            "addr": parts[0],
                            "addr_int": int(parts[0], 16),
                            "size": sz,
                            "type": "PAD",
                            "attr": "RO" if ("ROM" in cur_region or "FLASH" in cur_region) else "RW",
                            "section": "Padding",
                            "object": "Linker Padding"
                        })
                    elif len(parts) >= 6:
                        sz = int(parts[1], 16)
                        sec_name = parts[5] if len(parts) >= 7 else parts[4]
                        obj_name = parts[-1]
                        regions[cur_region]["entries"].append({
                            "addr": parts[0],
                            "addr_int": int(parts[0], 16),
                            "size": sz,
                            "type": parts[2], # Data, Code, Zero
                            "attr": parts[3], # RO, RW
                            "section": sec_name,
                            "object": obj_name
                        })

            # --- Grand Totals Section ---
            if "Grand Totals" in sline:
                # e.g.: 171084 18582 8784 1180 29120 873812 Grand Totals
                parts = sline.split()
                if len(parts) >= 5:
                    try:
                        code_bytes = int(parts[0])
                        ro_data_bytes = int(parts[1])
                        rw_data_bytes = int(parts[2])
                        zi_data_bytes = int(parts[3])
                        found_grand_totals = True
                    except Exception:
                        pass

        # If grand totals not matched, aggregate from execution regions
        if not found_grand_totals:
            for rname, rdata in regions.items():
                is_rom = "ROM" in rname or "FLASH" in rname
                for e in rdata["entries"]:
                    t = e["type"]
                    a = e["attr"]
                    s = e["size"]
                    if t == "Code":
                        code_bytes += s
                    elif t == "Data" and a == "RO":
                        ro_data_bytes += s
                    elif t == "Data" and a == "RW":
                        if is_rom:
                            # In ROM, data initial values
                            pass
                        else:
                            rw_data_bytes += s
                    elif t == "Zero":
                        zi_data_bytes += s

        rom_total = code_bytes + ro_data_bytes + rw_data_bytes
        ram_total = rw_data_bytes + zi_data_bytes

        # Chip Capacity Defaults if not provided
        # Heuristics: if base address is 0x00004000 or ROM <= 512KB, default 512KB / 64KB (ING91800)
        # If ROM > 512KB or Base 0x02000000, default 2MB / 32KB (ING91600 / ING2000)
        flash_base_addr = 0x00000000
        for rname, rdata in regions.items():
            if "ROM" in rname or "FLASH" in rname:
                flash_base_addr = rdata["base_int"]
                break

        if not chip_flash_size or chip_flash_size <= 0:
            if flash_base_addr >= 0x02000000 or rom_total > 512 * 1024:
                chip_flash_size = 2048 * 1024
            else:
                chip_flash_size = 512 * 1024

        if not chip_ram_size or chip_ram_size <= 0:
            if flash_base_addr >= 0x02000000:
                chip_ram_size = 32 * 1024
            else:
                chip_ram_size = 64 * 1024

        flash_usage_pct = round((rom_total / chip_flash_size) * 100, 2) if chip_flash_size else None
        ram_usage_pct = round((ram_total / chip_ram_size) * 100, 2) if chip_ram_size else None

        # Ratios
        rom_code_ratio = round((code_bytes / rom_total) * 100, 1) if rom_total > 0 else 0
        rom_ro_ratio = round((ro_data_bytes / rom_total) * 100, 1) if rom_total > 0 else 0
        rom_rw_ratio = round((rw_data_bytes / rom_total) * 100, 1) if rom_total > 0 else 0
        ram_rw_ratio = round((rw_data_bytes / ram_total) * 100, 1) if ram_total > 0 else 0
        ram_zi_ratio = round((zi_data_bytes / ram_total) * 100, 1) if ram_total > 0 else 0

        flash_free = max(0, chip_flash_size - rom_total)
        ram_free = max(0, chip_ram_size - ram_total)

        # 4. Modules Aggregation
        modules_dict = defaultdict(lambda: {
            "name": "",
            "full_path": "",
            "library": "",
            "code": 0,
            "ro_data": 0,
            "rw_data": 0,
            "zi_data": 0,
            "padding": 0,
            "symbols": []
        })

        sections_list = []
        libraries_set = set()

        for rname, rdata in regions.items():
            is_rom = "ROM" in rname or "FLASH" in rname
            for e in rdata["entries"]:
                obj_full = e["object"]
                sec_name = e["section"]
                sz = e["size"]
                t = e["type"]
                a = e["attr"]

                # Extract library if e.g. "mc_w.l(rand.o)" or "lllib_lab.lib(ble50_llm.o)"
                lib_name = ""
                mod_name = obj_full
                m_lib = re.match(r"^([^\(]+\.(?:lib|a|l))\(([^)]+)\)", obj_full)
                if m_lib:
                    lib_name = m_lib.group(1)
                    mod_name = m_lib.group(2)
                    libraries_set.add(lib_name)

                m_data = modules_dict[mod_name]
                m_data["name"] = mod_name
                m_data["full_path"] = obj_full
                m_data["library"] = lib_name

                if t == "Code":
                    m_data["code"] += sz
                elif t == "Data" and a == "RO":
                    m_data["ro_data"] += sz
                elif t == "Data" and a == "RW":
                    m_data["rw_data"] += sz
                elif t == "Zero":
                    m_data["zi_data"] += sz
                elif t == "PAD":
                    m_data["padding"] += sz

                sections_list.append({
                    "name": sec_name,
                    "address": e["addr"],
                    "raw_address": e["addr_int"],
                    "size": sz,
                    "size_str": format_bytes(sz),
                    "type": t,
                    "flags": a,
                    "category": "Code" if t == "Code" else ("RO-Data" if (t == "Data" and a == "RO") else ("RW-Data" if (t == "Data" and a == "RW") else ("ZI-Data" if t == "Zero" else "Padding"))),
                    "target": "ROM" if is_rom else "RAM",
                    "object": mod_name
                })

        # Attach symbols to modules
        for mod_name, syms in symbols_by_obj.items():
            clean_name = mod_name
            if "(" in mod_name and ")" in mod_name:
                m_clean = re.search(r"\(([^)]+)\)", mod_name)
                if m_clean:
                    clean_name = m_clean.group(1)
            if clean_name in modules_dict:
                modules_dict[clean_name]["symbols"].extend(syms)

        module_list = []
        for mod_name, m_data in modules_dict.items():
            rom_m = m_data["code"] + m_data["ro_data"] + m_data["rw_data"]
            ram_m = m_data["rw_data"] + m_data["zi_data"]
            m_syms = m_data["symbols"]
            m_syms.sort(key=lambda s: s["size"], reverse=True)

            module_list.append({
                "name": mod_name,
                "full_path": m_data["full_path"],
                "library": m_data["library"],
                "rom_total": rom_m,
                "rom_total_str": format_bytes(rom_m),
                "rom_percent": round((rom_m / rom_total) * 100, 2) if rom_total > 0 else 0,
                "ram_total": ram_m,
                "ram_total_str": format_bytes(ram_m),
                "ram_percent": round((ram_m / ram_total) * 100, 2) if ram_total > 0 else 0,
                "code": m_data["code"],
                "code_str": format_bytes(m_data["code"]),
                "ro_data": m_data["ro_data"],
                "ro_data_str": format_bytes(m_data["ro_data"]),
                "rw_data": m_data["rw_data"],
                "rw_data_str": format_bytes(m_data["rw_data"]),
                "zi_data": m_data["zi_data"],
                "zi_data_str": format_bytes(m_data["zi_data"]),
                "padding": m_data["padding"],
                "padding_str": format_bytes(m_data["padding"]),
                "symbols_count": len(m_syms),
                "symbols": m_syms[:max_symbols_per_module]
            })

        module_list.sort(key=lambda m: m["rom_total"], reverse=True)

        # 5. Top Metrics
        all_functions.sort(key=lambda x: x["size"], reverse=True)
        all_objects.sort(key=lambda x: x["size"], reverse=True)

        max_func = all_functions[0] if all_functions else {"name": "N/A", "size": 0, "size_str": "0 B", "object": "N/A"}
        max_obj = all_objects[0] if all_objects else {"name": "N/A", "size": 0, "size_str": "0 B", "object": "N/A"}

        # Calculate heap & stack & free gap
        heap_size = 0
        stack_size = 0
        heap_obj = None
        for m in module_list:
            if "heap" in m["name"].lower():
                heap_size = m["zi_data"] or m["ram_total"]
                heap_obj = m["name"]
                break
        if not heap_size:
            # Check symbols for heap/stack
            for s in all_objects:
                if "heap" in s["name"].lower():
                    heap_size = s["size"]
                    heap_obj = s["name"]
                    break

        # Estimated stack size: default 2KB to 8KB or from symbol
        for s in all_objects:
            if "stack" in s["name"].lower():
                stack_size = s["size"]
                break
        if not stack_size:
            stack_size = 1024 * 4 # Default 4KB stack

        free_gap = max(0, ram_free)
        low_margin_warning = free_gap < 2048 # Alert if under 2KB

        # 6. Linear Memory Layout
        # FLASH blocks
        flash_blocks = []
        for sec in sections_list:
            if sec["target"] == "ROM":
                # Combine or take sections with size > 0
                if sec["size"] > 0:
                    flash_blocks.append({
                        "name": sec["name"],
                        "start": sec["address"],
                        "size": sec["size"],
                        "size_str": sec["size_str"],
                        "type": sec["category"].lower().replace("-", "_"),
                        "section": sec["name"],
                        "object": sec["object"]
                    })

        # Compress consecutive small sections into notable blocks for clean visualization
        compressed_flash = cls._compress_linear_blocks(flash_blocks, rom_total)

        # RAM blocks
        ram_blocks = [
            {
                "name": ".data (RW)",
                "type": "rw",
                "size": rw_data_bytes,
                "size_str": format_bytes(rw_data_bytes),
                "growth": "none"
            },
            {
                "name": ".bss (ZI)",
                "type": "zi",
                "size": max(0, zi_data_bytes - heap_size),
                "size_str": format_bytes(max(0, zi_data_bytes - heap_size)),
                "growth": "none"
            }
        ]
        if heap_size > 0:
            ram_blocks.append({
                "name": f"Heap ({heap_obj or '堆'}) (↑)",
                "type": "heap",
                "size": heap_size,
                "size_str": format_bytes(heap_size),
                "growth": "up"
            })
        ram_blocks.append({
            "name": f"Free Gap ({format_bytes(free_gap)})" + (" ⚠️ 低余量" if low_margin_warning else ""),
            "type": "free",
            "size": free_gap,
            "size_str": format_bytes(free_gap),
            "warning": low_margin_warning,
            "growth": "none"
        })
        ram_blocks.append({
            "name": f"Stack (栈) (↓)",
            "type": "stack",
            "size": stack_size,
            "size_str": format_bytes(stack_size),
            "growth": "down"
        })

        # 7. Treemap Hierarchies
        # Flash Treemap
        flash_treemap = {
            "name": "FLASH",
            "size": rom_total,
            "categories": [
                {
                    "name": ".text (Code)",
                    "type": "code",
                    "color": "#3b82f6",
                    "size": code_bytes,
                    "size_str": format_bytes(code_bytes),
                    "percent": rom_code_ratio,
                    "items": [
                        {"name": m["name"], "size": m["code"], "size_str": m["code_str"], "type": "code", "object": m["full_path"]}
                        for m in module_list if m["code"] > 0
                    ][:12]
                },
                {
                    "name": ".rodata (RO)",
                    "type": "ro",
                    "color": "#a855f7",
                    "size": ro_data_bytes,
                    "size_str": format_bytes(ro_data_bytes),
                    "percent": rom_ro_ratio,
                    "items": [
                        {"name": m["name"], "size": m["ro_data"], "size_str": m["ro_data_str"], "type": "ro", "object": m["full_path"]}
                        for m in module_list if m["ro_data"] > 0
                    ][:12]
                },
                {
                    "name": ".data_init (RW)",
                    "type": "rw",
                    "color": "#f97316",
                    "size": rw_data_bytes,
                    "size_str": format_bytes(rw_data_bytes),
                    "percent": rom_rw_ratio,
                    "items": [
                        {"name": m["name"], "size": m["rw_data"], "size_str": m["rw_data_str"], "type": "rw", "object": m["full_path"]}
                        for m in module_list if m["rw_data"] > 0
                    ][:8]
                },
                {
                    "name": "Padding",
                    "type": "padding",
                    "color": "#64748b",
                    "size": padding_bytes,
                    "size_str": format_bytes(padding_bytes),
                    "percent": round((padding_bytes / rom_total) * 100, 1) if rom_total > 0 else 0,
                    "items": [
                        {"name": "对齐间隙 (Padding)", "size": padding_bytes, "size_str": format_bytes(padding_bytes), "type": "padding", "object": "Linker"}
                    ]
                }
            ]
        }

        # RAM Treemap
        ram_treemap = {
            "name": "RAM",
            "size": ram_total,
            "categories": [
                {
                    "name": ".data (RW)",
                    "type": "rw",
                    "color": "#f97316",
                    "size": rw_data_bytes,
                    "size_str": format_bytes(rw_data_bytes),
                    "percent": ram_rw_ratio,
                    "items": [
                        {"name": m["name"], "size": m["rw_data"], "size_str": m["rw_data_str"], "type": "rw", "object": m["full_path"]}
                        for m in module_list if m["rw_data"] > 0
                    ][:8]
                },
                {
                    "name": ".bss (ZI)",
                    "type": "zi",
                    "color": "#22c55e",
                    "size": zi_data_bytes,
                    "size_str": format_bytes(zi_data_bytes),
                    "percent": ram_zi_ratio,
                    "items": [
                        {"name": m["name"], "size": m["zi_data"], "size_str": m["zi_data_str"], "type": "zi", "object": m["full_path"]}
                        for m in module_list if m["zi_data"] > 0
                    ][:12]
                },
                {
                    "name": "Heap (堆)",
                    "type": "heap",
                    "color": "#06b6d4",
                    "size": heap_size,
                    "size_str": format_bytes(heap_size),
                    "percent": round((heap_size / chip_ram_size) * 100, 1) if chip_ram_size else 0,
                    "items": [
                        {"name": f"动态堆 ({heap_obj or 'Heap'})", "size": heap_size, "size_str": format_bytes(heap_size), "type": "heap", "object": heap_obj or "OS Heap"}
                    ]
                },
                {
                    "name": "Free Gap (可用)",
                    "type": "free",
                    "color": "#1e293b",
                    "size": free_gap,
                    "size_str": format_bytes(free_gap),
                    "percent": round((free_gap / chip_ram_size) * 100, 1) if chip_ram_size else 0,
                    "items": [
                        {"name": "未分配自由 SRAM", "size": free_gap, "size_str": format_bytes(free_gap), "type": "free", "object": "System RAM"}
                    ]
                }
            ]
        }

        # 8. Hierarchy Tree (Left Sidebar)
        hierarchy_tree = [
            {
                "id": "flash",
                "label": "FLASH",
                "size": rom_total,
                "size_str": format_bytes(rom_total),
                "type": "region",
                "children": [
                    {"id": "flash_code", "label": ".text (代码)", "size": code_bytes, "size_str": format_bytes(code_bytes), "type": "code"},
                    {"id": "flash_ro", "label": ".rodata (只读数据)", "size": ro_data_bytes, "size_str": format_bytes(ro_data_bytes), "type": "ro"},
                    {"id": "flash_rw_init", "label": ".data_init (数据初值)", "size": rw_data_bytes, "size_str": format_bytes(rw_data_bytes), "type": "rw"},
                    {"id": "flash_padding", "label": "Padding (对齐填充)", "size": padding_bytes, "size_str": format_bytes(padding_bytes), "type": "padding"}
                ]
            },
            {
                "id": "ram",
                "label": "RAM",
                "size": ram_total,
                "size_str": format_bytes(ram_total),
                "type": "region",
                "children": [
                    {"id": "ram_data", "label": ".data (全局变量)", "size": rw_data_bytes, "size_str": format_bytes(rw_data_bytes), "type": "rw"},
                    {"id": "ram_bss", "label": ".bss (零初始化)", "size": zi_data_bytes, "size_str": format_bytes(zi_data_bytes), "type": "zi"},
                    {"id": "ram_heap", "label": "Heap (堆空间 ↑)", "size": heap_size, "size_str": format_bytes(heap_size), "type": "heap"},
                    {"id": "ram_stack", "label": "Stack (调用栈 ↓)", "size": stack_size, "size_str": format_bytes(stack_size), "type": "stack"},
                    {"id": "ram_free", "label": "Free Gap (空闲)", "size": free_gap, "size_str": format_bytes(free_gap), "type": "free"}
                ]
            },
            {
                "id": "libraries",
                "label": f"Libraries ({len(libraries_set)} 个静态库)",
                "size": sum(m["rom_total"] for m in module_list if m["library"]),
                "size_str": format_bytes(sum(m["rom_total"] for m in module_list if m["library"])),
                "type": "libs",
                "children": [
                    {
                        "id": f"lib_{lib}",
                        "label": lib,
                        "size": sum(m["rom_total"] for m in module_list if m["library"] == lib),
                        "size_str": format_bytes(sum(m["rom_total"] for m in module_list if m["library"] == lib)),
                        "type": "lib"
                    }
                    for lib in sorted(libraries_set)
                ]
            },
            {
                "id": "diagnostics",
                "label": "Diagnostics (解析状态)",
                "size": 0,
                "size_str": "0 B",
                "type": "diag",
                "children": [
                    {"id": "diag_padding", "label": f"Padding 损耗: {format_bytes(padding_bytes)}", "size": padding_bytes, "size_str": format_bytes(padding_bytes), "type": "warning" if padding_bytes > 1024 else "info"},
                    {"id": "diag_gap", "label": f"堆栈安全间隙: {format_bytes(free_gap)}" + (" (⚠️ 低余量告警)" if low_margin_warning else ""), "size": free_gap, "size_str": format_bytes(free_gap), "type": "warning" if low_margin_warning else "info"}
                ]
            }
        ]

        summary = {
            "rom_total": rom_total,
            "rom_total_str": format_bytes(rom_total),
            "ram_total": ram_total,
            "ram_total_str": format_bytes(ram_total),
            "code": code_bytes,
            "code_str": format_bytes(code_bytes),
            "ro_data": ro_data_bytes,
            "ro_data_str": format_bytes(ro_data_bytes),
            "rw_data": rw_data_bytes,
            "rw_data_str": format_bytes(rw_data_bytes),
            "zi_data": zi_data_bytes,
            "zi_data_str": format_bytes(zi_data_bytes),
            "padding_total": padding_bytes,
            "padding_total_str": format_bytes(padding_bytes),
            "rom_code_ratio": rom_code_ratio,
            "rom_ro_ratio": rom_ro_ratio,
            "rom_rw_ratio": rom_rw_ratio,
            "ram_rw_ratio": ram_rw_ratio,
            "ram_zi_ratio": ram_zi_ratio,
            "chip_flash_bytes": chip_flash_size,
            "chip_ram_bytes": chip_ram_size,
            "chip_flash_str": format_bytes(chip_flash_size),
            "chip_ram_str": format_bytes(chip_ram_size),
            "flash_usage_percent": flash_usage_pct,
            "ram_usage_percent": ram_usage_pct,
            "flash_free_bytes": flash_free,
            "ram_free_bytes": ram_free,
            "flash_free_str": format_bytes(flash_free),
            "ram_free_str": format_bytes(ram_free),
            "parse_status": {
                "warnings": 1 if low_margin_warning else 0,
                "inferred": 0,
                "format": "Keil MDK MAP"
            }
        }

        top_metrics = {
            "max_function": max_func,
            "max_object": max_obj,
            "total_padding": {"size": padding_bytes, "size_str": format_bytes(padding_bytes)},
            "heap_stack_gap": {"size": free_gap, "size_str": format_bytes(free_gap), "low_margin": low_margin_warning}
        }

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
            "architecture": "ARM Cortex-M",
            "summary": summary,
            "top_metrics": top_metrics,
            "linear_memory": {
                "flash_base": f"0x{flash_base_addr:08X}",
                "flash_end": f"0x{(flash_base_addr + rom_total):08X}",
                "flash_blocks": compressed_flash,
                "ram_base": "0x20000000",
                "ram_end": f"0x{(0x20000000 + chip_ram_size):08X}",
                "ram_blocks": ram_blocks
            },
            "treemap": {
                "flash": flash_treemap,
                "ram": ram_treemap
            },
            "hierarchy": hierarchy_tree,
            "sections": sections_list,
            "modules": module_list,
            "total_modules_count": len(module_list),
            "total_symbols_count": sum(len(m["symbols"]) for m in module_list)
        }

    @classmethod
    def _compress_linear_blocks(cls, blocks: List[Dict[str, Any]], total_size: int) -> List[Dict[str, Any]]:
        """Compress many small sections into prominent visualization chunks."""
        if not blocks:
            return []
        
        # Priority items to keep explicit: Vector table (RESET), large sections, padding
        result = []
        cur_chunk = None

        for b in blocks:
            # Special sections that should always be distinct
            is_special = (
                "RESET" in b["name"] or
                "vector" in b["name"].lower() or
                b["type"] == "pad" or
                b["size"] > total_size * 0.05 # > 5% of total
            )

            if is_special:
                if cur_chunk:
                    result.append(cur_chunk)
                    cur_chunk = None
                result.append(b)
            else:
                if not cur_chunk:
                    cur_chunk = {
                        "name": b["name"],
                        "start": b["start"],
                        "size": b["size"],
                        "size_str": format_bytes(b["size"]),
                        "type": b["type"],
                        "section": b["name"],
                        "object": b.get("object", "")
                    }
                elif cur_chunk["type"] == b["type"] and (cur_chunk["size"] + b["size"]) < total_size * 0.25:
                    cur_chunk["size"] += b["size"]
                    cur_chunk["size_str"] = format_bytes(cur_chunk["size"])
                    cur_chunk["name"] = f"{cur_chunk['name']}, ..."
                else:
                    result.append(cur_chunk)
                    cur_chunk = {
                        "name": b["name"],
                        "start": b["start"],
                        "size": b["size"],
                        "size_str": format_bytes(b["size"]),
                        "type": b["type"],
                        "section": b["name"],
                        "object": b.get("object", "")
                    }

        if cur_chunk:
            result.append(cur_chunk)

        return result

    @classmethod
    def _parse_gcc_map(cls, file_path, file_name, file_size, content, chip_flash_size, chip_ram_size, max_symbols_per_module):
        """Parse GNU ld map file."""
        # Simple parser for GCC ld maps
        lines = content.splitlines()
        toolchain_type = "gcc"
        toolchain_name = "GNU Arm GCC Linker (ld)"
        raw_producer = "GNU ld"

        code_bytes = 0
        ro_data_bytes = 0
        rw_data_bytes = 0
        zi_data_bytes = 0
        padding_bytes = 0

        module_dict = defaultdict(lambda: {"name": "", "full_path": "", "library": "", "code": 0, "ro_data": 0, "rw_data": 0, "zi_data": 0, "padding": 0, "symbols": []})
        sections_list = []

        in_map = False
        for line in lines:
            if "Linker script and memory map" in line:
                in_map = True
                continue
            if not in_map:
                continue

            # Check lines like:  .text.main   0x08000100   0x48 main.o
            m = re.match(r"^\s*(\.[a-zA-Z0-9_\.]+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+([^\s]+)", line)
            if m:
                sec_name = m.group(1)
                addr_int = int(m.group(2), 16)
                sz_int = int(m.group(3), 16)
                obj_file = m.group(4)
                if sz_int == 0 or obj_file.startswith("*fill*"):
                    if obj_file.startswith("*fill*"):
                        padding_bytes += sz_int
                    continue

                mod_name = os.path.basename(obj_file)
                m_data = module_dict[mod_name]
                m_data["name"] = mod_name
                m_data["full_path"] = obj_file

                cat = "Other"
                if sec_name.startswith(".text"):
                    code_bytes += sz_int
                    m_data["code"] += sz_int
                    cat = "Code"
                elif sec_name.startswith(".rodata"):
                    ro_data_bytes += sz_int
                    m_data["ro_data"] += sz_int
                    cat = "RO-Data"
                elif sec_name.startswith(".data"):
                    rw_data_bytes += sz_int
                    m_data["rw_data"] += sz_int
                    cat = "RW-Data"
                elif sec_name.startswith(".bss"):
                    zi_data_bytes += sz_int
                    m_data["zi_data"] += sz_int
                    cat = "ZI-Data"

                sections_list.append({
                    "name": sec_name,
                    "address": f"0x{addr_int:08X}",
                    "raw_address": addr_int,
                    "size": sz_int,
                    "size_str": format_bytes(sz_int),
                    "type": cat,
                    "flags": "A",
                    "category": cat,
                    "target": "ROM" if cat in ("Code", "RO-Data") else "RAM",
                    "object": mod_name
                })

        rom_total = code_bytes + ro_data_bytes + rw_data_bytes
        ram_total = rw_data_bytes + zi_data_bytes

        if not chip_flash_size: chip_flash_size = 512 * 1024
        if not chip_ram_size: chip_ram_size = 64 * 1024

        summary = {
            "rom_total": rom_total,
            "rom_total_str": format_bytes(rom_total),
            "ram_total": ram_total,
            "ram_total_str": format_bytes(ram_total),
            "code": code_bytes,
            "code_str": format_bytes(code_bytes),
            "ro_data": ro_data_bytes,
            "ro_data_str": format_bytes(ro_data_bytes),
            "rw_data": rw_data_bytes,
            "rw_data_str": format_bytes(rw_data_bytes),
            "zi_data": zi_data_bytes,
            "zi_data_str": format_bytes(zi_data_bytes),
            "padding_total": padding_bytes,
            "padding_total_str": format_bytes(padding_bytes),
            "rom_code_ratio": round((code_bytes / rom_total) * 100, 1) if rom_total > 0 else 0,
            "rom_ro_ratio": round((ro_data_bytes / rom_total) * 100, 1) if rom_total > 0 else 0,
            "rom_rw_ratio": round((rw_data_bytes / rom_total) * 100, 1) if rom_total > 0 else 0,
            "ram_rw_ratio": round((rw_data_bytes / ram_total) * 100, 1) if ram_total > 0 else 0,
            "ram_zi_ratio": round((zi_data_bytes / ram_total) * 100, 1) if ram_total > 0 else 0,
            "chip_flash_bytes": chip_flash_size,
            "chip_ram_bytes": chip_ram_size,
            "chip_flash_str": format_bytes(chip_flash_size),
            "chip_ram_str": format_bytes(chip_ram_size),
            "flash_usage_percent": round((rom_total / chip_flash_size) * 100, 2),
            "ram_usage_percent": round((ram_total / chip_ram_size) * 100, 2),
            "flash_free_bytes": max(0, chip_flash_size - rom_total),
            "ram_free_bytes": max(0, chip_ram_size - ram_total),
            "flash_free_str": format_bytes(max(0, chip_flash_size - rom_total)),
            "ram_free_str": format_bytes(max(0, chip_ram_size - ram_total)),
            "parse_status": {"warnings": 0, "inferred": 0, "format": "GNU ld MAP"}
        }

        module_list = []
        for mod_name, m_data in module_dict.items():
            rom_m = m_data["code"] + m_data["ro_data"] + m_data["rw_data"]
            ram_m = m_data["rw_data"] + m_data["zi_data"]
            module_list.append({
                "name": mod_name,
                "full_path": m_data["full_path"],
                "library": m_data["library"],
                "rom_total": rom_m,
                "rom_total_str": format_bytes(rom_m),
                "rom_percent": round((rom_m / rom_total) * 100, 2) if rom_total > 0 else 0,
                "ram_total": ram_m,
                "ram_total_str": format_bytes(ram_m),
                "ram_percent": round((ram_m / ram_total) * 100, 2) if ram_total > 0 else 0,
                "code": m_data["code"],
                "code_str": format_bytes(m_data["code"]),
                "ro_data": m_data["ro_data"],
                "ro_data_str": format_bytes(m_data["ro_data"]),
                "rw_data": m_data["rw_data"],
                "rw_data_str": format_bytes(m_data["rw_data"]),
                "zi_data": m_data["zi_data"],
                "zi_data_str": format_bytes(m_data["zi_data"]),
                "padding": m_data["padding"],
                "padding_str": format_bytes(m_data["padding"]),
                "symbols_count": 0,
                "symbols": []
            })
        module_list.sort(key=lambda m: m["rom_total"], reverse=True)

        return {
            "file_path": file_path,
            "file_name": file_name,
            "file_size": file_size,
            "file_size_str": format_bytes(file_size),
            "toolchain": {"type": toolchain_type, "name": toolchain_name, "raw_producer": raw_producer},
            "architecture": "ARM Cortex-M",
            "summary": summary,
            "top_metrics": {
                "max_function": {"name": "N/A", "size": 0, "size_str": "0 B"},
                "max_object": {"name": "N/A", "size": 0, "size_str": "0 B"},
                "total_padding": {"size": padding_bytes, "size_str": format_bytes(padding_bytes)},
                "heap_stack_gap": {"size": max(0, chip_ram_size - ram_total), "size_str": format_bytes(max(0, chip_ram_size - ram_total)), "low_margin": False}
            },
            "linear_memory": {
                "flash_base": "0x08000000",
                "flash_end": f"0x{(0x08000000 + rom_total):08X}",
                "flash_blocks": [],
                "ram_base": "0x20000000",
                "ram_end": f"0x{(0x20000000 + chip_ram_size):08X}",
                "ram_blocks": []
            },
            "treemap": {
                "flash": {"name": "FLASH", "size": rom_total, "categories": []},
                "ram": {"name": "RAM", "size": ram_total, "categories": []}
            },
            "hierarchy": [],
            "sections": sections_list,
            "modules": module_list,
            "total_modules_count": len(module_list),
            "total_symbols_count": 0
        }

if __name__ == "__main__":
    res = MapFileAnalyzer.analyze(r"C:\ming\source\axf_tool\bin\exp_ING9188xx.map")
    print("Parsed Keil MAP successfully!")
    print("Summary:", res["summary"])
    print("Top Metrics:", res["top_metrics"])
    print("Linear Flash Blocks:", len(res["linear_memory"]["flash_blocks"]))
    print("Linear RAM Blocks:", len(res["linear_memory"]["ram_blocks"]))
    print("Treemap Flash Categories:", len(res["treemap"]["flash"]["categories"]))
    print("Modules Count:", len(res["modules"]))
