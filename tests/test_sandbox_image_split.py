import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SandboxImageSplitTests(unittest.TestCase):
    def read_repo_file(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_flutter_wrappers_default_to_image_owned_sdk(self):
        flutter_wrapper = self.read_repo_file("sandbox/flutter-tools/flutter.sh")
        dart_wrapper = self.read_repo_file("sandbox/flutter-tools/dart.sh")
        guard = self.read_repo_file("sandbox/flutter-tools/package_config_guard.py")

        self.assertIn("/opt/flutter-sdk/bin/flutter", flutter_wrapper)
        self.assertIn("/opt/flutter-sdk/bin/flutter", dart_wrapper)
        self.assertIn("/opt/flutter-sdk/bin/dart", dart_wrapper)
        self.assertIn("/opt/flutter-sdk/bin/flutter", guard)
        self.assertNotIn("/home/agent/persist/.flutter-sdk", flutter_wrapper)
        self.assertNotIn("/home/agent/persist/.flutter-sdk", dart_wrapper)
        self.assertNotIn("/home/agent/persist/.flutter-sdk", guard)

    def test_entrypoint_uses_image_owned_agent_binaries(self):
        entrypoint = self.read_repo_file("sandbox/entrypoint.sh")

        self.assertIn('claude_versions_root="/opt/claude-code"', entrypoint)
        self.assertIn('opencode_root="/opt/opencode"', entrypoint)
        self.assertIn('flutter_sdk_root="/opt/flutter-sdk"', entrypoint)
        self.assertIn('ln -sfn "$opencode_root" /home/agent/.opencode', entrypoint)
        self.assertIn('ln -sfn "$flutter_sdk_root" /home/agent/.flutter-sdk', entrypoint)
        self.assertIn("ln -sfn /opt/pub-cache-template/bin/protoc-gen-dart", entrypoint)
        self.assertNotIn("cp -a --no-target-directory /opt/flutter-sdk", entrypoint)
        self.assertNotIn("ln -sfn /home/agent/persist/.opencode /home/agent/.opencode", entrypoint)
        self.assertNotIn("ln -sfn /home/agent/persist/.claude-versions", entrypoint)

    def test_dockerfile_declares_stable_image_owned_aliases(self):
        dockerfile = self.read_repo_file("sandbox/Dockerfile")

        self.assertIn("ln -sfn /opt/flutter-sdk-template /opt/flutter-sdk", dockerfile)
        self.assertIn("ln -sfn /opt/opencode-template /opt/opencode", dockerfile)
        self.assertIn("ln -sfn /opt/claude-versions-template /opt/claude-code", dockerfile)
        self.assertIn("ln -sfn /opt/pub-cache-template/bin/protoc-gen-dart", dockerfile)
        self.assertIn("/opt/flutter-sdk/bin:/home/agent/.nvm/current/bin", dockerfile)

    def test_local_wrapper_copies_do_not_invalidate_agent_installs(self):
        dockerfile = self.read_repo_file("sandbox/Dockerfile")

        wrapper_copy_index = dockerfile.index("COPY --chown=agent:agent flutter-tools/")
        self.assertLess(dockerfile.index("https://opencode.ai/install"), wrapper_copy_index)
        self.assertLess(dockerfile.index("api.github.com/repos/openai/codex"), wrapper_copy_index)


if __name__ == "__main__":
    unittest.main()
