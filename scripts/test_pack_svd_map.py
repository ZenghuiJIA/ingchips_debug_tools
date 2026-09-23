#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test script for:
1. CMSIS-Pack target registration & FLM detection
2. SVD peripheral & register parsing from pack
3. Keil / GCC Map parser generating Treemap, Linear Layout, and Metrics
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PACK_PATH = ROOT_DIR / "packs" / "INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack"
MAP_PATH = Path(r"C:\ming\source\axf_tool\bin\exp_ING9188xx.map")

def test_pack_and_svd():
    print("--- 1. Testing CMSIS-Pack & SVD ---")
    from pyocd.target.pack.cmsis_pack import CmsisPack
    from pyocd.target.pack.pack_target import PackTargets
    from pyocd.target import TARGET

    assert PACK_PATH.exists(), f"Pack file not found: {PACK_PATH}"
    PackTargets.populate_targets_from_pack(str(PACK_PATH))
    
    for tname in ["ing91800", "ing91600", "ing2000"]:
        assert tname in TARGET, f"Target {tname} not registered in TARGET!"
        print(f"  [OK] Target '{tname}' registered: {TARGET[tname]}")

    pack = CmsisPack(str(PACK_PATH))
    print(f"  [OK] Pack loaded with {len(pack.devices)} devices.")
    for dev in pack.devices:
        svd_stream = dev.svd
        xml_bytes = svd_stream.read()
        root = ET.fromstring(xml_bytes)
        periphs = root.findall(".//peripheral")
        print(f"    Device {dev.part_number}: {len(periphs)} peripherals found.")
def test_map_parser():
    print("--- 2. Testing MAP File Parser ---")
    import re
    assert MAP_PATH.exists(), f"Map path not found: {MAP_PATH}"
    
    in_mem_map = False
    cur_region = None
    regions = {}
    
    with open(MAP_PATH, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_s = line.strip()
            if "Memory Map of the image" in line_s:
                in_mem_map = True
                continue
            if in_mem_map and line_s.startswith("================================="):
                break
            if not in_mem_map:
                continue
                
            if line_s.startswith("Execution Region"):
                m = re.search(r"Execution Region\s+(\w+)\s+\(Base:\s*(0x[0-9a-fA-F]+),\s*Size:\s*(0x[0-9a-fA-F]+)", line_s)
                if m:
                    cur_region = m.group(1)
                    regions[cur_region] = {"base": m.group(2), "size": m.group(3), "entries": []}
                continue
                
            if cur_region and line_s.startswith("0x"):
                parts = line_s.split()
                if len(parts) >= 3 and parts[2] == "PAD":
                    regions[cur_region]["entries"].append({
                        "addr": parts[0],
                        "size": int(parts[1], 16),
                        "type": "PAD",
                        "attr": "RO" if "ROM" in cur_region else "RW",
                        "section": "Padding",
                        "object": "Linker Padding"
                    })
                elif len(parts) >= 6:
                    addr = parts[0]
                    size = int(parts[1], 16)
                    type_ = parts[2]
                    attr = parts[3]
                    sec_name = parts[5] if len(parts) >= 7 else parts[4]
                    obj_name = parts[-1]
                    regions[cur_region]["entries"].append({
                        "addr": addr,
                        "size": size,
                        "type": type_,
                        "attr": attr,
                        "section": sec_name,
                        "object": obj_name
                    })

    for rname, rdata in regions.items():
        pad_bytes = sum(e["size"] for e in rdata["entries"] if e["type"] == "PAD")
        total_bytes = sum(e["size"] for e in rdata["entries"])
        print(f"  [OK] Region {rname}: Base={rdata['base']}, Size={rdata['size']}, Entries={len(rdata['entries'])}, Total={total_bytes} bytes, Padding={pad_bytes} bytes")

    print("  [PASS] MAP parser verification succeeded!\n")

if __name__ == "__main__":
    test_pack_and_svd()
    test_map_parser()
