import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SANDBOX = REPO_ROOT / "scripts" / "run_sandbox.sh"


class RunSandboxLauncherTests(unittest.TestCase):
    def run_with_fake_docker(
        self,
        workspace: Path,
        env_file: str | None = None,
        agent: str = "codex",
    ) -> str:
        fake_bin = workspace / "bin"
        fake_bin.mkdir()
        docker_log = workspace / "docker.log"
        fake_docker = fake_bin / "docker"
        fake_docker.write_text(
            "#!/bin/bash\n"
            "printf 'DOCKER' >> \"$DOCKER_LOG\"\n"
            "for arg in \"$@\"; do printf '\\t%s' \"$arg\" >> \"$DOCKER_LOG\"; done\n"
            "printf '\\n' >> \"$DOCKER_LOG\"\n",
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)
        fake_touch = fake_bin / "touch"
        fake_touch.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        fake_touch.chmod(0o755)

        workcell_dir = workspace / ".workcell"
        workcell_dir.mkdir(exist_ok=True)
        if env_file is not None:
            (workcell_dir / ".env").write_text(env_file, encoding="utf-8")

        env = os.environ.copy()
        env["DOCKER_LOG"] = str(docker_log)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

        subprocess.run(
            [str(RUN_SANDBOX), agent, "--", "status"],
            cwd=workspace,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return docker_log.read_text(encoding="utf-8")

    def test_pi_agent_is_passed_to_docker_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(workspace, agent="pi")

            run_line = next(line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t"))
            self.assertIn("\t-e\tAGENT_CLI=pi\t", f"{run_line}\t")

    def test_pi_sessions_are_mounted_from_workcell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(workspace, agent="pi")

            run_line = next(line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t"))
            expected_mount = (
                f"{workspace / '.workcell' / 'pi-sessions'}:"
                f"/home/agent/persist/.pi/agent/sessions/--workspaces-{workspace.name}--"
            )
            self.assertIn(f"\t-v\t{expected_mount}\t", f"{run_line}\t")
            self.assertTrue((workspace / ".workcell" / "pi-sessions").is_dir())

    def test_unknown_agent_error_mentions_pi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = subprocess.run(
                [str(RUN_SANDBOX), "unknown"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("'claude', 'opencode', 'codex', or 'pi'", result.stdout)

    def test_flutter_project_dir_requires_flutter_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = subprocess.run(
                [str(RUN_SANDBOX), "codex", "--flutter-project-dir", "./gui"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--flutter-project-dir requires --with-flutter", result.stdout)

    def test_flutter_project_dir_must_exist_under_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = subprocess.run(
                [str(RUN_SANDBOX), "codex", "--with-flutter", "--flutter-project-dir", "./gui"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Flutter project directory not found", result.stdout)

    def test_flutter_project_dir_must_be_relative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = subprocess.run(
                [str(RUN_SANDBOX), "codex", "--with-flutter", "--flutter-project-dir", "/tmp"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be relative to the workspace directory", result.stdout)

    def test_env_file_is_passed_to_docker_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(
                workspace,
                "CUSTOM=value\nQUOTED=\"value with spaces\"\n",
            )

            run_line = next(line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t"))
            self.assertIn("\t-e\tCUSTOM=value\t", f"{run_line}\t")
            self.assertIn("\t-e\tQUOTED=value with spaces\t", f"{run_line}\t")
            self.assertLess(run_line.index("CUSTOM=value"), run_line.index("AGENT_CLI=codex"))

    def test_gitignore_is_seeded_with_env_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.run_with_fake_docker(workspace)

            self.assertEqual(
                (workspace / ".workcell" / ".gitignore").read_text(encoding="utf-8"),
                ".DS_Store\n.env\nflutter-config.json\nartifacts/\n",
            )

    def test_existing_gitignore_gets_env_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            workcell_dir = workspace / ".workcell"
            workcell_dir.mkdir()
            (workcell_dir / ".gitignore").write_text("artifacts/", encoding="utf-8")
            self.run_with_fake_docker(workspace)

            self.assertEqual(
                (workspace / ".workcell" / ".gitignore").read_text(encoding="utf-8"),
                "artifacts/\n.env\n",
            )


if __name__ == "__main__":
    unittest.main()
