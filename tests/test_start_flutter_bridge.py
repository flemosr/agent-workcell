import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from shell_test_support import temporary_script_repo


class StartFlutterBridgeTests(unittest.TestCase):
    def setUp(self):
        self.repo = temporary_script_repo(self)
        (self.repo / "scripts" / "flutter-bridge.py").write_text(
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            'Path(os.environ["BRIDGE_ARGS_LOG"]).write_text(json.dumps(sys.argv[1:]))\n',
            encoding="utf-8",
        )

    def run_bridge(self, workspace: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        fake_bin = workspace / "bin"
        fake_bin.mkdir()
        fake_flutter = fake_bin / "flutter"
        fake_flutter.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        fake_flutter.chmod(0o755)
        # The recording bridge never opens a socket; don't depend on host port availability.
        fake_lsof = fake_bin / "lsof"
        fake_lsof.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
        fake_lsof.chmod(0o755)
        (self.repo / "config.sh").write_text(
            f"FLUTTER_PATH={shlex.quote(str(fake_flutter))}\n"
            "FLUTTER_BRIDGE_PORT=8765\n"
            "FLUTTER_BRIDGE_TOKEN=\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
        env["FLUTTER_BRIDGE_LOG_FILE"] = str(workspace / "flutter-bridge.log")
        env["BRIDGE_ARGS_LOG"] = str(workspace / "bridge-args.json")

        return subprocess.run(
            [str(self.repo / "scripts" / "start-flutter-bridge.sh"), *args],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=15, check=False,
        )

    def test_flutter_project_dir_writes_workspace_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "gui").mkdir()
            result = self.run_bridge(
                workspace,
                ["--port", "8766", "--token", "test-token", "--flutter-project-dir", "./gui"],
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            config = json.loads((workspace / ".workcell" / "flutter-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["token"], "test-token")
            self.assertEqual(config["port"], 8766)
            self.assertEqual(config["flutter_project_dir"], "./gui")
            bridge_args = json.loads((workspace / "bridge-args.json").read_text(encoding="utf-8"))
            self.assertEqual(
                bridge_args,
                [
                    "--port", "8766", "--host", "0.0.0.0",
                    "--project-dir", str((workspace / "gui").resolve()),
                    "--target", "lib/main.dart", "--flutter-path", str(workspace / "bin" / "flutter"),
                    "--token", "test-token", "--log-file", str(workspace / "flutter-bridge.log"),
                ],
            )

    def test_flutter_project_dir_rejects_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = self.run_bridge(
                workspace,
                ["--port", "8766", "--token", "test-token", "--flutter-project-dir", "/tmp"],
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("must be relative to the workspace directory", result.stdout + result.stderr)
            self.assertFalse((workspace / "bridge-args.json").exists())


if __name__ == "__main__":
    unittest.main()
