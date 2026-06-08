import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SANDBOX = REPO_ROOT / "scripts" / "run_sandbox.sh"


class RunSandboxLauncherTests(unittest.TestCase):
    def setUp(self):
        self.config = REPO_ROOT / "config.sh"
        self.original_config = self.config.read_text(encoding="utf-8") if self.config.exists() else None
        self.config.unlink(missing_ok=True)
        self.addCleanup(self.restore_repo_config)

    def restore_repo_config(self):
        if self.original_config is None:
            self.config.unlink(missing_ok=True)
        else:
            self.config.write_text(self.original_config, encoding="utf-8")

    def with_repo_config(self, content: str):
        self.config.write_text(content, encoding="utf-8")

    def run_with_fake_docker(
        self,
        workspace: Path,
        env_file: str | None = None,
        agent: str = "codex",
        extra_env: dict[str, str] | None = None,
    ) -> str:
        fake_bin = workspace / "bin"
        fake_bin.mkdir(exist_ok=True)
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
        env["WORKCELL_TEST_SKIP_WATCHDOG"] = "1"
        env.pop("WORKCELL_CONTEXT_REPO", None)
        if extra_env:
            env.update(extra_env)

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
                f"{workspace / '.workcell' / 'sessions' / 'pi'}:"
                f"/home/agent/persist/.pi/agent/sessions/--workspaces-{workspace.name}--"
            )
            self.assertIn(f"\t-v\t{expected_mount}\t", f"{run_line}\t")
            self.assertTrue((workspace / ".workcell" / "sessions" / "pi").is_dir())

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
            self.assertIn("'pi', 'opencode', 'codex', or 'claude'", result.stdout)

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
        self.with_repo_config("\n")
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
        self.with_repo_config("\n")
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

    def test_context_repo_env_is_ignored_when_not_in_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(workspace, extra_env={"WORKCELL_CONTEXT_REPO": str(workspace)})
            run_line = next(line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t"))
            self.assertNotIn("/opt/workcell-context", run_line)

    def test_context_repo_config_adds_writable_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "agent-context"
            repo.mkdir()
            self.with_repo_config(f'WORKCELL_CONTEXT_REPO="{repo}"\n')
            docker_log = self.run_with_fake_docker(workspace)
            run_line = next(line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t"))
            self.assertIn(f"\t-v\t{repo}:/opt/workcell-context:rw\t", f"{run_line}\t")
            self.assertNotIn("/opt/workcell-context:ro", run_line)

    def test_context_repo_config_rejects_relative_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.with_repo_config('WORKCELL_CONTEXT_REPO="relative/context"\n')
            result = subprocess.run(
                [str(RUN_SANDBOX), "codex", "--", "status"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WORKCELL_CONTEXT_REPO must be an absolute", result.stdout)

    def test_context_repo_env_file_entry_is_not_passed_to_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(
                workspace,
                f"WORKCELL_CONTEXT_REPO={workspace}\nCUSTOM=value\n",
            )
            run_line = next(line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t"))
            self.assertNotIn("WORKCELL_CONTEXT_REPO", run_line)
            self.assertNotIn("/opt/workcell-context", run_line)
            self.assertIn("\t-e\tCUSTOM=value\t", f"{run_line}\t")

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

    def test_workcell_planning_files_are_seeded_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.run_with_fake_docker(workspace)

            ideas_file = workspace / ".workcell" / "ideas.md"
            roadmap_file = workspace / ".workcell" / "roadmap.md"
            self.assertIn("# Ideas", ideas_file.read_text(encoding="utf-8"))
            self.assertIn("# Roadmap", roadmap_file.read_text(encoding="utf-8"))

            ideas_file.write_text("# Ideas\n\n- Keep me.\n", encoding="utf-8")
            roadmap_file.write_text("# Roadmap\n\n- Keep me too.\n", encoding="utf-8")
            self.run_with_fake_docker(workspace)

            self.assertEqual(ideas_file.read_text(encoding="utf-8"), "# Ideas\n\n- Keep me.\n")
            self.assertEqual(
                roadmap_file.read_text(encoding="utf-8"), "# Roadmap\n\n- Keep me too.\n"
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
