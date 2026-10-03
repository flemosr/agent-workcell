import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shell_test_support import fake_docker_env, read_docker_invocations, temporary_script_repo
from test_pi_compaction_lifecycle import RUNNER, pi_package_root

REPO_ROOT = Path(__file__).resolve().parents[1]


class SandboxImageSplitTests(unittest.TestCase):
    def setUp(self):
        self.repo = temporary_script_repo(self)
        self.config = self.repo / "config.sh"
        self.cli = self.repo / "cli.sh"

    def with_repo_config(self, content: str):
        self.config.write_text(content, encoding="utf-8")

    def run_cli(self, workspace: Path, args: list[str], env=None, expect_success=True):
        if env is None:
            env, _ = fake_docker_env(workspace)
        result = subprocess.run(
            [str(self.cli), *args],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=15, check=False,
        )
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def docker_run_args(self, docker_log: Path) -> list[str]:
        invocations = read_docker_invocations(docker_log)
        runs = [args for args in invocations if args[:1] == ["run"]]
        self.assertEqual(len(runs), 1, invocations)
        return runs[0]

    def assert_docker_option(self, args: list[str], option: str, value: str):
        self.assertIn((option, value), list(zip(args, args[1:])))

    def test_cli_run_uses_agent_image_volume_and_shared_gpg(self):
        for agent in ["pi", "opencode", "codex", "claude"]:
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                env, docker_log = fake_docker_env(workspace)
                self.run_cli(workspace, [agent, "run", "--", "--version"], env)
                run_args = self.docker_run_args(docker_log)
                self.assertEqual(run_args[:2], ["run", "-d"])
                self.assert_docker_option(run_args, "-v", f"agent-workcell-{agent}:/home/agent/persist")
                self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/home/agent/persist/.gnupg")
                image_index = run_args.index(f"local/agent-workcell-{agent}")
                expected = ["--version"]
                if agent == "pi":
                    expected = ["--extension", "/opt/workcell/pi-extensions/compact-session.ts", *expected]
                self.assertEqual(run_args[image_index + 1:], expected)

    def test_cli_update_uses_native_command_and_isolated_persistent_volume(self):
        expected_args = {
            "pi": ["update", "--self"],
            "opencode": ["upgrade", "--method", "curl"],
            "codex": ["update"],
            "claude": ["update"],
        }
        for agent, native_args in expected_args.items():
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                env, docker_log = fake_docker_env(workspace)
                self.run_cli(workspace, [agent, "update"], env)
                invocations = read_docker_invocations(docker_log)
                run_args = self.docker_run_args(docker_log)
                self.assertEqual(run_args[:3], ["run", "--rm", "--init"])
                self.assertFalse(any(args[:2] == ["compose", "build"] for args in invocations))
                self.assert_docker_option(run_args, "-v", f"agent-workcell-{agent}:/home/agent/persist")
                self.assert_docker_option(
                    run_args, "--tmpfs",
                    "/home/agent/persist/.gnupg:rw,noexec,nosuid,nodev,size=64k,mode=0700",
                )
                self.assertFalse(any("agent-workcell-gpg" in arg for arg in run_args))
                self.assert_docker_option(run_args, "-e", f"AGENT_CLI={agent}")
                self.assertEqual(run_args[-(len(native_args) + 1):], [f"local/agent-workcell-{agent}", *native_args])
                self.assertEqual(
                    ("-e", "WORKCELL_CLAUDE_UPDATE=1") in list(zip(run_args, run_args[1:])),
                    agent == "claude",
                )
                for excluded in [str(workspace), "/workspaces/", "WORKCELL_CONTEXT", "ENABLE_FIREWALL"]:
                    self.assertFalse(any(excluded in arg for arg in run_args), (excluded, run_args))

    def test_cli_update_builds_selected_image_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace, image_inspect_missing=True)
            self.run_cli(workspace, ["claude", "update"], env)
            invocations = read_docker_invocations(docker_log)
            self.assertIn(["image", "inspect", "local/agent-workcell-claude"], invocations)
            self.assertEqual(
                [args for args in invocations if args[:2] == ["compose", "build"]],
                [["compose", "build", "agent-workcell-base"], ["compose", "build", "agent-workcell-claude"]],
            )
            run_args = self.docker_run_args(docker_log)
            self.assertEqual(run_args[:3], ["run", "--rm", "--init"])
            self.assertEqual(run_args[-2:], ["local/agent-workcell-claude", "update"])

    def test_cli_update_help_lists_native_command_without_docker(self):
        expected = {
            "pi": "pi update --self",
            "opencode": "opencode upgrade --method curl",
            "codex": "codex update",
            "claude": "claude update",
        }
        for agent, native_command in expected.items():
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                env, docker_log = fake_docker_env(workspace)
                result = self.run_cli(workspace, [agent, "update", "--help"], env)
                self.assertIn(f"workcell {agent} update", result.stdout)
                self.assertIn(native_command, result.stdout)
                self.assertFalse(docker_log.exists())

    def test_cli_run_builds_target_image_only_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace, image_inspect_missing=True)
            self.run_cli(workspace, ["codex", "run", "--", "--version"], env)
            invocations = read_docker_invocations(docker_log)
            self.assertIn(["image", "inspect", "local/agent-workcell-codex"], invocations)
            self.assertEqual(
                [args for args in invocations if args[:2] == ["compose", "build"]],
                [["compose", "build", "agent-workcell-base"], ["compose", "build", "agent-workcell-codex"]],
            )

    def test_cli_run_skips_build_when_target_image_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["opencode", "run", "--", "--version"], env)
            invocations = read_docker_invocations(docker_log)
            self.assertIn(["image", "inspect", "local/agent-workcell-opencode"], invocations)
            self.assertFalse(any(args[:2] == ["compose", "build"] for args in invocations))

    def test_cli_build_targets_base_then_requested_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["pi", "build", "--no-cache"], env)
            self.assertEqual(
                read_docker_invocations(docker_log),
                [
                    ["ps"],
                    ["compose", "build", "--no-cache", "agent-workcell-base"],
                    ["compose", "build", "--no-cache", "agent-workcell-pi"],
                ],
            )

    def test_cli_build_all_targets_all_agent_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["build"], env)
            self.assertEqual(
                read_docker_invocations(docker_log),
                [
                    ["ps"],
                    ["compose", "build", "agent-workcell-base"],
                    ["compose", "build", "agent-workcell-pi", "agent-workcell-opencode", "agent-workcell-codex", "agent-workcell-claude"],
                ],
            )

    def test_cli_build_rejects_all_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            result = self.run_cli(workspace, ["build", "all"], env, expect_success=False)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Error: unexpected argument: all", result.stdout)
            self.assertFalse(docker_log.exists())

    def test_cli_settings_uses_selected_agent_image_and_volume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["pi", "settings"], env)
            run_args = self.docker_run_args(docker_log)
            self.assert_docker_option(run_args, "-v", "agent-workcell-pi:/data")
            self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/data/.gnupg")
            self.assertIn("local/agent-workcell-pi", run_args)

    def test_cli_context_and_skill_mount_configured_context_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "agent-context"
            repo.mkdir()
            self.with_repo_config(f'WORKCELL_CONTEXT_REPO="{repo}"\n')
            env, docker_log = fake_docker_env(workspace)
            for command in [["codex", "context", "open"], ["codex", "skill", "list"]]:
                self.run_cli(workspace, command, env)
            runs = [args for args in read_docker_invocations(docker_log) if args[:1] == ["run"]]
            self.assertEqual(len(runs), 2)
            for args in runs:
                self.assert_docker_option(args, "-v", f"{repo}:/opt/workcell-context:rw")
                self.assertNotIn(f"{repo}:/opt/workcell-context:ro", args)

    def test_cli_context_uses_selected_agent_image_volume_and_gpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["codex", "context", "open"], env)
            run_args = self.docker_run_args(docker_log)
            self.assert_docker_option(run_args, "-v", "agent-workcell-codex:/data")
            self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/data/.gnupg")
            self.assertIn("local/agent-workcell-codex", run_args)
            self.assert_docker_option(run_args, "-e", "WORKCELL_CONTEXT_NATIVE=/data/.codex/AGENTS.md")
            self.assert_docker_option(run_args, "-e", "WORKCELL_CONTEXT_SOURCE=/data/.codex/workcell-context.md")
            self.assert_docker_option(run_args, "-e", "WORKCELL_CONTEXT_ACTION=open")
            self.assertIn("/opt/workcell-context-lib.sh", run_args[-1])

    def test_cli_context_restore_uses_selected_agent_image_volume_and_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["claude", "context", "restore"], env)
            run_args = self.docker_run_args(docker_log)
            self.assert_docker_option(run_args, "-v", "agent-workcell-claude:/data")
            self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/data/.gnupg")
            self.assertIn("local/agent-workcell-claude", run_args)
            self.assert_docker_option(run_args, "-e", "WORKCELL_CONTEXT_ACTION=restore")
            self.assert_docker_option(run_args, "-e", "WORKCELL_CONTEXT_NATIVE=/data/.claude/CLAUDE.md")
            self.assert_docker_option(run_args, "-e", "WORKCELL_CONTEXT_SOURCE=/data/.claude/workcell-context.md")
            self.assertIn("/opt/workcell-context-lib.sh", run_args[-1])

    def test_harness_skill_list_uses_selected_agent_image_and_volume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["opencode", "skill", "list"], env)
            run_args = self.docker_run_args(docker_log)
            self.assert_docker_option(run_args, "-v", "agent-workcell-opencode:/data")
            self.assertIn("local/agent-workcell-opencode", run_args)
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILLS_NATIVE=/data/.config/opencode/skills")
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILLS_SOURCE=/data/.config/opencode/workcell-skills")
            self.assertIn("wc_skill_list", run_args[-1])

    def test_harness_skill_edit_uses_selected_agent_image_volume_and_gpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["pi", "skill", "open", "chrome-integration"], env)
            run_args = self.docker_run_args(docker_log)
            self.assert_docker_option(run_args, "-v", "agent-workcell-pi:/data")
            self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/data/.gnupg")
            self.assertIn("local/agent-workcell-pi", run_args)
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILLS_NATIVE=/data/.pi/agent/skills")
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILLS_SOURCE=/data/.pi/agent/workcell-skills")
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILL_NAME=chrome-integration")
            self.assertIn("wc_skill_open", run_args[-1])

    def test_harness_skill_restore_uses_selected_agent_image_volume_and_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["claude", "skill", "restore", "chrome-integration"], env)
            run_args = self.docker_run_args(docker_log)
            self.assert_docker_option(run_args, "-v", "agent-workcell-claude:/data")
            self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/data/.gnupg")
            self.assertIn("local/agent-workcell-claude", run_args)
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILL_ACTION=restore")
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILLS_NATIVE=/data/.claude/skills")
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILLS_SOURCE=/data/.claude/workcell-skills")
            self.assert_docker_option(run_args, "-e", "WORKCELL_SKILL_NAME=chrome-integration")
            self.assertIn("wc_skill_restore", run_args[-1])

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

            result = self.run_cli(workspace, ["migrate"])

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
            env, docker_log = fake_docker_env(workspace)
            self.run_cli(workspace, ["opencode", "sessions", "export"], env)
            (workspace / ".workcell" / "sessions" / "opencode").mkdir(
                parents=True, exist_ok=True
            )
            (
                workspace / ".workcell" / "sessions" / "opencode" / "session.json"
            ).write_text("{}\n", encoding="utf-8")
            self.run_cli(workspace, ["opencode", "sessions", "import"], env)
            runs = [args for args in read_docker_invocations(docker_log) if args[:1] == ["run"]]
            self.assertEqual(len(runs), 2)
            for action, run_args in zip(["export", "import"], runs):
                with self.subTest(action=action):
                    self.assert_docker_option(run_args, "-v", "agent-workcell-opencode:/home/agent/persist")
                    self.assert_docker_option(run_args, "-v", "agent-workcell-gpg:/home/agent/persist/.gnupg")
                    self.assertIn("local/agent-workcell-opencode", run_args)
                    self.assertIn(f"opencode {action}", run_args[-1])

    def test_top_level_agent_scoped_commands_show_helpful_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            for command, example in [
                ("run", "workcell pi run"),
                ("update", "workcell pi update"),
                ("settings", "workcell pi settings"),
                ("context", "workcell pi context open"),
                ("skill", "workcell pi skill list"),
            ]:
                with self.subTest(command=command):
                    result = self.run_cli(workspace, [command, "list"], env, expect_success=False)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(f"Error: '{command}' must be scoped to an agent", result.stdout)
                    self.assertIn(example, result.stdout)
                    self.assertFalse(docker_log.exists())

    def test_command_groups_without_subcommand_show_help(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            env, docker_log = fake_docker_env(workspace)
            for command, expected in [
                (["pi"], "workcell pi run"),
                (["pi", "context"], "workcell pi context open"),
                (["pi", "skill"], "workcell pi skill list"),
                (["opencode", "sessions"], "workcell opencode sessions <export|import>"),
                (["gpg"], "workcell gpg new"),
                (["volume"], "workcell volume shell"),
            ]:
                with self.subTest(command=command):
                    result = self.run_cli(workspace, command, env)
                    self.assertIn(expected, result.stdout)
                    self.assertIn("Subcommands:", result.stdout)
                    self.assertFalse(docker_log.exists())

    def test_cli_argless_commands_reject_unexpected_args(self):
        commands = [
            ["pi", "update", "extra"],
            ["pi", "update", "--help", "extra"],
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
                env, docker_log = fake_docker_env(workspace)
                result = self.run_cli(workspace, command, env, expect_success=False)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Error: unexpected argument: extra", result.stdout)
                self.assertFalse(docker_log.exists())

    def test_pi_packaged_extensions_load_without_user_resources(self):
        package = pi_package_root()
        if package is None:
            self.skipTest("Pi SDK unavailable; packaged extension acceptance requires Pi or PI_TEST_PACKAGE_ROOT")
        dockerfile = (REPO_ROOT / "sandbox" / "dockerfiles" / "pi.Dockerfile").read_text()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_root = Path(temp_dir) / "image with spaces"
            # Reproduce the image's extension COPY layout outside the project; this is not a Docker build.
            for line in dockerfile.splitlines():
                if line.startswith("COPY pi-extensions/"):
                    _, source, destination = line.split()
                    target = image_root / destination.lstrip("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(REPO_ROOT / "sandbox" / source, target)
            extensions = image_root / "opt" / "workcell" / "pi-extensions"
            result = subprocess.run(
                ["node", "--experimental-import-meta-resolve", str(RUNNER), str(package),
                 str(extensions / "compact-session.ts"), str(extensions / "terminal-notify.ts"), "native-success"],
                cwd=REPO_ROOT, text=True, capture_output=True, timeout=120, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["passed"], payload)
            self.assertEqual([report["name"] for report in payload["reports"]], ["native-success"])
            for report in payload["reports"]:
                with self.subTest(case=report["name"], pi_version=payload["packageVersion"]):
                    self.assertTrue(report["passed"], report)


if __name__ == "__main__":
    unittest.main()
