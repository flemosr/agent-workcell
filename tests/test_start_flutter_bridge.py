import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_FLUTTER_BRIDGE = REPO_ROOT / "scripts" / "start-flutter-bridge.sh"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class StartFlutterBridgeTests(unittest.TestCase):
    def run_bridge_until_config_write(self, workspace: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        fake_bin = workspace / "bin"
        fake_bin.mkdir()
        fake_flutter = fake_bin / "flutter"
        fake_flutter.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        fake_flutter.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
        env["FLUTTER_BRIDGE_LOG_FILE"] = str(workspace / "flutter-bridge.log")

        return subprocess.run(
            ["timeout", "2", str(START_FLUTTER_BRIDGE), *args],
            cwd=workspace,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_flutter_project_dir_writes_workspace_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "gui").mkdir()

            self.run_bridge_until_config_write(
                workspace,
                [
                    "--port",
                    str(free_port()),
                    "--token",
                    "test-token",
                    "--flutter-project-dir",
                    "./gui",
                ],
            )

            config = json.loads((workspace / ".workcell" / "flutter-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["token"], "test-token")
            self.assertEqual(config["flutter_project_dir"], "./gui")

    def test_flutter_project_dir_rejects_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = self.run_bridge_until_config_write(
                workspace,
                [
                    "--port",
                    str(free_port()),
                    "--token",
                    "test-token",
                    "--flutter-project-dir",
                    "/tmp",
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be relative to the workspace directory", result.stdout)


if __name__ == "__main__":
    unittest.main()
