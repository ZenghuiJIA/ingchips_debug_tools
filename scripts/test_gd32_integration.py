import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAEMON_DIR = PROJECT_ROOT / "src-tauri" / "daemon"
sys.path.insert(0, str(DAEMON_DIR))

from svd_manager import SvdManager

gd32_pack_path = r'C:\Users\ming\Documents\xwechat_files\wxid_pp3man8zwkkq22_1b12\msg\file\2024-02\GigaDevice.GD32F4xx_DFP.3.1.0.pack'

print("=== 1. Testing GigaDevice GD32 Pack Import ===")
res = SvdManager.import_pack(gd32_pack_path)
print(f"Pack: {res['pack']}, Devices count: {len(res['devices'])}")
assert len(res['devices']) > 0, "No devices imported"

print("\n=== 2. Testing Peripheral Loading for GD32F403RC ===")
periphs_403 = SvdManager.get_peripherals("GD32F403RC")
print(f"GD32F403RC Peripherals: {len(periphs_403)}")
assert len(periphs_403) == 56, f"Expected 56 peripherals, got {len(periphs_403)}"

names_403 = [p["name"] for p in periphs_403]
print(f"Sample peripherals: {names_403[:8]}")
assert "USART0" in names_403
assert "ADC0" in names_403
assert "ADC2" in names_403

print("\n=== 3. Testing Peripheral Loading for GD32F450VG ===")
periphs_450 = SvdManager.get_peripherals("GD32F450VG")
print(f"GD32F450VG Peripherals: {len(periphs_450)}")
assert len(periphs_450) == 83, f"Expected 83 peripherals, got {len(periphs_450)}"

print("\n=== 4. Testing Register Loading for USART0 ===")
usart_regs = SvdManager.get_registers("GD32F403RC", "USART0")
print(f"USART0 Registers: {len(usart_regs)}")
assert len(usart_regs) > 0, "USART0 registers should not be empty"
for r in usart_regs[:3]:
    print(f"  - {r['name']} ({r['address']}) -> {len(r['fields'])} fields")

print("\n=== 5. Testing derivedFrom Register Loading for ADC2 (derived from ADC1) ===")
adc2_regs = SvdManager.get_registers("GD32F403RC", "ADC2")
print(f"ADC2 Registers: {len(adc2_regs)}")
assert len(adc2_regs) > 0, "ADC2 registers should not be empty"
for r in adc2_regs[:3]:
    print(f"  - {r['name']} ({r['address']}) -> {len(r['fields'])} fields")
    # Verify address begins with ADC2 baseAddress 0x40013C00
    assert r['address'].startswith("0x40013C"), f"ADC2 register address {r['address']} should start with 0x40013C!"

print("\n=== 6. Testing INGChips Pack Compatibility ===")
ing_periphs = SvdManager.get_peripherals("ING91800")
print(f"ING91800 Peripherals: {len(ing_periphs)}")
assert len(ing_periphs) > 0

print("\n[ALL SVD MANAGER TESTS PASSED SUCCESSFULLY!]")
