import subprocess
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAEMON_EXE = PROJECT_ROOT / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"
PACK_PATH = r"C:\Users\ming\Documents\xwechat_files\wxid_pp3man8zwkkq22_1b12\msg\file\2024-02\GigaDevice.GD32F4xx_DFP.3.1.0.pack"

print(f"Testing frozen daemon at: {DAEMON_EXE}")
proc = subprocess.Popen(
    [str(DAEMON_EXE), "--mode", "stdio-mcp"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

def rpc(method, params, req_id):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    resp_line = proc.stdout.readline()
    return json.loads(resp_line)

try:
    # 1. Initialize
    init = rpc("initialize", {"protocolVersion": "2024-11-05"}, 1)
    print("1. Initialize:", init.get("result", {}).get("serverInfo"))

    # 2. Import GigaDevice Pack
    import_res = rpc("tools/call", {"name": "svd_import_pack", "arguments": {"pack_path": PACK_PATH}}, 2)
    content = json.loads(import_res["result"]["content"][0]["text"])
    print(f"2. Imported GD32 Pack: {content['pack']}, {len(content['devices'])} devices")
    assert len(content['devices']) > 0

    # 3. Get Peripherals for GD32F403RC
    periph_res = rpc("tools/call", {"name": "svd_get_peripherals", "arguments": {"device_name": "GD32F403RC"}}, 3)
    p_content = json.loads(periph_res["result"]["content"][0]["text"])
    print(f"3. GD32F403RC Peripherals: {len(p_content)}")
    assert len(p_content) == 56

    # 4. Get Registers for USART0
    reg_res = rpc("tools/call", {"name": "svd_get_registers", "arguments": {"device_name": "GD32F403RC", "peripheral_name": "USART0"}}, 4)
    r_content = json.loads(reg_res["result"]["content"][0]["text"])
    print(f"4. USART0 Registers: {len(r_content)}")
    assert len(r_content) == 10

    # 5. Get Registers for derivedFrom ADC2
    adc2_res = rpc("tools/call", {"name": "svd_get_registers", "arguments": {"device_name": "GD32F403RC", "peripheral_name": "ADC2"}}, 5)
    adc2_content = json.loads(adc2_res["result"]["content"][0]["text"])
    print(f"5. ADC2 Registers: {len(adc2_content)}, first addr: {adc2_content[0]['address']}")
    assert adc2_content[0]['address'] == "0x40013C00"

    print("\n[ALL JSON-RPC GD32 SVD TESTS PASSED ON FROZEN DAEMON!]")
finally:
    proc.terminate()
    proc.wait()
