import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SANDBOX = REPO_ROOT / "scripts" / "run_sandbox.sh"
PI_NOTIFICATION_EXTENSION = "/opt/workcell/pi-extensions/terminal-notify.ts"


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
        agent_args: list[str] | None = None,
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
        for name in [
            "WORKCELL_CONTEXT_REPO",
            "WORKCELL_PI_NOTIFICATIONS",
            "CMUX_SURFACE_ID",
            "CMUX_PANEL_ID",
        ]:
            env.pop(name, None)
        if extra_env:
            env.update(extra_env)

        subprocess.run(
            [str(RUN_SANDBOX), agent, "--", *(agent_args or ["status"])],
            cwd=workspace,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return docker_log.read_text(encoding="utf-8")

    def docker_run_args(self, docker_log: str) -> list[str]:
        run_line = next(
            line for line in docker_log.splitlines() if line.startswith("DOCKER\trun\t")
        )
        return run_line.split("\t")[1:]

    def launched_agent_args(self, docker_log: str, agent: str) -> list[str]:
        run_args = self.docker_run_args(docker_log)
        image_index = run_args.index(f"local/agent-workcell-{agent}")
        return run_args[image_index + 1 :]

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

    def test_pi_notifications_use_modern_cmux_identity_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(
                workspace,
                agent="pi",
                extra_env={
                    "WORKCELL_PI_NOTIFICATIONS": "enabled",
                    "CMUX_SURFACE_ID": "surface-1",
                },
            )

            self.assertEqual(
                self.launched_agent_args(docker_log, "pi"),
                ["--extension", PI_NOTIFICATION_EXTENSION, "status"],
            )
            run_args = self.docker_run_args(docker_log)
            self.assertFalse(any("CMUX_" in arg for arg in run_args))
            self.assertFalse(any(arg.endswith(".sock") for arg in run_args))

    def test_pi_notifications_fall_back_to_legacy_cmux_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(
                workspace,
                agent="pi",
                extra_env={
                    "WORKCELL_PI_NOTIFICATIONS": "enabled",
                    "CMUX_SURFACE_ID": "",
                    "CMUX_PANEL_ID": "panel-1",
                },
            )

            self.assertEqual(
                self.launched_agent_args(docker_log, "pi"),
                ["--extension", PI_NOTIFICATION_EXTENSION, "status"],
            )

    def test_pi_notifications_require_cmux_identity(self):
        for cmux_env in [{}, {"CMUX_SURFACE_ID": "", "CMUX_PANEL_ID": ""}]:
            with (
                self.subTest(cmux_env=cmux_env),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                docker_log = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    extra_env={"WORKCELL_PI_NOTIFICATIONS": "enabled", **cmux_env},
                )

                self.assertEqual(self.launched_agent_args(docker_log, "pi"), ["status"])

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
                docker_log = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    extra_env=extra_env,
                )

                self.assertEqual(self.launched_agent_args(docker_log, "pi"), ["status"])

    def test_pi_notification_config_overrides_host_setting(self):
        cases = [
            ("enabled", "disabled", ["status"]),
            (
                "disabled",
                "enabled",
                ["--extension", PI_NOTIFICATION_EXTENSION, "status"],
            ),
        ]
        for host_value, config_value, expected in cases:
            with (
                self.subTest(host=host_value, config=config_value),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                self.with_repo_config(
                    f'WORKCELL_PI_NOTIFICATIONS="{config_value}"\n'
                )
                docker_log = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    extra_env={
                        "WORKCELL_PI_NOTIFICATIONS": host_value,
                        "CMUX_SURFACE_ID": "surface-1",
                    },
                )

                self.assertEqual(self.launched_agent_args(docker_log, "pi"), expected)

    def test_config_cannot_manufacture_cmux_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.with_repo_config(
                "WORKCELL_PI_NOTIFICATIONS=enabled\nCMUX_SURFACE_ID=config-surface\n"
            )
            docker_log = self.run_with_fake_docker(workspace, agent="pi")

            self.assertEqual(self.launched_agent_args(docker_log, "pi"), ["status"])

    def test_pi_notifications_do_not_change_other_harnesses(self):
        for agent in ["opencode", "codex", "claude"]:
            with (
                self.subTest(agent=agent),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                docker_log = self.run_with_fake_docker(
                    workspace,
                    agent=agent,
                    extra_env={
                        "WORKCELL_PI_NOTIFICATIONS": "enabled",
                        "CMUX_SURFACE_ID": "surface-1",
                    },
                )

                self.assertEqual(self.launched_agent_args(docker_log, agent), ["status"])

    def test_pi_notification_extension_precedes_unchanged_user_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_args = [
                "--extension",
                "/tmp/user extension.ts",
                "--",
                "prompt with spaces",
                str(workspace / "path with spaces"),
            ]
            docker_log = self.run_with_fake_docker(
                workspace,
                agent="pi",
                agent_args=user_args,
                extra_env={
                    "WORKCELL_PI_NOTIFICATIONS": "enabled",
                    "CMUX_SURFACE_ID": "surface-1",
                },
            )
            launched_args = self.launched_agent_args(docker_log, "pi")

            self.assertEqual(
                launched_args,
                ["--extension", PI_NOTIFICATION_EXTENSION, *user_args],
            )
            self.assertEqual(launched_args.count(PI_NOTIFICATION_EXTENSION), 1)

    def test_pi_notification_extension_preserves_noninteractive_mode_arguments(self):
        for agent_args in [
            ["-p", "prompt with spaces"],
            ["--mode", "json", "prompt with spaces"],
            ["--mode", "rpc"],
        ]:
            with (
                self.subTest(agent_args=agent_args),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace = Path(temp_dir)
                docker_log = self.run_with_fake_docker(
                    workspace,
                    agent="pi",
                    agent_args=agent_args,
                    extra_env={
                        "WORKCELL_PI_NOTIFICATIONS": "enabled",
                        "CMUX_SURFACE_ID": "surface-1",
                    },
                )

                self.assertEqual(
                    self.launched_agent_args(docker_log, "pi"),
                    ["--extension", PI_NOTIFICATION_EXTENSION, *agent_args],
                )

    def test_cmux_env_file_entries_are_not_forwarded_or_used_for_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(
                workspace,
                "CMUX_SURFACE_ID=surface-from-file\n"
                "CMUX_SOCKET_PATH=/tmp/cmux.sock\n"
                "CMUX_API_KEY=secret\n"
                "CUSTOM=value\n",
                agent="pi",
                extra_env={"WORKCELL_PI_NOTIFICATIONS": "enabled"},
            )
            run_args = self.docker_run_args(docker_log)

            self.assertEqual(self.launched_agent_args(docker_log, "pi"), ["status"])
            self.assertFalse(any("CMUX_" in arg for arg in run_args))
            self.assertIn("CUSTOM=value", run_args)
            self.assertFalse(any("cmux.sock" in arg for arg in run_args))

    def test_env_file_cannot_enable_pi_notifications(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            docker_log = self.run_with_fake_docker(
                workspace,
                "WORKCELL_PI_NOTIFICATIONS=enabled\nCUSTOM=value\n",
                agent="pi",
                extra_env={"CMUX_SURFACE_ID": "surface-1"},
            )
            run_args = self.docker_run_args(docker_log)

            self.assertEqual(self.launched_agent_args(docker_log, "pi"), ["status"])
            self.assertFalse(
                any("WORKCELL_PI_NOTIFICATIONS" in arg for arg in run_args)
            )
            self.assertIn("CUSTOM=value", run_args)

    def test_config_template_enables_pi_notifications(self):
        template = (REPO_ROOT / "config.template.sh").read_text(encoding="utf-8")

        self.assertIn("WORKCELL_PI_NOTIFICATIONS=enabled", template)

    def test_unknown_agent_error_mentions_pi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = subprocess.run(
                [str(RUN_SANDBOX), "unknown"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
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
                check=False,
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
                check=False,
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
                check=False,
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
                check=False,
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
