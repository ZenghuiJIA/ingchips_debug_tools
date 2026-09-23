#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prototype & Test for Firmware Resource Analyzer (AXF/ELF).
Supports GCC, ARMCC (AC5), and ARMClang (AC6).
"""

import os
import sys
from collections import defaultdict
from typing import Dict, Any, List, Optional
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


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
    Analyzes embedded ARM Cortex-M firmware (.axf / .elf) for total RAM/ROM footprint,
    compiler toolchain detection (GCC, ARMCC, ARMClang), section layout, and module-level attribution.
    """

    @staticmethod
    def analyze(
        file_path: str,
        chip_flash_size: Optional[int] = None,
        chip_ram_size: Optional[int] = None,
        max_symbols_per_module: int = 20
    ) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Firmware file not found: {file_path}")

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
            cu_func_ranges = [] # list of (low_pc, high_pc, cu_name, cu_path)
            cu_files = set()

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
                        cu_files.add((file_base, full_path))

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
                """Binary search for compile unit covering addr."""
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

                                # Try to refine using DWARF CU range map
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

                                # Keep symbol records
                                mod_entry["symbols"].append({
                                    "name": name,
                                    "kind": "func" if exec_instr else "object",
                                    "address": f"0x{st_value:08X}",
                                    "raw_address": st_value,
                                    "size": st_size,
                                    "size_str": format_bytes(st_size),
                                    "category": sym_category
                                })

            # Format and sort modules
            module_list = []
            for mod_key, mod_val in modules_map.items():
                m_code = mod_val["code"]
                m_ro = mod_val["ro_data"]
                m_rw = mod_val["rw_data"]
                m_zi = mod_val["zi_data"]
                m_rom = m_code + m_ro + m_rw
                m_ram = m_rw + m_zi

                # Sort symbols in module by size descending
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

            # Sort modules by ROM total descending
            module_list.sort(key=lambda m: m["rom_total"], reverse=True)

            # 5. Chip Capacity Usage Calculation
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
                "architecture": arch_name,
                "summary": summary,
                "sections": sections_info,
                "modules": module_list,
                "total_modules_count": len(module_list),
                "total_symbols_count": total_symbols_count
            }


if __name__ == "__main__":
    test_files = [
        (r"C:\ming\ING918XX_SDK_SOURCE\examples-gcc\peripheral_console_liteos\peripheral_console_liteos.axf", 512 * 1024, 64 * 1024),
        (r"C:\ming\source\ING_usb_sdk\output\usb_test.axf", 512 * 1024, 128 * 1024),
    ]

    for p, f_size, r_size in test_files:
        print("=" * 60)
        print(f"Testing Analysis on: {p}")
        res = FirmwareResourceAnalyzer.analyze(p, chip_flash_size=f_size, chip_ram_size=r_size)
        print(f"  Toolchain:     {res['toolchain']['name']}")
        print(f"  Architecture:  {res['architecture']}")
        print(f"  ROM Total:     {res['summary']['rom_total_str']} ({res['summary']['flash_usage_percent']}% of {res['summary']['chip_flash_str']})")
        print(f"                 Code={res['summary']['code_str']} ({res['summary']['rom_code_ratio']}%), RO={res['summary']['ro_data_str']}, RW={res['summary']['rw_data_str']}")
        print(f"  RAM Total:     {res['summary']['ram_total_str']} ({res['summary']['ram_usage_percent']}% of {res['summary']['chip_ram_str']})")
        print(f"                 RW={res['summary']['rw_data_str']} ({res['summary']['ram_rw_ratio']}%), ZI={res['summary']['zi_data_str']} ({res['summary']['ram_zi_ratio']}%)")
        print(f"  Total Modules: {res['total_modules_count']}, Total Symbols: {res['total_symbols_count']}")
        print(f"  Sections:      {len(res['sections'])}")
        print("  Top 5 Modules:")
        for m in res['modules'][:5]:
            print(f"    - {m['name']:<25} ROM: {m['rom_total_str']:>9} ({m['rom_percent']:>5}%) | RAM: {m['ram_total_str']:>9} ({m['ram_percent']:>5}%)")
            for sym in m['symbols'][:2]:
                print(f"        * [{sym['kind']}] {sym['name']} ({sym['size_str']}, {sym['category']})")
