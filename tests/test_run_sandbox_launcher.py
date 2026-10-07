import subprocess
import tempfile
import unittest
from pathlib import Path

from shell_test_support import fake_docker_env, read_docker_invocations, temporary_script_repo

PI_COMPACTION_EXTENSION = "/opt/workcell/pi-extensions/compact-session.ts"
PI_REASONING_EXTENSION = "/opt/workcell/pi-extensions/reasoning-effort.ts"
PI_CONTEXT_USAGE_EXTENSION = "/opt/workcell/pi-extensions/context-usage.ts"
PI_DEFAULT_EXTENSION_ARGS = [
    "--extension", PI_COMPACTION_EXTENSION,
    "--extension", PI_REASONING_EXTENSION,
    "--extension", PI_CONTEXT_USAGE_EXTENSION,
]
PI_NOTIFICATION_EXTENSION = "/opt/workcell/pi-extensions/terminal-notify.ts"


class RunSandboxLauncherTests(unittest.TestCase):
    def setUp(self):
        self.repo = temporary_script_repo(self)
        self.config = self.repo / "config.sh"
        self.run_sandbox = self.repo / "scripts" / "run_sandbox.sh"

    def with_repo_config(self, content: str):
        self.config.write_text(content, encoding="utf-8")

    def run_launcher(self, workspace: Path, args: list[str], env=None):
        if env is None:
            env, _ = fake_docker_env(workspace)
        return subprocess.run(
            [str(self.run_sandbox), *args],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=15, check=False,
        )

    def run_with_fake_docker(
        self,
        workspace: Path,
        env_file: str | None = None,
        agent: str = "codex",
        agent_args: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> list[list[str]]:
        env, docker_log = fake_docker_env(workspace, extra_env=extra_env)
        workcell_dir = workspace / ".workcell"
        workcell_dir.mkdir(exist_ok=True)
        if env_file is not None:
            (workcell_dir / ".env").write_text(env_file, encoding="utf-8")
        result = self.run_launcher(
            workspace, [agent, "--", *(agent_args if agent_args is not None else ["status"])], env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return read_docker_invocations(docker_log)

    def docker_run_args(self, invocations: list[list[str]]) -> list[str]:
        runs = [args for args in invocations if args[:1] == ["run"]]
        self.assertEqual(len(runs), 1, invocations)
        return runs[0]

    def assert_docker_option(self, args: list[str], option: str, value: str):
        self.assertIn((option, value), list(zip(args, args[1:])))

    def launched_agent_args(self, invocations: list[list[str]], agent: str) -> list[str]:
        run_args = self.docker_run_args(invocations)
        image_index = run_args.index(f"local/agent-workcell-{agent}")
        return run_args[image_index + 1:]

    def test_pi_bundled_extensions_are_default_for_bare_launch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(workspace, agent="pi", agent_args=[])

            launched_args = self.launched_agent_args(invocations, "pi")
            self.assertEqual(launched_args, PI_DEFAULT_EXTENSION_ARGS)
            self.assertEqual(launched_args.count(PI_COMPACTION_EXTENSION), 1)
            self.assertEqual(launched_args.count(PI_REASONING_EXTENSION), 1)
            self.assertEqual(launched_args.count(PI_CONTEXT_USAGE_EXTENSION), 1)
            self.assertNotIn(PI_NOTIFICATION_EXTENSION, launched_args)

    def test_pi_bundled_extensions_preserve_native_selection_and_mode_options(self):
        for notification_enabled in [False, True]:
            for user_args in [
                ["--exclude-tools", "compact_session"],
                ["--exclude-tools", "get_model_info,set_reasoning_effort"],
                ["--exclude-tools", "get_context_usage"],
                ["--tools", "get_context_usage", "--no-extensions"],
                ["--tools", "read,get_context_usage", "--no-extensions"],
                ["--tools", "read,compact_session", "--no-extensions"],
                ["--tools", "read,get_model_info,set_reasoning_effort", "--no-extensions"],
                ["--no-tools"],
                ["--no-builtin-tools"],
                ["--print", "prompt with spaces"],
                ["--mode", "json", "prompt with spaces"],
                ["--mode", "rpc"],
            ]:
                with (
                    self.subTest(notifications=notification_enabled, user_args=user_args),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    workspace = Path(temp_dir)
                    invocations = self.run_with_fake_docker(
                        workspace, agent="pi", agent_args=user_args,
                        extra_env={
                            "WORKCELL_PI_NOTIFICATIONS": "enabled" if notification_enabled else "disabled",
                            "CMUX_SURFACE_ID": "surface-1",
                        },
                    )
                    optional = ["--extension", PI_NOTIFICATION_EXTENSION] if notification_enabled else []
                    self.assertEqual(
                        self.launched_agent_args(invocations, "pi"),
                        [*PI_DEFAULT_EXTENSION_ARGS, *optional, *user_args],
                    )

    def test_pi_extensions_preserve_exact_user_argument_vector(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_args = [
                "--extension", "/tmp/user extension.ts", "--no-extensions", "--",
                "prompt with spaces\nand a tab\tand unicode: café", "", "--port", "1234",
                str(workspace / "path with spaces"),
            ]
            invocations = self.run_with_fake_docker(
                workspace, agent="pi", agent_args=user_args,
                extra_env={"WORKCELL_PI_NOTIFICATIONS": "enabled", "CMUX_SURFACE_ID": "surface-1"},
            )
            launched_args = self.launched_agent_args(invocations, "pi")
            self.assertEqual(
                launched_args,
                [*PI_DEFAULT_EXTENSION_ARGS, "--extension", PI_NOTIFICATION_EXTENSION, *user_args],
            )
            self.assertEqual(launched_args.count(PI_COMPACTION_EXTENSION), 1)
            self.assertEqual(launched_args.count(PI_REASONING_EXTENSION), 1)
            self.assertEqual(launched_args.count(PI_CONTEXT_USAGE_EXTENSION), 1)
            self.assertEqual(launched_args.count(PI_NOTIFICATION_EXTENSION), 1)

    def test_pi_agent_is_passed_to_docker_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(workspace, agent="pi")

            self.assert_docker_option(self.docker_run_args(invocations), "-e", "AGENT_CLI=pi")

    def test_pi_sessions_are_mounted_from_workcell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(workspace, agent="pi")

            expected_mount = (
                f"{workspace / '.workcell' / 'sessions' / 'pi'}:"
                f"/home/agent/persist/.pi/agent/sessions/--workspaces-{workspace.name}--"
            )
            self.assert_docker_option(self.docker_run_args(invocations), "-v", expected_mount)
            self.assertTrue((workspace / ".workcell" / "sessions" / "pi").is_dir())

    def test_pi_notifications_use_modern_cmux_identity_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(
                workspace,
                agent="pi",
                extra_env={
                    "WORKCELL_PI_NOTIFICATIONS": "enabled",
                    "CMUX_SURFACE_ID": "surface-1",
                },
            )

            self.assertEqual(
                self.launched_agent_args(invocations, "pi"),
                [*PI_DEFAULT_EXTENSION_ARGS, "--extension", PI_NOTIFICATION_EXTENSION, "status"],
            )
            run_args = self.docker_run_args(invocations)
            self.assertFalse(any("CMUX_" in arg for arg in run_args))
            self.assertFalse(any(arg.endswith(".sock") for arg in run_args))

    def test_pi_notifications_fall_back_to_legacy_cmux_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(
                workspace,
                agent="pi",
                extra_env={
                    "WORKCELL_PI_NOTIFICATIONS": "enabled",
                    "CMUX_SURFACE_ID": "",
                    "CMUX_PANEL_ID": "panel-1",
                },
            )

            self.assertEqual(
                self.launched_agent_args(invocations, "pi"),
                [*PI_DEFAULT_EXTENSION_ARGS, "--extension", PI_NOTIFICATION_EXTENSION, "status"],
            )

    def test_pi_notifications_require_cmux_identity(self):
        for cmux_env in [{}, {"CMUX_SURFACE_ID": "", "CMUX_PANEL_ID": ""}]:
            with (
                self.subTest(cmux_env=cmux_env),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                invocations = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    extra_env={"WORKCELL_PI_NOTIFICATIONS": "enabled", **cmux_env},
                )

                self.assertEqual(self.launched_agent_args(invocations, "pi"), [*PI_DEFAULT_EXTENSION_ARGS, "status"])

    def test_pi_notifications_require_exact_enabled_value(self):
        for value in [None, "", "disabled", "1", "ENABLED"]:
            with (
                self.subTest(value=value),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                extra_env = {"CMUX_SURFACE_ID": "surface-1"}
                if value is not None:
                    extra_env["WORKCELL_PI_NOTIFICATIONS"] = value
                invocations = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    extra_env=extra_env,
                )

                self.assertEqual(self.launched_agent_args(invocations, "pi"), [*PI_DEFAULT_EXTENSION_ARGS, "status"])

    def test_pi_notification_config_overrides_host_setting(self):
        cases = [
            ("enabled", "disabled", [*PI_DEFAULT_EXTENSION_ARGS, "status"]),
            (
                "disabled",
                "enabled",
                [*PI_DEFAULT_EXTENSION_ARGS, "--extension", PI_NOTIFICATION_EXTENSION, "status"],
            ),
        ]
        for host_value, config_value, expected in cases:
            with (
                self.subTest(host=host_value, config=config_value),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                self.with_repo_config(f'WORKCELL_PI_NOTIFICATIONS="{config_value}"\n')
                invocations = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    extra_env={
                        "WORKCELL_PI_NOTIFICATIONS": host_value,
                        "CMUX_SURFACE_ID": "surface-1",
                    },
                )

                self.assertEqual(self.launched_agent_args(invocations, "pi"), expected)

    def test_config_cannot_manufacture_cmux_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.with_repo_config("WORKCELL_PI_NOTIFICATIONS=enabled\nCMUX_SURFACE_ID=config-surface\n")
            invocations = self.run_with_fake_docker(workspace, agent="pi")

            self.assertEqual(self.launched_agent_args(invocations, "pi"), [*PI_DEFAULT_EXTENSION_ARGS, "status"])

    def test_pi_notifications_do_not_change_other_harnesses(self):
        for agent in ["opencode", "codex", "claude"]:
            with (
                self.subTest(agent=agent),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                invocations = self.run_with_fake_docker(
                    workspace,
                    agent=agent,
                    extra_env={
                        "WORKCELL_PI_NOTIFICATIONS": "enabled",
                        "CMUX_SURFACE_ID": "surface-1",
                    },
                )

                self.assertEqual(self.launched_agent_args(invocations, agent), ["status"])

    def test_cmux_env_file_entries_are_not_forwarded_or_used_for_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(
                workspace,
                "CMUX_SURFACE_ID=surface-from-file\n"
                "CMUX_SOCKET_PATH=/tmp/cmux.sock\n"
                "CMUX_API_KEY=secret\n"
                "CUSTOM=value\n",
                agent="pi",
                extra_env={"WORKCELL_PI_NOTIFICATIONS": "enabled"},
            )
            run_args = self.docker_run_args(invocations)

            self.assertEqual(self.launched_agent_args(invocations, "pi"), [*PI_DEFAULT_EXTENSION_ARGS, "status"])
            self.assertFalse(any("CMUX_" in arg for arg in run_args))
            self.assert_docker_option(run_args, "-e", "CUSTOM=value")
            self.assertFalse(any("cmux.sock" in arg for arg in run_args))

    def test_env_file_cannot_enable_pi_notifications(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(
                workspace,
                "WORKCELL_PI_NOTIFICATIONS=enabled\nCUSTOM=value\n",
                agent="pi",
                extra_env={"CMUX_SURFACE_ID": "surface-1"},
            )
            run_args = self.docker_run_args(invocations)

            self.assertEqual(self.launched_agent_args(invocations, "pi"), [*PI_DEFAULT_EXTENSION_ARGS, "status"])
            self.assertFalse(any("WORKCELL_PI_NOTIFICATIONS" in arg for arg in run_args))
            self.assert_docker_option(run_args, "-e", "CUSTOM=value")

    def test_unknown_agent_error_mentions_pi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = self.run_launcher(workspace, ["unknown"])

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("'pi', 'opencode', 'codex', or 'claude'", result.stdout + result.stderr)

    def test_flutter_project_dir_requires_flutter_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = self.run_launcher(workspace, ["codex", "--flutter-project-dir", "./gui"])

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--flutter-project-dir requires --with-flutter", result.stdout + result.stderr)

    def test_flutter_project_dir_must_exist_under_workspace(self):
        self.with_repo_config("\n")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = self.run_launcher(workspace, ["codex", "--with-flutter", "--flutter-project-dir", "./gui"])

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Flutter project directory not found", result.stdout + result.stderr)

    def test_flutter_project_dir_must_be_relative(self):
        self.with_repo_config("\n")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = self.run_launcher(workspace, ["codex", "--with-flutter", "--flutter-project-dir", "/tmp"])

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("must be relative to the workspace directory", result.stdout + result.stderr)

    def test_context_repo_env_is_ignored_when_not_in_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(workspace, extra_env={"WORKCELL_CONTEXT_REPO": str(workspace)})
            run_args = self.docker_run_args(invocations)
            self.assertFalse(any("/opt/workcell-context" in arg for arg in run_args))

    def test_context_repo_config_adds_writable_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "agent-context"
            repo.mkdir()
            self.with_repo_config(f'WORKCELL_CONTEXT_REPO="{repo}"\n')
            run_args = self.docker_run_args(self.run_with_fake_docker(workspace))
            self.assert_docker_option(run_args, "-v", f"{repo}:/opt/workcell-context:rw")
            self.assertNotIn(f"{repo}:/opt/workcell-context:ro", run_args)

    def test_context_repo_config_rejects_relative_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.with_repo_config('WORKCELL_CONTEXT_REPO="relative/context"\n')
            result = self.run_launcher(workspace, ["codex", "--", "status"])
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WORKCELL_CONTEXT_REPO must be an absolute", result.stdout + result.stderr)

    def test_context_repo_env_file_entry_is_not_passed_to_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(
                workspace,
                f"WORKCELL_CONTEXT_REPO={workspace}\nCUSTOM=value\n",
            )
            run_args = self.docker_run_args(invocations)
            self.assertFalse(any("WORKCELL_CONTEXT_REPO" in arg for arg in run_args))
            self.assertFalse(any("/opt/workcell-context" in arg for arg in run_args))
            self.assert_docker_option(run_args, "-e", "CUSTOM=value")

    def test_env_file_is_passed_to_docker_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            invocations = self.run_with_fake_docker(
                workspace,
                "CUSTOM=value\nQUOTED=\"value with spaces\"\n",
            )

            run_args = self.docker_run_args(invocations)
            self.assert_docker_option(run_args, "-e", "CUSTOM=value")
            self.assert_docker_option(run_args, "-e", "QUOTED=value with spaces")
            self.assertLess(run_args.index("CUSTOM=value"), run_args.index("AGENT_CLI=codex"))

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
            for status in ["accepted", "current", "deferred", "dropped", "finished"]:
                self.assertTrue((workspace / ".workcell" / "tasks" / status).is_dir())

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
