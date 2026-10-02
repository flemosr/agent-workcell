import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = REPO_ROOT / "sandbox" / "agent-init" / "codex.sh"


class CodexInitTests(unittest.TestCase):
    def test_native_updated_release_starts_with_fresh_home(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            codex_home = home / "persist" / ".codex"
            standalone = codex_home / "packages" / "standalone"
            release = standalone / "releases" / "0.160.0-aarch64-unknown-linux-musl"
            binary = release / "bin" / "codex"
            binary.parent.mkdir(parents=True)
            binary.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'codex-cli 0.160.0'\n",
                encoding="utf-8",
            )
            binary.chmod(0o755)
            (release / "codex").symlink_to("bin/codex")

            # The native updater selects an absolute path through the home alias.
            selected_path = (
                home / ".codex" / "packages" / "standalone" / "releases" / release.name
            )
            selector = standalone / "current"
            selector.symlink_to(selected_path)
            self.assertFalse((home / ".codex").exists())
            self.assertFalse(selector.exists())

            config = codex_home / "config.toml"
            auth = codex_home / "auth.json"
            config.write_text("# persisted configuration\n", encoding="utf-8")
            auth.write_text('{"fixture": true}\n', encoding="utf-8")
            original_state = {
                path: path.read_bytes() for path in (config, auth, binary)
            }

            # A valid older image seed must not replace the updated selection.
            template = root / "template" / "packages" / "standalone"
            template_release = template / "releases" / "image-seed"
            template_release.mkdir(parents=True)
            template_binary = template_release / "codex"
            template_binary.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'codex-cli 0.144.5'\n",
                encoding="utf-8",
            )
            template_binary.chmod(0o755)
            (template / "current").symlink_to("releases/image-seed")

            # Context management and root ownership are unrelated to selection.
            context_lib = root / "context-lib.sh"
            context_lib.write_text(
                "wc_prepare_all() { :; }\n"
                "wc_chown_persisted_context() { :; }\n"
                "wc_chown_persisted_skills() { :; }\n"
                "chown() { :; }\n",
                encoding="utf-8",
            )
            script = root / "codex-init.sh"
            script.write_text(
                INIT_SCRIPT.read_text(encoding="utf-8")
                .replace("/home/agent", str(home))
                .replace("/opt/workcell-context-lib.sh", str(context_lib))
                .replace("/opt/codex-template", str(root / "template")),
                encoding="utf-8",
            )
            launcher = home / ".local" / "bin" / "codex"
            result = subprocess.run(
                [
                    "bash", "-ec", '. "$1"; "$2" --version',
                    "_", str(script), str(launcher),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "codex-cli 0.160.0")
            self.assertEqual(launcher.resolve(), binary)
            self.assertEqual(selector.readlink(), selected_path)
            for path, original_bytes in original_state.items():
                self.assertEqual(path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
