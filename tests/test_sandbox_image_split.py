import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "cli.sh"


class SandboxImageSplitTests(unittest.TestCase):
    def setUp(self):
        self.config = REPO_ROOT / "config.sh"
        self.original_config = (
            self.config.read_text(encoding="utf-8") if self.config.exists() else None
        )
        self.config.unlink(missing_ok=True)
        self.addCleanup(self.restore_repo_config)

    def restore_repo_config(self):
        if self.original_config is None:
            self.config.unlink(missing_ok=True)
        else:
            self.config.write_text(self.original_config, encoding="utf-8")

    def with_repo_config(self, content: str):
        self.config.write_text(content, encoding="utf-8")

    def fake_docker_env(self, workspace: Path, image_inspect_missing: bool = False):
        fake_bin = workspace / "bin"
        fake_bin.mkdir()
        docker_log = workspace / "docker.log"
        fake_docker = fake_bin / "docker"
        fake_docker.write_text(
            "#!/bin/bash\n"
            "printf 'DOCKER' >> \"$DOCKER_LOG\"\n"
            'for arg in "$@"; do printf \'\\t%s\' "$arg" >> "$DOCKER_LOG"; done\n'
            "printf '\\n' >> \"$DOCKER_LOG\"\n"
            'if [ "${1:-}" = image ] && [ "${2:-}" = inspect ] && [ "${IMAGE_INSPECT_MISSING:-0}" = 1 ]; then exit 1; fi\n'
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

    def test_cli_run_uses_agent_image_volume_and_shared_gpg(self):
        for agent in ["pi", "opencode", "codex", "claude"]:
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                env, docker_log = self.fake_docker_env(workspace)
                subprocess.run(
                    [str(CLI), agent, "run", "--", "--version"],
                    cwd=workspace,
                    env=env,
                    check=True,
                )
                run_line = next(
                    line
                    for line in docker_log.read_text().splitlines()
                    if line.startswith("DOCKER\trun\t-d\t")
                )
                self.assertIn(
                    f"\t-v\tagent-workcell-{agent}:/home/agent/persist\t",
                    f"{run_line}\t",
                )
                self.assertIn(
                    "\t-v\tagent-workcell-gpg:/home/agent/persist/.gnupg\t",
                    f"{run_line}\t",
                )
                self.assertTrue(
                    run_line.endswith(f"\tlocal/agent-workcell-{agent}\t--version")
                )

    def test_cli_run_builds_target_image_only_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(
                workspace, image_inspect_missing=True
            )
            subprocess.run(
                [str(CLI), "codex", "run", "--", "--version"],
                cwd=workspace,
                env=env,
                check=True,
            )
            lines = docker_log.read_text().splitlines()
            self.assertIn("DOCKER\timage\tinspect\tlocal/agent-workcell-codex", lines)
            self.assertIn("DOCKER\tcompose\tbuild\tagent-workcell-base", lines)
            self.assertIn("DOCKER\tcompose\tbuild\tagent-workcell-codex", lines)
            self.assertNotIn("agent-workcell-claude", "\n".join(lines))

    def test_cli_run_skips_build_when_target_image_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "opencode", "run", "--", "--version"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn("DOCKER\timage\tinspect\tlocal/agent-workcell-opencode", log)
            self.assertNotIn("DOCKER\tcompose\tbuild", log)

    def test_cli_build_targets_base_then_requested_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "pi", "build", "--no-cache"],
                cwd=workspace,
                env=env,
                check=True,
            )
            self.assertIn(
                "DOCKER\tps\nDOCKER\tcompose\tbuild\t--no-cache\tagent-workcell-base\nDOCKER\tcompose\tbuild\t--no-cache\tagent-workcell-pi",
                docker_log.read_text(),
            )

    def test_cli_build_all_targets_all_agent_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run([str(CLI), "build"], cwd=workspace, env=env, check=True)
            self.assertIn(
                "DOCKER\tps\nDOCKER\tcompose\tbuild\tagent-workcell-base\nDOCKER\tcompose\tbuild\tagent-workcell-pi\tagent-workcell-opencode\tagent-workcell-codex\tagent-workcell-claude",
                docker_log.read_text(),
            )

    def test_cli_build_rejects_all_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            result = subprocess.run(
                [str(CLI), "build", "all"],
                cwd=workspace,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Error: unexpected argument: all", result.stdout)
            self.assertFalse(docker_log.exists())

    def test_cli_settings_uses_selected_agent_image_and_volume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "pi", "settings"], cwd=workspace, env=env, check=True
            )
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-pi:/data\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/data/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-pi\t", f"{log}\t")

    def test_cli_context_and_skill_mount_configured_context_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "agent-context"
            repo.mkdir()
            self.with_repo_config(f'WORKCELL_CONTEXT_REPO="{repo}"\n')
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "codex", "context", "open"],
                cwd=workspace,
                env=env,
                check=True,
            )
            subprocess.run(
                [str(CLI), "codex", "skill", "list"], cwd=workspace, env=env, check=True
            )
            log = docker_log.read_text()
            self.assertIn(f"\t-v\t{repo}:/opt/workcell-context:rw\t", f"{log}\t")
            self.assertNotIn("/opt/workcell-context:ro", log)

    def test_cli_context_uses_selected_agent_image_volume_and_gpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "codex", "context", "open"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-codex:/data\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/data/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-codex\t", f"{log}\t")
            self.assertIn("/data/.codex/AGENTS.md", log)
            self.assertIn("/data/.codex/workcell-context.md", log)
            self.assertIn("WORKCELL_CONTEXT_ACTION=open", log)
            self.assertIn("/opt/workcell-context-lib.sh", log)

    def test_cli_context_restore_uses_selected_agent_image_volume_and_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "claude", "context", "restore"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-claude:/data\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/data/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-claude\t", f"{log}\t")
            self.assertIn("WORKCELL_CONTEXT_ACTION=restore", log)
            self.assertIn("/data/.claude/CLAUDE.md", log)
            self.assertIn("/data/.claude/workcell-context.md", log)
            self.assertIn("/opt/workcell-context-lib.sh", log)

    def test_harness_skill_list_uses_selected_agent_image_and_volume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "opencode", "skill", "list"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-opencode:/data\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-opencode\t", f"{log}\t")
            self.assertIn("/data/.config/opencode/skills", log)
            self.assertIn("/data/.config/opencode/workcell-skills", log)
            self.assertIn("wc_skill_list", log)

    def test_harness_skill_edit_uses_selected_agent_image_volume_and_gpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "pi", "skill", "open", "chrome-integration"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-pi:/data\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/data/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-pi\t", f"{log}\t")
            self.assertIn("WORKCELL_SKILLS_NATIVE=/data/.pi/agent/skills", log)
            self.assertIn("WORKCELL_SKILLS_SOURCE=/data/.pi/agent/workcell-skills", log)
            self.assertIn("WORKCELL_SKILL_NAME=chrome-integration", log)
            self.assertIn("wc_skill_open", log)

    def test_harness_skill_restore_uses_selected_agent_image_volume_and_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "claude", "skill", "restore", "chrome-integration"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn("\t-v\tagent-workcell-claude:/data\t", f"{log}\t")
            self.assertIn("\t-v\tagent-workcell-gpg:/data/.gnupg\t", f"{log}\t")
            self.assertIn("\tlocal/agent-workcell-claude\t", f"{log}\t")
            self.assertIn("WORKCELL_SKILL_ACTION=restore", log)
            self.assertIn("WORKCELL_SKILLS_NATIVE=/data/.claude/skills", log)
            self.assertIn("WORKCELL_SKILLS_SOURCE=/data/.claude/workcell-skills", log)
            self.assertIn("WORKCELL_SKILL_NAME=chrome-integration", log)
            self.assertIn("wc_skill_restore", log)

    def test_migrate_moves_legacy_session_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            for name in [
                "claude-sessions",
                "opencode-sessions",
                "codex-sessions",
                "pi-sessions",
            ]:
                legacy_dir = workspace / ".workcell" / name
                legacy_dir.mkdir(parents=True)
                (legacy_dir / "session.json").write_text("{}\n", encoding="utf-8")
            task_file = (
                workspace
                / ".workcell"
                / "tasks"
                / "20260608-165656-restructure-project-scoped-workcell-dir.md"
            )
            task_file.parent.mkdir(parents=True)
            flat_task_dir = workspace / ".workcell" / "tasks" / "20260607-120000-finished-flat-task"
            flat_task_dir.mkdir(parents=True)
            (flat_task_dir / "task.md").write_text(
                "# Finished Flat Task\n"
                "\n"
                "- **Status:** completed\n"
                "- **Created:** 2026-06-07 12:00 GMT-3\n"
                "- **Updated:** 2026-06-07 12:30 GMT-3\n"
                "\n"
                "## Objective\n"
                "\n"
                "Already done.\n",
                encoding="utf-8",
            )
            (flat_task_dir / "log.md").write_text("# Finished Flat Task Log\n", encoding="utf-8")
            task_file.write_text(
                "# Restructure Project-Scoped Workcell Directory\n"
                "\n"
                "- **Status:** in_progress\n"
                "- **Created:** 2026-06-08 13:56 GMT-3\n"
                "- **Updated:** 2026-06-08 14:06 GMT-3\n"
                "\n"
                "## Objective\n"
                "\n"
                "Restructure `.workcell/`.\n"
                "\n"
                "## Context\n"
                "\n"
                "Project-scoped data needs cleanup.\n"
                "\n"
                "## Plan\n"
                "\n"
                "- [ ] Convert tasks.\n"
                "\n"
                "## Next Steps\n"
                "\n"
                "- Run migration.\n"
                "\n"
                "## Log\n"
                "\n"
                "- `2026-06-08 14:06 GMT-3` | `pi/gpt-5.5` | Started.\n"
                "\n"
                "## Dependencies\n"
                "\n"
                "None.\n"
                "\n"
                "## Notes\n"
                "\n"
                "Keep concise.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [str(CLI), "migrate"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            self.assertIn("Migration complete.", result.stdout)
            for harness in ["claude", "opencode", "codex", "pi"]:
                self.assertTrue(
                    (
                        workspace / ".workcell" / "sessions" / harness / "session.json"
                    ).is_file()
                )
            for name in [
                "claude-sessions",
                "opencode-sessions",
                "codex-sessions",
                "pi-sessions",
            ]:
                self.assertFalse((workspace / ".workcell" / name).exists())
            task_dir = (
                workspace
                / ".workcell"
                / "tasks"
                / "current"
                / "20260608-165656-restructure-project-scoped-workcell-dir"
            )
            self.assertFalse(task_file.exists())
            self.assertTrue((task_dir / "task.md").is_file())
            self.assertTrue((task_dir / "log.md").is_file())
            task_text = (task_dir / "task.md").read_text(encoding="utf-8")
            self.assertIn("- **Status:** current", task_text)
            self.assertIn("## Objective", task_text)
            self.assertNotIn("## Log", task_text)
            self.assertIn("Started.", (task_dir / "log.md").read_text(encoding="utf-8"))
            migrated_flat_task = (
                workspace / ".workcell" / "tasks" / "finished" / "20260607-120000-finished-flat-task"
            )
            self.assertFalse(flat_task_dir.exists())
            self.assertIn(
                "- **Status:** finished",
                (migrated_flat_task / "task.md").read_text(encoding="utf-8"),
            )

    def test_opencode_session_helpers_use_opencode_volume_image_and_gpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = self.fake_docker_env(workspace)
            subprocess.run(
                [str(CLI), "opencode", "sessions", "export"],
                cwd=workspace,
                env=env,
                check=True,
            )
            (workspace / ".workcell" / "sessions" / "opencode").mkdir(
                parents=True, exist_ok=True
            )
            (
                workspace / ".workcell" / "sessions" / "opencode" / "session.json"
            ).write_text("{}\n", encoding="utf-8")
            subprocess.run(
                [str(CLI), "opencode", "sessions", "import"],
                cwd=workspace,
                env=env,
                check=True,
            )
            log = docker_log.read_text()
            self.assertIn(
                "\t-v\tagent-workcell-opencode:/home/agent/persist\t", f"{log}\t"
            )
            self.assertIn(
                "\t-v\tagent-workcell-gpg:/home/agent/persist/.gnupg\t", f"{log}\t"
            )
            self.assertIn("\tlocal/agent-workcell-opencode\t", f"{log}\t")

    def test_top_level_agent_scoped_commands_show_helpful_error(self):
        for command, example in [
            ("run", "workcell pi run"),
            ("settings", "workcell pi settings"),
            ("context", "workcell pi context open"),
            ("skill", "workcell pi skill list"),
        ]:
            with self.subTest(command=command):
                result = subprocess.run(
                    [str(CLI), command, "list"],
                    cwd=REPO_ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"Error: '{command}' must be scoped to an agent", result.stdout
                )
                self.assertIn(example, result.stdout)

    def test_command_groups_without_subcommand_show_help(self):
        for command, expected in [
            (["pi"], "workcell pi run"),
            (["pi", "context"], "workcell pi context open"),
            (["pi", "skill"], "workcell pi skill list"),
            (["opencode", "sessions"], "workcell opencode sessions <export|import>"),
            (["gpg"], "workcell gpg new"),
            (["volume"], "workcell volume shell"),
        ]:
            with self.subTest(command=command):
                result = subprocess.run(
                    [str(CLI), *command],
                    cwd=REPO_ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)
                self.assertIn("Subcommands:", result.stdout)

    def test_cli_argless_commands_reject_unexpected_args(self):
        commands = [
            ["pi", "settings", "extra"],
            ["pi", "context", "open", "extra"],
            ["pi", "context", "restore", "extra"],
            ["pi", "skill", "list", "extra"],
            ["pi", "skill", "open", "chrome-integration", "extra"],
            ["pi", "skill", "restore", "chrome-integration", "extra"],
            ["opencode", "sessions", "export", "extra"],
            ["opencode", "sessions", "import", "extra"],
            ["gpg", "new", "extra"],
            ["gpg", "erase", "extra"],
            ["volume", "shell", "codex", "extra"],
            ["volume", "rm", "codex", "extra"],
        ]
        for command in commands:
            with (
                self.subTest(command=command),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                env, docker_log = self.fake_docker_env(workspace)
                result = subprocess.run(
                    [str(CLI), *command],
                    cwd=workspace,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Error: unexpected argument: extra", result.stdout)
                self.assertFalse(docker_log.exists())

    def test_entrypoint_has_mismatch_guard(self):
        entrypoint = (REPO_ROOT / "sandbox" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("WORKCELL_IMAGE_AGENT", entrypoint)
        self.assertIn("image/agent mismatch", entrypoint)
        self.assertLess(
            entrypoint.index("image/agent mismatch"),
            entrypoint.index("workcell-agent-init.sh"),
        )

    def test_agent_context_init_uses_shared_context_lib_and_workcell_sources(self):
        expected = {
            "claude.sh": (
                "/home/agent/persist/.claude/CLAUDE.md",
                "/home/agent/persist/.claude/workcell-context.md",
                "/home/agent/persist/.claude/workcell-skills",
            ),
            "opencode.sh": (
                "/home/agent/persist/.config/opencode/AGENTS.md",
                "/home/agent/persist/.config/opencode/workcell-context.md",
                "/home/agent/persist/.config/opencode/workcell-skills",
            ),
            "codex.sh": (
                "/home/agent/persist/.codex/AGENTS.md",
                "/home/agent/persist/.codex/workcell-context.md",
                "/home/agent/persist/.agents/workcell-skills",
            ),
            "pi.sh": (
                "/home/agent/persist/.pi/agent/AGENTS.md",
                "/home/agent/persist/.pi/agent/workcell-context.md",
                "/home/agent/persist/.pi/agent/workcell-skills",
            ),
        }
        for script_name, tokens in expected.items():
            with self.subTest(script=script_name):
                script = (REPO_ROOT / "sandbox" / "agent-init" / script_name).read_text(
                    encoding="utf-8"
                )
                self.assertIn("/opt/workcell-context-lib.sh", script)
                self.assertIn("wc_prepare_all", script)
                for token in tokens:
                    self.assertIn(token, script)

    def test_agent_installers_are_not_in_base_dockerfile(self):
        base = (REPO_ROOT / "sandbox" / "dockerfiles" / "base.Dockerfile").read_text(
            encoding="utf-8"
        )
        forbidden = [
            "@earendil-works/pi-coding-agent",
            "opencode-linux",
            "codex-${CODEX_ARCH}",
            "claude.ai/install.sh",
        ]
        for token in forbidden:
            self.assertNotIn(token, base)


if __name__ == "__main__":
    unittest.main()
