import os
import sys
import json
import sqlite3
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

candidates = [
    ROOT_DIR / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe",
    ROOT_DIR / "hil-daemon-x86_64-pc-windows-msvc.exe",
    Path(r"C:\ming\source\tools\test_tools\bin\hil-daemon-x86_64-pc-windows-msvc.exe"),
]

found_exe = next((p for p in candidates if p.exists()), candidates[0])
DAEMON_EXE = str(found_exe)
DAEMON_FALLBACK_PY = str(ROOT_DIR / "src-tauri" / "daemon" / "daemon_entry.py")

SERVER_ID = "embedded-hil-debugger"
SERVER_NAME = "embedded-hil-debugger"
SERVER_DESC = "AI 嵌入式硬件在环(HIL)测试与调试系统 (DAPLink串口/SWD烧录/寄存器分析/HardFault自动诊断)"

if not os.path.exists(DAEMON_EXE):
    print(f"[WARN] Daemon binary not found at: {DAEMON_EXE}")
    print(f"[WARN] Will fallback to Python entry point if needed.")
else:
    print(f"[INFO] Using daemon executable: {DAEMON_EXE}")

def backup_file(path: Path):
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"  [Backup] Created backup at {bak}")

def deploy_to_ccswitch():
    print(f"\n[1/6] Deploying to CCSwitch (Database)...")
    db_path = Path(r"C:\Users\ming\.cc-switch\cc-switch.db")
    if not db_path.exists():
        print(f"  [SKIP] CCSwitch database not found at {db_path}")
        return

    backup_file(db_path)
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        server_config = json.dumps({
            "type": "stdio",
            "command": DAEMON_EXE,
            "args": ["--mode", "stdio-mcp"]
        }, ensure_ascii=False)

        tags = json.dumps(["embedded", "hil", "swd", "pyocd", "serial"], ensure_ascii=False)

        cur.execute("""
            INSERT INTO mcp_servers (
                id, name, server_config, description, homepage, docs, tags,
                enabled_claude, enabled_codex, enabled_gemini, enabled_opencode, enabled_hermes, enabled_grokbuild
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 1, 1, 1, 1)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                server_config=excluded.server_config,
                description=excluded.description,
                tags=excluded.tags,
                enabled_claude=1,
                enabled_codex=1,
                enabled_gemini=1,
                enabled_opencode=1,
                enabled_hermes=1,
                enabled_grokbuild=1
        """, (SERVER_ID, SERVER_NAME, server_config, SERVER_DESC, None, None, tags))

        conn.commit()
        conn.close()
        print(f"  [OK] Successfully registered '{SERVER_ID}' in CCSwitch database!")
    except Exception as e:
        print(f"  [ERROR] Failed to update CCSwitch database: {e}")

