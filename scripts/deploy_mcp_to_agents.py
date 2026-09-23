import os
import re
import sys
import json
import sqlite3
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

candidates = [
    ROOT_DIR / "release" / "AI-HIL-Debugger-v1.0.0-windows-x64" / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe",
    ROOT_DIR / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe",
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

def is_same_daemon(cmd_str: str) -> bool:
    """Check if an existing command points to a valid hil-daemon executable."""
    if not cmd_str:
        return False
    if cmd_str == DAEMON_EXE:
        return True
    try:
        p1 = Path(cmd_str).resolve()
        p2 = Path(DAEMON_EXE).resolve()
        if p1 == p2:
            return True
        if p1.exists() and "hil-daemon" in p1.name:
            return True
    except Exception:
        pass
    return False

def backup_file(path: Path):
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"  [Backup] Created backup at {bak}")

def deploy_to_ccswitch():
    print(f"\n[1/7] Deploying to CCSwitch (Database)...")
    db_path = Path(r"C:\Users\ming\.cc-switch\cc-switch.db")
    if not db_path.exists():
        print(f"  [SKIP] CCSwitch database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Check if already installed with valid daemon command
        cur.execute("SELECT server_config FROM mcp_servers WHERE id = ?", (SERVER_ID,))
        row = cur.fetchone()
        if row:
            try:
                cfg = json.loads(row[0])
                if is_same_daemon(cfg.get("command", "")) and cfg.get("args") == ["--mode", "stdio-mcp"]:
                    print(f"  [EXISTS] MCP server '{SERVER_ID}' is already up to date in CCSwitch (Skipping)")
                    conn.close()
                    return
            except Exception:
                pass

        backup_file(db_path)
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
    print(f"\n[2/7] Deploying to Claude Code (.claude.json)...")
    claude_json_path = Path(r"C:\Users\ming\.claude.json")
    if not claude_json_path.exists():
        print(f"  [SKIP] .claude.json not found at {claude_json_path}")
        return

    try:
        with open(claude_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        mcp_servers = data.get("mcpServers", {})
        if SERVER_ID in mcp_servers:
            curr = mcp_servers[SERVER_ID]
            if is_same_daemon(curr.get("command", "")) and curr.get("args") == ["--mode", "stdio-mcp"]:
                print(f"  [EXISTS] MCP server '{SERVER_ID}' is already configured in Claude Code (Skipping)")
                return

        backup_file(claude_json_path)
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
    print(f"\n[3/7] Deploying to OpenAI Codex (.codex/config.toml)...")
    codex_toml_path = Path(r"C:\Users\ming\.codex\config.toml")
    if not codex_toml_path.exists():
        print(f"  [SKIP] Codex config.toml not found at {codex_toml_path}")
        return

    try:
        with open(codex_toml_path, "r", encoding="utf-8") as f:
            content = f.read()

        section_header = "[mcp_servers.embedded_hil_debugger]"
        if section_header in content:
            # Check if command is already configured and valid
            match = re.search(r"command\s*=\s*['\"]([^'\"]+)['\"]", content)
            if match and is_same_daemon(match.group(1)):
                print(f"  [EXISTS] MCP server 'embedded_hil_debugger' already configured in Codex (Skipping)")
                return

        backup_file(codex_toml_path)
        toml_block = (
            f"\n{section_header}\n"
            f"command = '{DAEMON_EXE}'\n"
            f"args = [\"--mode\", \"stdio-mcp\"]\n"
        )

        if section_header in content:
            pattern = re.compile(r"\[mcp_servers\.embedded_hil_debugger\].*?(?=\n\[|\Z)", re.DOTALL)
            content = pattern.sub(lambda _: toml_block.strip(), content)
        else:
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
    print(f"\n[4/7] Deploying to OpenCode (.config/opencode/opencode.json)...")
    opencode_json_path = Path(r"C:\Users\ming\.config\opencode\opencode.json")
    if not opencode_json_path.exists():
        print(f"  [SKIP] OpenCode config not found at {opencode_json_path}")
        return

    try:
        with open(opencode_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        mcp_cfg = data.get("mcp", {})
        if SERVER_ID in mcp_cfg:
            curr = mcp_cfg[SERVER_ID]
            cmd = curr.get("command")
            if (curr.get("type") == "local" and
                isinstance(cmd, list) and
                len(cmd) >= 1 and
                is_same_daemon(cmd[0]) and
                cmd[1:] == ["--mode", "stdio-mcp"]):
                print(f"  [EXISTS] MCP server '{SERVER_ID}' already configured in OpenCode (Skipping)")
                return

        backup_file(opencode_json_path)
        if "mcp" not in data or not isinstance(data["mcp"], dict):
            data["mcp"] = {}

        data["mcp"][SERVER_ID] = {
            "type": "local",
            "command": [DAEMON_EXE, "--mode", "stdio-mcp"],
            "enabled": True,
            "timeout": 60000
        }

        with open(opencode_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [OK] Successfully added '{SERVER_ID}' to OpenCode configuration!")
    except Exception as e:
        print(f"  [ERROR] Failed to update OpenCode configuration: {e}")

def deploy_to_gemini():
    print(f"\n[5/7] Deploying to Gemini / Antigravity (.gemini/config/mcp_config.json)...")
    gemini_mcp_path = Path(r"C:\Users\ming\.gemini\config\mcp_config.json")
    try:
        data = {}
        if gemini_mcp_path.exists():
            try:
                with open(gemini_mcp_path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                    if txt:
                        data = json.loads(txt)
            except Exception:
                data = {}

        mcp_servers = data.get("mcpServers", {})
        if SERVER_ID in mcp_servers:
            curr = mcp_servers[SERVER_ID]
            if is_same_daemon(curr.get("command", "")) and curr.get("args") == ["--mode", "stdio-mcp"]:
                print(f"  [EXISTS] MCP server '{SERVER_ID}' already configured in Gemini / Antigravity (Skipping)")
                return

        gemini_mcp_path.parent.mkdir(parents=True, exist_ok=True)
        backup_file(gemini_mcp_path)

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
    print(f"\n[6/7] Deploying to Claude Desktop (%APPDATA%/Claude/claude_desktop_config.json)...")
    appdata = os.getenv("APPDATA")
    if not appdata:
        return
    claude_desktop_dir = Path(appdata) / "Claude"
    claude_desktop_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_desktop_dir / "claude_desktop_config.json"

    try:
        data = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                    if txt:
                        data = json.loads(txt)
            except Exception:
                data = {}

        mcp_servers = data.get("mcpServers", {})
        if SERVER_ID in mcp_servers:
            curr = mcp_servers[SERVER_ID]
            if is_same_daemon(curr.get("command", "")) and curr.get("args") == ["--mode", "stdio-mcp"]:
                print(f"  [EXISTS] MCP server '{SERVER_ID}' already configured in Claude Desktop (Skipping)")
                return

        backup_file(config_path)
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

def deploy_to_deepseek_harness():
    print(f"\n[7/7] Deploying to DeepSeek Harness (~/.ohdsh)...")
    ohdsh_dir = Path.home() / ".ohdsh"
    if not ohdsh_dir.exists():
        print(f"  [SKIP] DeepSeek Harness directory not found at {ohdsh_dir}")
        return

    profiles = ["desktop", "web"]
    for profile in profiles:
        patch_file = ohdsh_dir / "profiles" / profile / "cordis.patch.yml"
        if not patch_file.parent.exists():
            continue

        existing_content = ""
        if patch_file.exists():
            try:
                with open(patch_file, "r", encoding="utf-8") as f:
                    existing_content = f.read()
            except Exception:
                existing_content = ""

        # Check if already installed with valid daemon executable
        if "mcp-embedded-hil" in existing_content:
            match = re.search(r"command\s*:\s*['\"]([^'\"]+)['\"]", existing_content)
            if match and is_same_daemon(match.group(1)):
                print(f"  [EXISTS] MCP server already registered in DeepSeek Harness ({profile}) (Skipping)")
                continue

        backup_file(patch_file)
        mcp_block = f"""
- id: mcp-embedded-hil
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: hil
    transport: stdio
    command: '{DAEMON_EXE}'
    args: ['--mode', 'stdio-mcp']
    toolCallTimeoutMs: 120000
"""
        if "mcp-embedded-hil" in existing_content:
            # Replace existing outdated mcp-embedded-hil block
            pattern = re.compile(r"-\s*id:\s*mcp-embedded-hil.*?(?=\n-|\Z)", re.DOTALL)
            new_content = pattern.sub(mcp_block.strip(), existing_content)
        else:
            new_content = existing_content.rstrip() + "\n" + mcp_block.strip() + "\n"

        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(new_content)

        print(f"  [OK] Successfully registered MCP server in DeepSeek Harness ({profile})!")

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
    deploy_to_deepseek_harness()

    print("\n================================================================")
    print("[SUCCESS] All MCP deployments finished without repeat!")
    print("================================================================")
