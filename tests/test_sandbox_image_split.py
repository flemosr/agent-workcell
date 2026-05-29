import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SANDBOX = REPO_ROOT / "scripts" / "run_sandbox.sh"
CLI = REPO_ROOT / "cli.sh"


class SandboxImageSplitTests(unittest.TestCase):
    def fake_docker_env(self, workspace: Path, image_inspect_missing: bool = False):
        fake_bin = workspace / "bin"
        fake_bin.mkdir()
        docker_log = workspace / "docker.log"
        fake_docker = fake_bin / "docker"
        fake_docker.write_text(
            "#!/bin/bash\n"
            "printf 'DOCKER' >> \"$DOCKER_LOG\"\n"
            "for arg in \"$@\"; do printf '\\t%s' \"$arg\" >> \"$DOCKER_LOG\"; done\n"
            "printf '\\n' >> \"$DOCKER_LOG\"\n"
            "if [ \"${1:-}\" = image ] && [ \"${2:-}\" = inspect ] && [ \"${IMAGE_INSPECT_MISSING:-0}\" = 1 ]; then exit 1; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)
        for name in ["touch", "sleep"]:
            tool = fake_bin / name
            tool.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            tool.chmod(0o755)
        env = os.environ.copy()
        env["DOCKER_LOG"] = str(docker_log)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
        env["WORKCELL_TEST_SKIP_WATCHDOG"] = "1"
        if image_inspect_missing:
            env["IMAGE_INSPECT_MISSING"] = "1"
        return env, docker_log

    def test_run_uses_agent_image_volume_and_shared_gpg(self):
        for agent in ["claude", "opencode", "codex", "pi"]:
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                env, docker_log = self.fake_docker_env(workspace)
                subprocess.run([str(RUN_SANDBOX), agent, "--", "--version"], cwd=workspace, env=env, check=True)
                run_line = next(line for line in docker_log.read_text().splitlines() if line.startswith("DOCKER\trun\t-d\t"))
                self.assertIn(f"\t-v\tagent-workcell-{agent}:/home/agent/persist\t", f"{run_line}\t")
                self.assertIn("\t-v\tagent-workcell-gpg:/home/agent/persist/.gnupg\t", f"{run_line}\t")
                self.assertTrue(run_line.endswith(f"\tlocal/agent-workcell-{agent}\t--version"))

    def test_run_builds_target_image_only_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace, image_inspect_missing=True)
            subprocess.run([str(RUN_SANDBOX), "codex", "--", "--version"], cwd=workspace, env=env, check=True)
            lines = docker_log.read_text().splitlines()
            self.assertIn("DOCKER\timage\tinspect\tlocal/agent-workcell-codex", lines)
            self.assertIn("DOCKER\tcompose\tbuild\tagent-workcell-base", lines)
            self.assertIn("DOCKER\tcompose\tbuild\tagent-workcell-codex", lines)
            self.assertNotIn("agent-workcell-claude", "\n".join(lines))

    def test_run_skips_build_when_target_image_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run([str(RUN_SANDBOX), "opencode", "--", "--version"], cwd=workspace, env=env, check=True)
            log = docker_log.read_text()
            self.assertIn("DOCKER\timage\tinspect\tlocal/agent-workcell-opencode", log)
            self.assertNotIn("DOCKER\tcompose\tbuild", log)

    def test_cli_build_targets_base_then_requested_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run([str(CLI), "build", "pi", "--no-cache"], cwd=workspace, env=env, check=True)
            self.assertIn(
                "DOCKER\tps\nDOCKER\tcompose\tbuild\t--no-cache\tagent-workcell-base\nDOCKER\tcompose\tbuild\t--no-cache\tagent-workcell-pi",
                docker_log.read_text(),
            )

    def test_cli_build_all_targets_all_agent_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run([str(CLI), "build", "all"], cwd=workspace, env=env, check=True)
            self.assertIn(
                "DOCKER\tps\nDOCKER\tcompose\tbuild\tagent-workcell-base\nDOCKER\tcompose\tbuild\tagent-workcell-claude\tagent-workcell-opencode\tagent-workcell-codex\tagent-workcell-pi",
                docker_log.read_text(),
            )

    def test_cli_settings_uses_selected_agent_image_and_volume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run([str(CLI), "settings", "pi"], cwd=workspace, env=env, check=True)
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-pi:/data\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/data/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-pi\t", f"{log}\t")

    def test_opencode_session_helpers_use_opencode_volume_image_and_gpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run([str(CLI), "opencode-sessions-export"], cwd=workspace, env=env, check=True)
            (workspace / ".workcell" / "opencode-sessions" / "session.json").write_text("{}\n", encoding="utf-8")
            subprocess.run([str(CLI), "opencode-sessions-import"], cwd=workspace, env=env, check=True)
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-opencode:/home/agent/persist\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/home/agent/persist/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-opencode\t", f"{log}\t")

    def test_entrypoint_has_mismatch_guard(self):
        entrypoint = (REPO_ROOT / "sandbox" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("WORKCELL_IMAGE_AGENT", entrypoint)
        self.assertIn("image/agent mismatch", entrypoint)
        self.assertLess(entrypoint.index("image/agent mismatch"), entrypoint.index("workcell-agent-init.sh"))

    def test_agent_installers_are_not_in_base_dockerfile(self):
        base = (REPO_ROOT / "sandbox" / "dockerfiles" / "base.Dockerfile").read_text(encoding="utf-8")
        forbidden = ["claude.ai/install.sh", "opencode-linux", "@earendil-works/pi-coding-agent", "codex-${CODEX_ARCH}"]
        for token in forbidden:
            self.assertNotIn(token, base)


if __name__ == "__main__":
    unittest.main()
