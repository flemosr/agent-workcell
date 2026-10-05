"""Offline managed Pi build/startup fixtures; no root, installer network, or user state."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = REPO_ROOT / "sandbox" / "agent-init" / "pi.sh"
DOCKERFILE = REPO_ROOT / "sandbox" / "dockerfiles" / "pi.Dockerfile"
LAUNCHER = '''#!/bin/sh
root=$(dirname "$(dirname "$(readlink -f "$0")")")
IFS= read -r version < "$root/install/current-version" || exit 1
PI_MANAGED_INSTALL_ROOT="$root/install"
export PI_MANAGED_INSTALL_ROOT
exec "$root/install/releases/$version/node_modules/.bin/pi" "$@"
'''


class PiInitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.agent = self.home / "persist" / ".pi" / "agent"
        self.agent.mkdir(parents=True)
        self.install = self.agent / "install"
        self.launcher = self.agent / "bin" / "pi"
        self.entrypoint = self.home / ".local" / "bin" / "pi"
        self.entrypoint.parent.mkdir(parents=True)
        self.template = self.root / "template"
        self.marker = {"kind": "pi-managed-install", "schemaVersion": 1, "layout": "releases-v1",
                       "entrypoint": {"type": "symlink", "path": str(self.entrypoint)}}
        self.make_install(self.template, "1.0.3")
        self.entrypoint.symlink_to(self.template / "bin" / "pi")
        self.original_state = {}
        for name in ["auth.json", "settings.json", "sessions/saved.jsonl", "AGENTS.md", "workcell-context.md",
                     "skills/custom/SKILL.md", "workcell-skills/custom/SKILL.md", "packages/custom/resource"]:
            path = self.agent / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture user state: " + name + "\n")
            self.original_state[path] = path.read_bytes()
        legacy = self.agent / "self" / "bin" / "pi"
        self.write_executable(legacy, "#!/bin/sh\nprintf 'legacy executable\\n'\n")
        self.original_state[legacy] = legacy.read_bytes()
        self.chown_log = self.root / "chown.log"
        self.context_lib = self.root / "context-lib.sh"
        self.context_lib.write_text(
            "wc_prepare_all() { :; }\nwc_chown_persisted_context() { :; }\nwc_chown_persisted_skills() { :; }\n"
            f'chown() {{ printf "%s\\n" "$*" >> "{self.chown_log}"; }}\n'
        )
        self.script = self.root / "pi-init.sh"
        self.script.write_text(INIT_SCRIPT.read_text().replace("/home/agent", str(self.home))
                               .replace("/opt/workcell-context-lib.sh", str(self.context_lib))
                               .replace("/opt/pi", str(self.template)))
        self.env = os.environ.copy()
        for key in ["BASH_ENV", "PI_CODING_AGENT_DIR", "PI_MANAGED_INSTALL_ROOT", "PI_TEST_PACKAGE_ROOT", "NPM_CONFIG_CACHE"]:
            self.env.pop(key, None)
        self.env["HOME"] = str(self.home)

    def write_executable(self, path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def make_release(self, root: Path, version: str):
        release = root / "install" / "releases" / version
        package = release / "node_modules" / "@earendil-works" / "pi-coding-agent"
        self.write_executable(package / "cli.sh", f'''#!/bin/sh
if [ "${{1:-}}" = "--managed-root" ]; then printf '%s\\n' "$PI_MANAGED_INSTALL_ROOT";
else printf '%s\\n' '{version}'; fi
''')
        (package / "package.json").write_text(json.dumps({"name": "@earendil-works/pi-coding-agent", "version": version}))
        binary = release / "node_modules" / ".bin" / "pi"
        binary.parent.mkdir()
        binary.symlink_to("../@earendil-works/pi-coding-agent/cli.sh")
        return binary

    def make_install(self, root: Path, version: str):
        self.make_release(root, version)
        (root / "install" / "managed-install.json").write_text(json.dumps(self.marker))
        (root / "install" / "current-version").write_text(version + "\n")
        self.write_executable(root / "bin" / "pi", LAUNCHER)

    def run_init(self, after='', env=None):
        result = subprocess.run(
            ["bash", "-ec", '. "$1"; ' + (after or '"$2" --version'), "_", str(self.script), str(self.entrypoint)],
            env=env or self.env, text=True, capture_output=True, timeout=15, check=False,
        )
        for path, original in self.original_state.items():
            self.assertEqual(path.read_bytes(), original, str(path))
        self.assertEqual(list(self.agent.glob(".pi-install.*")), [])
        self.assertEqual(list((self.agent / "bin").glob(".pi-launcher.*")), [])
        return result

    def assert_success(self, result, version):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], version)
        self.assertEqual(self.entrypoint.readlink(), self.launcher)
        self.assertEqual((self.home / ".pi").readlink(), self.home / "persist" / ".pi")

    def assert_failure(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)

    def test_fresh_seed_preserves_user_state_and_ignores_legacy_prefix(self):
        marker_bytes = (self.template / "install" / "managed-install.json").read_bytes()
        self.assert_success(self.run_init(), "1.0.3")
        self.assertEqual((self.install / "managed-install.json").read_bytes(), marker_bytes)
        self.assertEqual(self.launcher.read_text(), LAUNCHER)
        self.assertTrue(self.launcher.stat().st_mode & 0o111)
        ownership = self.chown_log.read_text()
        self.assertIn("-R agent:agent", ownership)
        self.assertIn(f"agent:agent {self.agent} {self.agent / 'bin'}", ownership)
        for path in self.original_state:
            self.assertNotIn(str(path), ownership)
        result = self.run_init('"$2" --managed-root')
        self.assert_success(result, str(self.install))

    def test_existing_selector_survives_fresh_home_and_changed_image(self):
        self.make_install(self.agent, "1.0.4")
        self.make_release(self.agent, "9.0.0")
        original_selector = (self.install / "current-version").read_bytes()
        original_marker = (self.install / "managed-install.json").read_bytes()
        for image_version in ["1.0.2", "2.0.0"]:
            with self.subTest(image_version=image_version):
                self.make_release(self.template, image_version)
                (self.template / "install" / "current-version").write_text(image_version + "\n")
                (self.home / ".pi").unlink(missing_ok=True)
                self.entrypoint.unlink(missing_ok=True)
                self.assert_success(self.run_init(), "1.0.4")
                self.assertEqual((self.install / "current-version").read_bytes(), original_selector)
                self.assertEqual((self.install / "managed-install.json").read_bytes(), original_marker)

    def test_missing_or_nonexecutable_launcher_is_restored_without_reseeding(self):
        self.make_install(self.agent, "1.0.4")
        for missing in [True, False]:
            with self.subTest(missing=missing):
                self.launcher.unlink()
                if not missing:
                    self.launcher.write_text("nonexecutable old launcher")
                self.assert_success(self.run_init(), "1.0.4")
                self.assertEqual(self.launcher.read_text(), LAUNCHER)

    def test_launcher_restore_failure_preserves_selected_install(self):
        self.make_install(self.agent, "1.0.4")
        self.launcher.unlink()
        self.context_lib.write_text(self.context_lib.read_text() + 'cp() { return 1; }\n')
        self.assertNotEqual(self.run_init().returncode, 0)
        self.assertFalse(self.launcher.exists())
        self.assertEqual((self.install / "current-version").read_text(), "1.0.4\n")
        (self.template / "bin" / "pi").unlink()
        self.assert_failure(self.run_init(), "no managed Pi template launcher")
        self.assertEqual((self.install / "current-version").read_text(), "1.0.4\n")

    def test_existing_executable_launcher_and_install_need_no_template(self):
        self.make_install(self.agent, "1.0.4")
        self.launcher.write_text(LAUNCHER + "# retained launcher\n")
        original = self.launcher.read_bytes()
        shutil.rmtree(self.template)
        self.assert_success(self.run_init(), "1.0.4")
        self.assertEqual(self.launcher.read_bytes(), original)

    def test_invalid_existing_marker_does_not_reseed(self):
        self.make_install(self.agent, "1.0.4")
        path = self.install / "managed-install.json"
        invalid = ["not json", "null", json.dumps({**self.marker, "layout": "unknown"}),
                   json.dumps({**self.marker, "schemaVersion": True}),
                   json.dumps({**self.marker, "entrypoint": {"type": "symlink", "path": "/wrong/pi"}})]
        for content in invalid:
            with self.subTest(content=content):
                path.write_text(content)
                self.assert_failure(self.run_init(), "invalid managed Pi install")
                self.assertEqual(path.read_text(), content)
                self.assertEqual((self.install / "current-version").read_text(), "1.0.4\n")
        path.unlink()
        self.assert_failure(self.run_init(), "invalid managed Pi install")
        self.assertFalse(path.exists())

    def test_invalid_existing_selector_does_not_reseed(self):
        self.make_install(self.agent, "1.0.4")
        path = self.install / "current-version"
        for content in ["", ".\n", "..\n", "../../bad\n", "1.0.4 \n", "1.0.4\n\n", "1.0.4\r\n", "1.0.4"]:
            with self.subTest(content=content):
                path.write_text(content)
                self.assert_failure(self.run_init(), "current-version")
                self.assertEqual(path.read_bytes(), content.encode())
        path.unlink()
        self.assert_failure(self.run_init(), "invalid managed Pi install")
        self.assertFalse(path.exists())

    def test_missing_or_nonexecutable_selected_binary_does_not_reseed(self):
        self.make_install(self.agent, "1.0.4")
        binary = self.install / "releases" / "1.0.4" / "node_modules" / ".bin" / "pi"
        binary.resolve().chmod(0o644)
        self.assert_failure(self.run_init(), "invalid managed Pi install")
        binary.unlink()
        self.assert_failure(self.run_init(), "invalid managed Pi install")
        self.assertEqual((self.install / "current-version").read_text(), "1.0.4\n")

    def test_selected_executable_outside_release_is_rejected(self):
        self.make_install(self.agent, "1.0.4")
        binary = self.install / "releases" / "1.0.4" / "node_modules" / ".bin" / "pi"
        external = self.root / "external-pi"
        self.write_executable(external, "#!/bin/sh\nprintf 'external\\n'\n")
        binary.unlink()
        binary.symlink_to(external)
        self.assert_failure(self.run_init(), "selected executable must stay inside its managed release")
        self.assertEqual(binary.readlink(), external)

    def test_symlink_install_and_bin_roots_are_rejected(self):
        self.make_install(self.agent, "1.0.4")
        original = self.install / "current-version"
        external = self.root / "external-install"
        self.install.rename(external)
        self.install.symlink_to(external, target_is_directory=True)
        self.assert_failure(self.run_init(), "install root must be a directory")
        self.assertEqual(original.read_text(), "1.0.4\n")
        self.install.unlink()
        external.rename(self.install)
        bin_dir = self.agent / "bin"
        external_bin = self.root / "external-bin"
        bin_dir.rename(external_bin)
        bin_dir.symlink_to(external_bin, target_is_directory=True)
        self.assert_failure(self.run_init(), "bin directory must not be a symlink")
        self.assertEqual((external_bin / "pi").read_text(), LAUNCHER)

    def test_missing_template_or_invalid_seed_publishes_nothing(self):
        (self.template / "bin" / "pi").unlink()
        self.assert_failure(self.run_init(), "no complete managed Pi template")
        self.assertFalse(self.install.exists())
        self.write_executable(self.template / "bin" / "pi", LAUNCHER)
        (self.template / "install" / "current-version").write_text("../../bad\n")
        self.assert_failure(self.run_init(), "invalid managed Pi install")
        self.assertFalse(self.install.exists())
        shutil.rmtree(self.template)
        self.assert_failure(self.run_init(), "no complete managed Pi template")
        self.assertFalse(self.install.exists())

    def test_failed_seed_copy_or_ownership_publishes_nothing(self):
        original = self.context_lib.read_text()
        for function in ['cp() { mkdir -p "$3"; touch "$3/partial"; return 1; }', 'chown() { return 1; }']:
            with self.subTest(function=function):
                self.context_lib.write_text(original + function + "\n")
                result = self.run_init()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.install.exists())

    def test_competing_seed_is_not_overwritten_or_nested(self):
        competitor = self.root / "competitor"
        self.make_install(competitor, "1.0.4")
        self.context_lib.write_text(self.context_lib.read_text() + f'''
mv() {{
  cp -a "{competitor}/install" "{self.install}" || return 1
  command mv "$@"
}}
''')
        self.assert_failure(self.run_init(), "another initializer published")
        self.assertEqual((self.install / "current-version").read_text(), "1.0.4\n")
        self.assertFalse((self.install / "install").exists())

    def test_config_override_does_not_relocate_install_and_parent_traps_survive(self):
        env = {**self.env, "PI_CODING_AGENT_DIR": str(self.root / "custom-config")}
        # Install a parent EXIT trap before sourcing; seed/launcher cleanup must stay scoped.
        self.script.write_text("trap ':' EXIT\npi_parent_trap=$(trap -p EXIT)\n" + self.script.read_text())
        result = self.run_init('test "$(trap -p EXIT)" = "$pi_parent_trap"; printf "%s\\n" "$PI_CODING_AGENT_DIR"', env)
        self.assert_success(result, env["PI_CODING_AGENT_DIR"])
        self.assertTrue(self.install.is_dir())
        self.assertFalse((self.root / "custom-config").exists())

    def test_startup_never_invokes_installer_npm_or_curl(self):
        self.context_lib.write_text(self.context_lib.read_text() +
                                    'npm() { echo "unexpected npm" >&2; return 1; }\n'
                                    'curl() { echo "unexpected curl" >&2; return 1; }\n'
                                    'sh() { echo "unexpected installer" >&2; return 1; }\n')
        self.assert_success(self.run_init(), "1.0.3")

    def run_image_install(self, existing_pi=False, invalid_marker=False):
        if not existing_pi:
            self.entrypoint.unlink()
        if invalid_marker:
            (self.template / "install" / "managed-install.json").write_text("{}")
        build_root = self.root / "build-template"
        build_root.mkdir()
        cache = self.root / "npm-cache"
        cache.mkdir(exist_ok=True)
        installer = self.root / "installer.sh"
        installer.write_text(f'''#!/bin/sh
set -eu
test "$PI_CODING_AGENT_DIR" = "{build_root}"
test "$NPM_CONFIG_CACHE" = "{cache}"
test "$PI_OFFLINE:$PI_TELEMETRY:$TERM" = "1:0:dumb"
cp -a "{self.template}/install" "{self.template}/bin" "$PI_CODING_AGENT_DIR/"
ln -sfn "$PI_CODING_AGENT_DIR/bin/pi" "{self.entrypoint}"
''')
        tools = self.root / "tools"
        curl_log = self.root / "curl.log"
        self.write_executable(tools / "curl", f'''#!/bin/sh
printf 'called\\n' >> "{curl_log}"
for output in "$@"; do :; done
cp "{installer}" "$output"
''')
        run = DOCKERFILE.read_text().split("RUN ! command -v pi", 1)[1].split("\n\nUSER root", 1)[0]
        run = ("! command -v pi" + run).replace("\\\n", "").replace("/opt/pi-template", str(build_root))
        run = run.replace("/home/agent", str(self.home)).replace("/tmp/pi-install.sh", str(self.root / "download.sh"))
        run = run.replace("/tmp/pi-npm-cache", str(cache))
        # Isolate PATH from a maintainer's globally installed Pi/npm commands.
        for name in ["node", "sh", "cp", "ln", "rm", "dirname", "readlink"]:
            (tools / name).unlink(missing_ok=True)
            (tools / name).symlink_to(shutil.which(name))
        self.write_executable(tools / "npm", "#!/bin/sh\nexit 99\n")
        env = {**self.env, "PATH": f"{tools}:{self.entrypoint.parent}"}
        run = run.rstrip() + ' || exit 1\ntest -z "${PI_CODING_AGENT_DIR+x}"; test -z "${NPM_CONFIG_CACHE+x}"\n'
        result = subprocess.run(["sh", "-ec", run], env=env, text=True, capture_output=True, timeout=15, check=False)
        return result, build_root, cache, curl_log

    def test_image_installer_run_checks_contract_and_removes_temporary_files(self):
        result, root, cache, curl_log = self.run_image_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Verified managed Pi 1.0.3", result.stdout)
        self.assertEqual(curl_log.read_text(), "called\n")
        self.assertTrue((root / "install" / "releases" / "1.0.3").is_dir())
        self.assertFalse(cache.exists())
        self.assertFalse((self.root / "download.sh").exists())

    def test_image_existing_pi_or_invalid_output_fails_closed(self):
        result, _, _, curl_log = self.run_image_install(existing_pi=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(curl_log.exists())
        shutil.rmtree(self.root / "build-template")
        result, _, _, _ = self.run_image_install(invalid_marker=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AssertionError", result.stderr)


if __name__ == "__main__":
    unittest.main()
