"""Unit tests for update_manifest.py and publish_release.py release plan logic."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_manifest import build_latest_manifest, build_release_manifest
from publish_release import build_release_commands, release_assets, release_notes_match_version


class ReleasePlanTests(unittest.TestCase):
    def test_latest_manifest_format_and_validation(self):
        manifest = build_latest_manifest(
            version="1.3.5",
            signature="dGVzdC1zaWc=\n",
            tag="v1.3.5",
            notes="# v1.3.5\n- test",
            pub_date="2026-11-24T00:00:00Z",
        )
        self.assertEqual(manifest["version"], "1.3.5")
        self.assertEqual(
            manifest["platforms"]["windows-x86_64"]["url"],
            "https://github.com/ZenghuiJIA/ingchips_debug_tools/releases/download/v1.3.5/AI-HIL-Debugger-setup.exe",
        )
        self.assertEqual(manifest["platforms"]["windows-x86_64"]["signature"], "dGVzdC1zaWc=")

        with self.assertRaises(ValueError):
            build_latest_manifest(version="1.3.5", signature="", tag="v1.3.5")
        with self.assertRaises(ValueError):
            build_latest_manifest(version="1.3.5", signature="abc", tag="v1.3.4")

    def test_release_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "a.bin").write_bytes(b"hello")
            m = build_release_manifest(version="1.3.5", release_dir=tmp_dir, filenames=["a.bin"])
            self.assertEqual(m["version"], "1.3.5")
            self.assertEqual(m["files"][0]["bytes"], 5)
            self.assertEqual(len(m["files"][0]["sha256"]), 64)

    def test_build_release_commands_atomic_and_immutable(self):
        assets = release_assets("v1.3.5")
        cmds_new = build_release_commands(
            tag="v1.3.5",
            version="1.3.5",
            notes_file="docs/RELEASE_NOTES_v1.3.5.md",
            existing_status=1,
            existing_stdout="",
            existing_stderr="release not found",
            assets=assets,
        )
        self.assertEqual(cmds_new[0][1], "create")
        self.assertIn("--draft", cmds_new[0])
        self.assertEqual(cmds_new[1][1], "upload")
        self.assertEqual(cmds_new[2], ["release", "edit", "v1.3.5", "--draft=false", "--latest"])

        cmds_draft = build_release_commands(
            tag="v1.3.5",
            version="1.3.5",
            notes_file="docs/RELEASE_NOTES_v1.3.5.md",
            existing_status=0,
            existing_stdout=json.dumps({"isDraft": True}),
            existing_stderr="",
            assets=assets,
        )
        self.assertEqual(cmds_draft[0][1], "edit")

        with self.assertRaisesRegex(RuntimeError, "禁止覆盖"):
            build_release_commands(
                tag="v1.3.5",
                version="1.3.5",
                notes_file="docs/RELEASE_NOTES_v1.3.5.md",
                existing_status=0,
                existing_stdout=json.dumps({"isDraft": False}),
                existing_stderr="",
                assets=assets,
            )

    def test_release_notes_match(self):
        self.assertTrue(release_notes_match_version("# v1.3.5 更新\n", "1.3.5"))
        self.assertFalse(release_notes_match_version("# v1.3.4 更新\n", "1.3.5"))


if __name__ == "__main__":
    unittest.main()