def deploy_to_claude_code():
    print(f"\n[2/6] Deploying to Claude Code (.claude.json)...")
    claude_json_path = Path(r"C:\Users\ming\.claude.json")
    if not claude_json_path.exists():
        print(f"  [SKIP] .claude.json not found at {claude_json_path}")
        return

    try:
        backup_file(claude_json_path)
        with open(claude_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
            data["mcpServers"] = {}

        data["mcpServers"][SERVER_ID] = {
            "command": DAEMON_EXE,
            "args": ["--mode", "stdio-mcp"]
        }

        with open(claude_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [OK] Successfully added '{SERVER_ID}' to Claude Code configuration!")
    except Exception as e:
        print(f"  [ERROR] Failed to update Claude Code configuration: {e}")

def deploy_to_codex():
    print(f"\n[3/6] Deploying to OpenAI Codex (.codex/config.toml)...")
    codex_toml_path = Path(r"C:\Users\ming\.codex\config.toml")
    if not codex_toml_path.exists():
        print(f"  [SKIP] Codex config.toml not found at {codex_toml_path}")
        return

    try:
        backup_file(codex_toml_path)
        with open(codex_toml_path, "r", encoding="utf-8") as f:
            content = f.read()

        section_header = "[mcp_servers.embedded_hil_debugger]"
        escaped_exe = DAEMON_EXE.replace("\\", "\\\\")
        toml_block = (
            f"\n{section_header}\n"
            f"command = '{DAEMON_EXE}'\n"
            f"args = [\"--mode\", \"stdio-mcp\"]\n"
        )

        if section_header in content:
            # Already present, replace or update
            print(f"  [INFO] Codex config already contains {section_header}, ensuring up to date...")
            import re
            pattern = re.compile(r"\[mcp_servers\.embedded_hil_debugger\].*?(?=\n\[|\Z)", re.DOTALL)
            content = pattern.sub(lambda _: toml_block.strip(), content)
        else:
            # Append to [mcp_servers] or end of file
            if "[mcp_servers]" in content:
                content = content.replace("[mcp_servers]", "[mcp_servers]" + toml_block, 1)
            else:
                content += f"\n[mcp_servers]{toml_block}"

        with open(codex_toml_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"  [OK] Successfully added 'embedded_hil_debugger' to Codex config.toml!")
    except Exception as e:
        print(f"  [ERROR] Failed to update Codex configuration: {e}")

def deploy_to_opencode():
    print(f"\n[4/6] Deploying to OpenCode (.config/opencode/opencode.json)...")
    opencode_json_path = Path(r"C:\Users\ming\.config\opencode\opencode.json")
    if not opencode_json_path.exists():
        print(f"  [SKIP] OpenCode config not found at {opencode_json_path}")
        return

    try:
        backup_file(opencode_json_path)
        with open(opencode_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "mcp" not in data or not isinstance(data["mcp"], dict):
            data["mcp"] = {}

        data["mcp"][SERVER_ID] = {
            "type": "stdio",
            "command": DAEMON_EXE,
            "args": ["--mode", "stdio-mcp"]
        }

        with open(opencode_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [OK] Successfully added '{SERVER_ID}' to OpenCode configuration!")
    except Exception as e:
        print(f"  [ERROR] Failed to update OpenCode configuration: {e}")

def deploy_to_gemini():
    print(f"\n[5/6] Deploying to Gemini / Antigravity (.gemini/config/mcp_config.json)...")
    gemini_mcp_path = Path(r"C:\Users\ming\.gemini\config\mcp_config.json")
    try:
        gemini_mcp_path.parent.mkdir(parents=True, exist_ok=True)
        backup_file(gemini_mcp_path)

        data = {}
        if gemini_mcp_path.exists():
            try:
                with open(gemini_mcp_path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                    if txt:
                        data = json.loads(txt)
            except Exception:
                data = {}

        if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
            data["mcpServers"] = {}

        data["mcpServers"][SERVER_ID] = {
            "command": DAEMON_EXE,
            "args": ["--mode", "stdio-mcp"]
        }

        with open(gemini_mcp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [OK] Successfully added '{SERVER_ID}' to Gemini configuration!")
    except Exception as e:
        print(f"  [ERROR] Failed to update Gemini configuration: {e}")

def deploy_to_claude_desktop():
    print(f"\n[6/6] Deploying to Claude Desktop (%APPDATA%/Claude/claude_desktop_config.json)...")
    appdata = os.getenv("APPDATA")
    if not appdata:
        return
    claude_desktop_dir = Path(appdata) / "Claude"
    claude_desktop_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_desktop_dir / "claude_desktop_config.json"

    try:
        backup_file(config_path)
        data = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                    if txt:
                        data = json.loads(txt)
            except Exception:
                data = {}

        if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
            data["mcpServers"] = {}

        data["mcpServers"][SERVER_ID] = {
            "command": DAEMON_EXE,
            "args": ["--mode", "stdio-mcp"]
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [OK] Successfully added '{SERVER_ID}' to Claude Desktop configuration!")
    except Exception as e:
        print(f"  [ERROR] Failed to update Claude Desktop configuration: {e}")

if __name__ == "__main__":
    print("================================================================")
    print(" Deploying Embedded HIL MCP Server to CCSwitch & Agent Configs  ")
    print("================================================================")
    print(f"Server ID: {SERVER_ID}")
    print(f"Command:   {DAEMON_EXE}")
    print(f"Arguments: --mode stdio-mcp")

    deploy_to_ccswitch()
    deploy_to_claude_code()
    deploy_to_codex()
    deploy_to_opencode()
    deploy_to_gemini()
    deploy_to_claude_desktop()

    print("\n================================================================")
    print("[SUCCESS] All MCP deployments finished!")
    print("================================================================")
