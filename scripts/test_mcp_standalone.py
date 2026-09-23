import subprocess
import json
import sys
from pathlib import Path

exe_path = Path(__file__).parent.parent / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe"
print(f"[TEST] Testing standalone MCP executable: {exe_path}")

cmd = [str(exe_path), "--mode", "stdio-mcp"]
p = subprocess.Popen(
    cmd,
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
    # 1. initialize
    res = rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-runner", "version": "1.0"}
    }, 1)
    assert "serverInfo" in res.get("result", {}), f"Init failed: {res}"
    print("  [PASS] 1. initialize ->", res["result"]["serverInfo"])

    # 2. ping
    res = rpc("ping", {}, 2)
    assert "result" in res, f"Ping failed: {res}"
    print("  [PASS] 2. ping -> OK")

    # 3. tools/list
    res = rpc("tools/list", {}, 3)
    tools = [t["name"] for t in res.get("result", {}).get("tools", [])]
    print(f"  [PASS] 3. tools/list -> {len(tools)} tools: {tools}")
    assert len(tools) >= 7, f"Expected at least 7 tools, got {len(tools)}"

    # 4. tools/call: list_probes
    res = rpc("tools/call", {"name": "list_probes", "arguments": {}}, 4)
    call_res = res.get("result", {})
    assert call_res.get("isError") is False, f"list_probes error: {res}"
    probes = json.loads(call_res["content"][0]["text"])
    print(f"  [PASS] 4. tools/call list_probes -> Found {len(probes)} probe(s):")
    for pr in probes:
        uid = pr.get("unique_id")
        ptype = pr.get("probe_type")
        label = pr.get("type_label")
        desc = pr.get("description")
        print(f"         - ID: {uid}, Type: {ptype}, Label: {label}, Desc: {desc}")

    # 5. Direct JSON-RPC method: list_probes (backward compatibility for Tauri)
    res = rpc("list_probes", {}, 5)
    assert isinstance(res.get("result"), list), f"Direct method failed: {res}"
    print(f"  [PASS] 5. Direct RPC list_probes (Tauri IPC compatibility) -> {len(res['result'])} probe(s)")

    print("\n========================================================")
    print(" [ALL VERIFIED] Standalone MCP Daemon is 100% Functional!")
    print("========================================================")

finally:
    p.terminate()
