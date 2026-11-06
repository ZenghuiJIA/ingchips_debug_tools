#!/usr/bin/env python3
"""
Integration test for MCP capabilities, tools dispatch, and Desktop Bridge resource sharing.
Verifies:
1. MCP stdio lifecycle (initialize, initialized notification, tools/list).
2. All SWD and serial tools are discoverable and callable.
3. Desktop Bridge IPC inter-process sharing between Vue/Tauri and MCP agent.
4. Clean fallback and error handling without dropping the MCP session.
"""

import os
import sys
import json
import socket
import tempfile
import threading
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DAEMON_PY = REPO_ROOT / "src-tauri" / "daemon" / "daemon_entry.py"


class MockDesktopBridgeServer:
    """Mock DesktopBridgeServer mimicking Tauri's desktop_bridge.rs on 127.0.0.1."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.received_requests = []
        self.bridge_info_path = Path(tempfile.gettempdir()) / "ai-hil-serial-bridge.json"
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._write_info()

    def _write_info(self):
        data = {
            "version": "1.3.3",
            "port": self.port,
            "pid": os.getpid(),
            "started_at": 1700000000,
        }
        with open(self.bridge_info_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _run(self):
        self.sock.settimeout(0.5)
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(2.0)
        buffer = b""
        try:
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    req = json.loads(line_str)
                    self.received_requests.append(req)
                    resp = self._dispatch(req)
                    conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
        except Exception:
            pass
        finally:
            conn.close()

    def _dispatch(self, req: dict) -> dict:
        req_id = req.get("id", 1)
        action = req.get("action", "")
        params = req.get("params", {})

        if action == "ping":
            return {"id": req_id, "success": True, "result": {"status": "ok", "version": "1.3.3"}}
        elif action == "list_ports":
            return {
                "id": req_id,
                "success": True,
                "result": {
                    "ports": [
                        {"port_name": "COM3", "is_daplink": True, "usb_info": {"description": "CMSIS-DAP V2"}}
                    ]
                },
            }
        elif action == "open_port":
            return {"id": req_id, "success": True, "result": {"port_name": params.get("port_name"), "status": "opened"}}
        elif action == "send_serial_data":
            return {"id": req_id, "success": True, "result": {"bytes_sent": 8, "port_name": params.get("port_name")}}
        elif action == "read_serial_data":
            return {
                "id": req_id,
                "success": True,
                "result": {
                    "port_name": params.get("port_name"),
                    "text": "AT+OK\r\n",
                    "hex": "41 54 2B 4F 4B 0D 0A",
                    "bytes_count": 7,
                },
            }
        elif action == "close_port":
            return {"id": req_id, "success": True, "result": {"status": "closed"}}
        else:
            return {"id": req_id, "success": False, "error": f"Unknown action: {action}"}

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        if self.bridge_info_path.exists():
            try:
                self.bridge_info_path.unlink()
            except Exception:
                pass


class McpIntegratedCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(DAEMON_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.req_id = 0

    def tearDown(self):
        if self.proc:
            if self.proc.stdin and not self.proc.stdin.closed:
                try:
                    self.proc.stdin.close()
                except Exception:
                    pass
            if self.proc.stdout and not self.proc.stdout.closed:
                try:
                    self.proc.stdout.close()
                except Exception:
                    pass
            if self.proc.stderr and not self.proc.stderr.closed:
                try:
                    self.proc.stderr.close()
                except Exception:
                    pass
            if self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=3.0)
                except Exception:
                    self.proc.kill()

    def _rpc(self, method: str, params: dict = None, is_notification: bool = False):
        if not is_notification:
            self.req_id += 1
            payload = {"jsonrpc": "2.0", "id": self.req_id, "method": method}
        else:
            payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params

        line = json.dumps(payload) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

        if is_notification:
            return None

        # Read response line
        resp_line = self.proc.stdout.readline()
        self.assertTrue(resp_line, "MCP daemon closed stdout unexpectedly")
        return json.loads(resp_line)

    def test_mcp_lifecycle_and_tools_list(self):
        # 1. Initialize
        init_resp = self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.3.3"},
            },
        )
        self.assertIn("result", init_resp)
        self.assertEqual(init_resp["result"].get("protocolVersion"), "2024-11-05")
        self.assertIn("serverInfo", init_resp["result"])

        # 2. Initialized notification
        self._rpc("notifications/initialized", is_notification=True)

        # 3. tools/list
        tools_resp = self._rpc("tools/list")
        self.assertIn("result", tools_resp)
        tools = tools_resp["result"].get("tools", [])
        tool_names = {t["name"] for t in tools}

        expected_tools = {
            "list_probes",
            "read_memory",
            "write_memory",
            "read_core_registers",
            "reset_target",
            "diagnose_hardfault",
            "list_serial_ports",
            "open_serial_port",
            "close_serial_port",
            "send_serial_data",
            "read_serial_data",
        }
        for expected in expected_tools:
            self.assertIn(expected, tool_names, f"Expected MCP tool '{expected}' not found in tools/list")

    def test_mcp_probe_and_serial_queries(self):
        # Initialize
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.3.3"}})
        self._rpc("notifications/initialized", is_notification=True)

        # tools/call list_probes
        resp = self._rpc("tools/call", {"name": "list_probes", "arguments": {}})
        self.assertIn("result", resp)
        self.assertFalse(resp["result"].get("isError", False))

        # tools/call list_serial_ports
        resp = self._rpc("tools/call", {"name": "list_serial_ports", "arguments": {}})
        self.assertIn("result", resp)
        self.assertFalse(resp["result"].get("isError", False))

    def test_mcp_desktop_bridge_resource_sharing(self):
        """Verify that when Desktop Bridge is active, MCP serial calls transparently route through it without conflict."""
        bridge = MockDesktopBridgeServer()
        try:
            # Initialize MCP
            self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.3.3"}})
            self._rpc("notifications/initialized", is_notification=True)

            # Call open_serial_port
            resp = self._rpc("tools/call", {"name": "open_serial_port", "arguments": {"port_name": "COM3", "baud_rate": 115200}})
            self.assertIn("result", resp)
            content_text = resp["result"]["content"][0]["text"]
            self.assertIn("opened", content_text.lower())

            # Call send_serial_data
            resp = self._rpc("tools/call", {"name": "send_serial_data", "arguments": {"port_name": "COM3", "data": "41 54 0D 0A", "is_hex": True}})
            self.assertIn("result", resp)
            self.assertFalse(resp["result"].get("isError", False))

            # Call read_serial_data
            resp = self._rpc("tools/call", {"name": "read_serial_data", "arguments": {"port_name": "COM3", "max_bytes": 100}})
            self.assertIn("result", resp)
            content_text = resp["result"]["content"][0]["text"]
            self.assertIn("AT+OK", content_text)

            # Check that bridge received the requests
            actions = [r.get("action") for r in bridge.received_requests]
            self.assertIn("open_port", actions)
            self.assertIn("send_serial_data", actions)
            self.assertIn("read_serial_data", actions)
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
