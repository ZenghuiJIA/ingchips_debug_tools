import subprocess
import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DAEMON_EXE = ROOT_DIR / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"
FULL_PACK = Path(r"C:\ming\python\get_svd\INGChips.INGCHIPS_DeviceFamilyPack.1.0.1_full.pack")

print(f"Testing frozen daemon at: {DAEMON_EXE}")
assert DAEMON_EXE.exists(), f"Frozen daemon not found: {DAEMON_EXE}"

p = subprocess.Popen(
    [str(DAEMON_EXE), "--mode", "stdio-mcp"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8"
)

def rpc(method, params=None, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    p.stdin.write(json.dumps(payload) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    return json.loads(line)

try:
    # 1. Handshake
    init_res = rpc("initialize", {"protocolVersion": "2024-11-05"}, 1)
    print("1. Handshake OK:", init_res["result"]["serverInfo"])

    # 2. Tool list
    tools_res = rpc("tools/list", {}, 2)
    tools = [t["name"] for t in tools_res["result"]["tools"]]
    print(f"2. Tools Count: {len(tools)} (Has svd_import_pack: {'svd_import_pack' in tools})")
    assert "svd_import_pack" in tools
    assert "analyze_firmware_resources" in tools

    # 3. Test MAP files: 9188, 9168, 208
    map_files = [
        r"C:\ming\source\axf_tool\bin\exp_ING9188xx.map",
        r"C:\ming\source\axf_tool\bin\exp_ING9168xx.map",
        r"C:\ming\source\axf_tool\bin\exp_ING208xx.map",
    ]
    for mf in map_files:
        if not os.path.exists(mf):
            print(f"   [SKIP] File not found: {mf}")
            continue
        res = rpc("tools/call", {
            "name": "analyze_firmware_resources",
            "arguments": {
                "file_path": mf,
                "chip_flash_size": 2097152,
                "chip_ram_size": 65536
            }
        }, 10)
        assert res["result"]["isError"] is False, f"MAP analysis error for {mf}: {res}"
        data = json.loads(res["result"]["content"][0]["text"])
        mod_count = len(data.get("modules", []))
        sec_count = len(data.get("sections", []))
        print(f"   [PASS] {os.path.basename(mf)}: {mod_count} modules, {sec_count} sections, ROM={data['summary']['rom_total_str']}, RAM={data['summary']['ram_total_str']}")
        assert mod_count > 0, f"Expected modules > 0 for {mf}, got {mod_count}"
        assert sec_count > 0, f"Expected sections > 0 for {mf}, got {sec_count}"

    # 4. Test SVD initial devices
    dev_res = rpc("tools/call", {"name": "svd_get_devices", "arguments": {}}, 20)
    assert dev_res["result"]["isError"] is False
    dev_data = json.loads(dev_res["result"]["content"][0]["text"])
    dev_names = [d["name"] for d in dev_data]
    print(f"4. Initial SVD Devices: {dev_names}")

    # 5. Test Dynamic Pack Import
    if FULL_PACK.exists():
        print(f"5. Testing dynamic pack import from: {FULL_PACK.name}")
        import_res = rpc("tools/call", {
            "name": "svd_import_pack",
            "arguments": {"pack_path": str(FULL_PACK)}
        }, 30)
        assert import_res["result"]["isError"] is False, f"Import error: {import_res}"
        import_data = json.loads(import_res["result"]["content"][0]["text"])
        imported_devs = [d["name"] for d in import_data["devices"]]
        print(f"   [PASS] Imported {import_data['pack']}: {imported_devs}")

        # Test svd_get_devices again after import
        dev_res2 = rpc("tools/call", {"name": "svd_get_devices", "arguments": {}}, 31)
        dev_data2 = json.loads(dev_res2["result"]["content"][0]["text"])
        all_dev_names = [d["name"] for d in dev_data2]
        print(f"   [PASS] All devices after import ({len(all_dev_names)}): {all_dev_names}")
        assert any("926" in d for d in all_dev_names), "Expected ING92600 in devices list after importing full pack!"

        # Test peripheral query on ING92600
        periph_res = rpc("tools/call", {
            "name": "svd_get_peripherals",
            "arguments": {"device_name": "ING92600"}
        }, 32)
        assert periph_res["result"]["isError"] is False
        periphs = json.loads(periph_res["result"]["content"][0]["text"])
        periph_names = [p["name"] for p in periphs]
        print(f"   [PASS] ING92600 Peripherals ({len(periph_names)}): {periph_names[:8]}...")
        assert len(periphs) > 0

        # Test register query on first peripheral
        reg_res = rpc("tools/call", {
            "name": "svd_get_registers",
            "arguments": {"device_name": "ING92600", "peripheral_name": periph_names[0]}
        }, 33)
        assert reg_res["result"]["isError"] is False
        regs = json.loads(reg_res["result"]["content"][0]["text"])
        print(f"   [PASS] ING92600 {periph_names[0]} has {len(regs)} registers: {[r['name'] for r in regs[:5]]}")
        assert len(regs) > 0

    print("\n[ALL TESTS PASSED SUCCESSFULLY!]")
finally:
    p.terminate()
