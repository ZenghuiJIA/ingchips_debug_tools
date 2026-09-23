#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SvdManager:
Dynamically extracts, parses, and provides register-level and bitfield-level
read/write interfaces for microcontroller peripherals using SVD files bundled in
CMSIS-Pack (.pack) archives or standalone .svd files.

Enhanced with resilient XML sanitization supporting diverse vendor formats
(e.g. leading whitespace, BOMs, non-standard encoding headers, derivedFrom registers).
"""

import os
import sys
import re
import zipfile
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hil_daemon.svd")


def clean_and_parse_svd_xml(raw_bytes: bytes) -> ET.Element:
    """
    Robust XML sanitizer for CMSIS-SVD files from various chip vendors (GigaDevice, ST, NXP, etc.).
    Fixes:
    - Leading spaces/newlines before <?xml (e.g. GigaDevice GD32 pack: 'line 1 column 2' error)
    - UTF-8 / UTF-16 BOM markers
    - Non-standard XML header prefixes and encoding mismatches
    """
    if not raw_bytes:
        raise ValueError("SVD content is empty")

    # 1. Handle UTF-16 LE / BE BOM
    if raw_bytes.startswith(b'\xff\xfe'):
        text = raw_bytes[2:].decode('utf-16-le', errors='ignore')
    elif raw_bytes.startswith(b'\xfe\xff'):
        text = raw_bytes[2:].decode('utf-16-be', errors='ignore')
    elif raw_bytes.startswith(b'\xef\xbb\xbf'):
        text = raw_bytes[3:].decode('utf-8', errors='ignore')
    else:
        # Check encoding declaration in <?xml ... encoding="..." ?>
        match = re.search(rb'encoding=["\']([a-zA-Z0-9_-]+)["\']', raw_bytes[:150])
        if match:
            enc = match.group(1).decode('ascii', errors='ignore').lower()
            try:
                text = raw_bytes.decode(enc, errors='replace')
            except Exception:
                text = raw_bytes.decode('utf-8', errors='replace')
        else:
            text = raw_bytes.decode('utf-8', errors='replace')

    # 2. Strip leading/trailing whitespace and BOM characters from string
    text = text.strip()
    if text.startswith('\ufeff'):
        text = text[1:].strip()

    # 3. Ensure <?xml is at index 0, or if missing/misplaced, slice to <?xml or <device
    xml_decl_idx = text.find('<?xml')
    if xml_decl_idx > 0:
        text = text[xml_decl_idx:].strip()
    elif xml_decl_idx < 0:
        device_idx = text.find('<device')
        if device_idx >= 0:
            text = text[device_idx:].strip()

    # 4. Normalize encoding declaration in the header to utf-8 so Expat parser never fails
    text = re.sub(r'encoding=["\'][^"\']+["\']', 'encoding="utf-8"', text, count=1)

    # 5. Parse sanitized XML as UTF-8
    return ET.fromstring(text.encode('utf-8'))


class SvdManager:
    """
    Manages SVD devices, peripherals, registers, bitfields and hardware R/W.
    """
    _pack_instances = {}
    _svd_root_cache = {}

    @classmethod
    def get_loaded_packs(cls) -> List[Any]:
        from daemon_entry import discover_and_load_packs, CMSIS_PACK_AVAILABLE
        if not CMSIS_PACK_AVAILABLE:
            return []
        from pyocd.target.pack.cmsis_pack import CmsisPack

        pack_files = discover_and_load_packs()
        packs = []
        for p in pack_files:
            if p not in cls._pack_instances:
                try:
                    cls._pack_instances[p] = CmsisPack(p)
                except Exception as e:
                    logger.error(f"Failed to load CmsisPack {p}: {e}")
            if p in cls._pack_instances:
                packs.append(cls._pack_instances[p])
        return packs

    @classmethod
    def import_pack(cls, pack_path: str) -> Dict[str, Any]:
        if not os.path.exists(pack_path):
            raise FileNotFoundError(f"Pack file not found: {pack_path}")

        abs_path = os.path.abspath(pack_path)

        # Invalidate SVD parsed tree cache
        cls._svd_root_cache.clear()

        # Register targets and flash algorithms into PyOCD
        try:
            from pyocd.target.pack.pack_target import PackTargets
            PackTargets.populate_targets_from_pack(abs_path)
            logger.info(f"Populated PyOCD targets from imported pack: {abs_path}")
        except Exception as e:
            logger.warning(f"Could not populate PyOCD targets from {abs_path}: {e}")

        # Add to discovered packs list in daemon_entry
        from daemon_entry import _DISCOVERED_PACKS, _PACKS_LOCK
        with _PACKS_LOCK:
            if abs_path not in _DISCOVERED_PACKS:
                _DISCOVERED_PACKS.append(abs_path)

        # Instantiate CmsisPack
        from pyocd.target.pack.cmsis_pack import CmsisPack
        pack = CmsisPack(abs_path)
        cls._pack_instances[abs_path] = pack

        new_devices = []
        for dev in pack.devices:
            flash_size = 0
            flash_start = "0x00000000"
            ram_size = 0
            ram_start = "0x20000000"
            for r in dev.memory_map:
                if r.is_flash:
                    flash_size = max(flash_size, r.length)
                    flash_start = f"0x{r.start:08X}"
                elif r.is_ram:
                    ram_size = max(ram_size, r.length)
                    ram_start = f"0x{r.start:08X}"
            new_devices.append({
                "name": dev.part_number,
                "vendor": dev.vendor,
                "pack": os.path.basename(abs_path),
                "pack_path": abs_path,
                "core": getattr(dev, "core", "Cortex-M"),
                "flash_size": flash_size,
                "flash_start": flash_start,
                "ram_size": ram_size,
                "ram_start": ram_start
            })
        logger.info(f"Imported pack {os.path.basename(abs_path)} with {len(new_devices)} devices")
        return {
            "status": "success",
            "pack": os.path.basename(abs_path),
            "pack_path": abs_path,
            "devices": new_devices
        }

    @classmethod
    def list_devices(cls) -> List[Dict[str, Any]]:
        devices = []
        seen = set()
        for pack in cls.get_loaded_packs():
            for dev in pack.devices:
                if dev.part_number in seen:
                    continue
                seen.add(dev.part_number)
                flash_size = 0
                flash_start = "0x00000000"
                ram_size = 0
                ram_start = "0x20000000"
                for r in dev.memory_map:
                    if r.is_flash:
                        flash_size = max(flash_size, r.length)
                        flash_start = f"0x{r.start:08X}"
                    elif r.is_ram:
                        ram_size = max(ram_size, r.length)
                        ram_start = f"0x{r.start:08X}"
                devices.append({
                    "name": dev.part_number,
                    "vendor": dev.vendor,
                    "pack": os.path.basename(pack.pack_path),
                    "pack_path": pack.pack_path,
                    "core": getattr(dev, "core", "Cortex-M"),
                    "flash_size": flash_size,
                    "flash_start": flash_start,
                    "ram_size": ram_size,
                    "ram_start": ram_start
                })
        return devices

    @classmethod
    def _find_device_svd(cls, device_name: str, custom_svd_path: Optional[str] = None) -> bytes:
        if custom_svd_path and os.path.exists(custom_svd_path):
            with open(custom_svd_path, "rb") as f:
                return f.read()

        d_lower = device_name.lower().replace("_", "").replace("-", "")

        # 1. Exact match pass
        for pack in cls.get_loaded_packs():
            for dev in pack.devices:
                part_clean = dev.part_number.lower().replace("_", "").replace("-", "")
                if part_clean == d_lower:
                    try:
                        stream = dev.svd
                        if stream:
                            stream.seek(0)
                            return stream.read()
                    except Exception as e:
                        logger.warning(f"Error accessing dev.svd for {dev.part_number}: {e}")

        # 2. Substring match pass
        for pack in cls.get_loaded_packs():
            for dev in pack.devices:
                part_clean = dev.part_number.lower().replace("_", "").replace("-", "")
                if part_clean in d_lower or d_lower in part_clean:
                    try:
                        stream = dev.svd
                        if stream:
                            stream.seek(0)
                            return stream.read()
                    except Exception as e:
                        logger.warning(f"Error accessing dev.svd for {dev.part_number}: {e}")

        # 3. Direct zip inspection fallback for any matching .svd in loaded packs
        for pack in cls.get_loaded_packs():
            if os.path.exists(pack.pack_path):
                try:
                    with zipfile.ZipFile(pack.pack_path, "r") as z:
                        svd_names = [f for f in z.namelist() if f.lower().endswith(".svd")]
                        # Match filename
                        for s_name in svd_names:
                            base_no_ext = os.path.splitext(os.path.basename(s_name))[0].lower().replace("_", "").replace("-", "")
                            if base_no_ext in d_lower or d_lower in base_no_ext:
                                return z.read(s_name)
                        # If only one svd in pack, use it
                        if len(svd_names) == 1:
                            return z.read(svd_names[0])
                except Exception as e:
                    logger.warning(f"Zip fallback read failed for {pack.pack_path}: {e}")

        raise ValueError(f"Device SVD for '{device_name}' not found in loaded packs.")

    @classmethod
    def _get_device_svd_root(cls, device_name: str, custom_svd_path: Optional[str] = None) -> ET.Element:
        cache_key = f"{device_name}::{custom_svd_path or ''}"
        if cache_key in cls._svd_root_cache:
            return cls._svd_root_cache[cache_key]

        raw_bytes = cls._find_device_svd(device_name, custom_svd_path)
        root = clean_and_parse_svd_xml(raw_bytes)
        cls._svd_root_cache[cache_key] = root
        return root

    @classmethod
    def get_peripherals(cls, device_name: str, custom_svd_path: Optional[str] = None) -> List[Dict[str, Any]]:
        root = cls._get_device_svd_root(device_name, custom_svd_path)

        # Pre-build peripheral map for derivedFrom description lookups
        all_periphs = {p.findtext("name", "").strip(): p for p in root.findall(".//peripheral")}

        periphs = []
        for p in root.findall(".//peripheral"):
            name = p.findtext("name", "").strip()
            base_addr = p.findtext("baseAddress", "0")
            desc = p.findtext("description", "").strip()
            group = p.findtext("groupName", "")

            # If description is missing, inherit from derivedFrom
            if not desc:
                derived_name = p.get("derivedFrom")
                if derived_name and derived_name.strip() in all_periphs:
                    desc = all_periphs[derived_name.strip()].findtext("description", "").strip()

            try:
                base_int = int(base_addr, 16 if base_addr.startswith("0x") else 10)
            except Exception:
                base_int = 0

            periphs.append({
                "name": name,
                "base_address": f"0x{base_int:08X}",
                "raw_base_address": base_int,
                "description": desc,
                "group_name": group,
            })

        periphs.sort(key=lambda x: x["raw_base_address"])
        return periphs

    @classmethod
    def get_registers(cls, device_name: str, peripheral_name: str, custom_svd_path: Optional[str] = None) -> List[Dict[str, Any]]:
        root = cls._get_device_svd_root(device_name, custom_svd_path)

        all_periphs = {p.findtext("name", "").strip(): p for p in root.findall(".//peripheral")}
        if peripheral_name not in all_periphs:
            raise ValueError(f"Peripheral '{peripheral_name}' not found in device '{device_name}'")

        target_p = all_periphs[peripheral_name]

        # Critical: ALWAYS use the target peripheral's own baseAddress!
        base_addr_str = target_p.findtext("baseAddress", "0")
        try:
            base_addr = int(base_addr_str, 16 if base_addr_str.startswith("0x") else 10)
        except Exception:
            base_addr = 0

        # If target peripheral has no register definitions, resolve through derivedFrom chain
        source_p = target_p
        depth = 0
        while len(source_p.findall(".//register")) == 0 and depth < 6:
            derived_name = source_p.get("derivedFrom")
            if not derived_name or derived_name.strip() not in all_periphs:
                break
            source_p = all_periphs[derived_name.strip()]
            depth += 1

        # Map all register nodes by name for <register derivedFrom="..."> resolution
        reg_by_name: Dict[str, ET.Element] = {}
        for r in source_p.findall(".//register"):
            r_name = r.findtext("name", "").strip()
            if r_name:
                reg_by_name[r_name] = r

        def parse_register_element(r: ET.Element, cluster_offset: int = 0) -> List[Dict[str, Any]]:
            # Handle register-level derivedFrom
            derived_name = r.get("derivedFrom")
            base_r = reg_by_name.get(derived_name.strip()) if derived_name else None

            name_tmpl = r.findtext("name", getattr(base_r, "findtext", lambda *a: "")("name", "")).strip()
            desc = r.findtext("description", getattr(base_r, "findtext", lambda *a: "")("description", "")).strip()
            offset_str = r.findtext("addressOffset", "0")
            size_str = r.findtext("size", getattr(base_r, "findtext", lambda *a: "")("size", "32"))
            access = r.findtext("access", getattr(base_r, "findtext", lambda *a: "")("access", "read-write"))
            reset_str = r.findtext("resetValue", getattr(base_r, "findtext", lambda *a: "")("resetValue", "0x00000000"))

            try:
                base_offset = int(offset_str, 16 if offset_str.startswith("0x") else 10)
            except Exception:
                base_offset = 0
            base_offset += cluster_offset

            try:
                size = int(size_str, 16 if size_str.startswith("0x") else 10)
            except Exception:
                size = 32

            # Parse fields (inherit from base_r if empty)
            field_nodes = r.findall(".//field")
            if not field_nodes and base_r is not None:
                field_nodes = base_r.findall(".//field")

            fields = []
            for f in field_nodes:
                fname = f.findtext("name", "").strip()
                fdesc = f.findtext("description", "").strip()
                faccess = f.findtext("access", access)

                bit_offset = 0
                bit_width = 1
                if f.find("bitOffset") is not None and f.find("bitWidth") is not None:
                    bit_offset = int(f.findtext("bitOffset"))
                    bit_width = int(f.findtext("bitWidth"))
                elif f.find("lsb") is not None and f.find("msb") is not None:
                    lsb = int(f.findtext("lsb"))
                    msb = int(f.findtext("msb"))
                    bit_offset = lsb
                    bit_width = msb - lsb + 1
                elif f.find("bitRange") is not None:
                    br = f.findtext("bitRange").strip("[]")
                    msb, lsb = map(int, br.split(":"))
                    bit_offset = lsb
                    bit_width = msb - lsb + 1

                msb = bit_offset + bit_width - 1
                range_str = f"[{msb}:{bit_offset}]" if bit_width > 1 else f"[{bit_offset}]"

                fields.append({
                    "name": fname,
                    "description": fdesc,
                    "bit_offset": bit_offset,
                    "bit_width": bit_width,
                    "bit_range": range_str,
                    "access": faccess
                })
            fields.sort(key=lambda x: x["bit_offset"])

            # Handle dimensioned registers (<dim> array expansion)
            dim_str = r.findtext("dim")
            if dim_str:
                try:
                    dim_count = int(dim_str, 16 if dim_str.startswith("0x") else 10)
                except Exception:
                    dim_count = 0

                dim_inc_str = r.findtext("dimIncrement", "4")
                try:
                    dim_inc = int(dim_inc_str, 16 if dim_inc_str.startswith("0x") else 10)
                except Exception:
                    dim_inc = 4

                dim_idx_str = r.findtext("dimIndex")
                dim_indices = [s.strip() for s in dim_idx_str.split(",")] if dim_idx_str else [str(i) for i in range(dim_count)]
                if len(dim_indices) < dim_count:
                    dim_indices.extend([str(i) for i in range(len(dim_indices), dim_count)])

                results = []
                for i in range(dim_count):
                    idx_val = dim_indices[i]
                    if "%s" in name_tmpl:
                        reg_name = name_tmpl % idx_val
                    elif "[%s]" in name_tmpl:
                        reg_name = name_tmpl.replace("[%s]", f"[{idx_val}]")
                    else:
                        reg_name = f"{name_tmpl}_{idx_val}"

                    reg_off = base_offset + (i * dim_inc)
                    reg_abs = base_addr + reg_off
                    results.append({
                        "name": reg_name,
                        "description": desc,
                        "offset": f"0x{reg_off:04X}",
                        "raw_offset": reg_off,
                        "address": f"0x{reg_abs:08X}",
                        "raw_address": reg_abs,
                        "size": size,
                        "access": access,
                        "reset_value": reset_str,
                        "fields": fields
                    })
                return results

            abs_addr = base_addr + base_offset
            return [{
                "name": name_tmpl,
                "description": desc,
                "offset": f"0x{base_offset:04X}",
                "raw_offset": base_offset,
                "address": f"0x{abs_addr:08X}",
                "raw_address": abs_addr,
                "size": size,
                "access": access,
                "reset_value": reset_str,
                "fields": fields
            }]

        registers = []
        registers_elem = source_p.find("registers")
        if registers_elem is not None:
            for child in registers_elem:
                if child.tag == "register":
                    registers.extend(parse_register_element(child, 0))
                elif child.tag == "cluster":
                    cluster_off_str = child.findtext("addressOffset", "0")
                    try:
                        c_off = int(cluster_off_str, 16 if cluster_off_str.startswith("0x") else 10)
                    except Exception:
                        c_off = 0
                    for sub_r in child.findall(".//register"):
                        registers.extend(parse_register_element(sub_r, c_off))
        else:
            for r in source_p.findall(".//register"):
                registers.extend(parse_register_element(r, 0))

        registers.sort(key=lambda x: x["raw_address"])
        return registers

    @classmethod
    def read_register(cls, address: int, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        from daemon_entry import PyOCDController
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            val = target.read32(address)
            return {
                "address": f"0x{address:08X}",
                "value": f"0x{val:08X}",
                "value_uint": val,
                "binary": f"{val:032b}",
                "status": "success"
            }

    @classmethod
    def read_all_registers(cls, addresses: List[int], probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        from daemon_entry import PyOCDController
        session = PyOCDController._create_session(probe_id, target_override)
        results = {}
        with session:
            target = session.board.target
            for addr in addresses:
                try:
                    val = target.read32(addr)
                    results[f"0x{addr:08X}"] = {
                        "value": f"0x{val:08X}",
                        "value_uint": val,
                        "binary": f"{val:032b}"
                    }
                except Exception as e:
                    results[f"0x{addr:08X}"] = {"error": str(e)}
        return {"results": results, "status": "success"}

    @classmethod
    def write_register(cls, address: int, value: int, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        from daemon_entry import PyOCDController
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            target.write32(address, value)
            return {
                "address": f"0x{address:08X}",
                "value": f"0x{value:08X}",
                "status": "success"
            }

    @classmethod
    def write_field(cls, address: int, bit_offset: int, bit_width: int, field_value: int, probe_id: Optional[str] = None, target_override: Optional[str] = None) -> Dict[str, Any]:
        from daemon_entry import PyOCDController
        session = PyOCDController._create_session(probe_id, target_override)
        with session:
            target = session.board.target
            current_val = target.read32(address)
            mask = ((1 << bit_width) - 1) << bit_offset
            new_val = (current_val & ~mask) | ((field_value << bit_offset) & mask)
            target.write32(address, new_val)
            return {
                "address": f"0x{address:08X}",
                "old_value": f"0x{current_val:08X}",
                "new_value": f"0x{new_val:08X}",
                "bit_offset": bit_offset,
                "bit_width": bit_width,
                "field_value": field_value,
                "status": "success"
            }
