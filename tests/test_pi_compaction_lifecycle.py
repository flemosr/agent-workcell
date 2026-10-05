"""Offline tests against an installed Pi SDK; no user credentials or model HTTP calls."""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "fixtures" / "run_pi_compaction_lifecycle.mjs"
EXTENSION = REPO_ROOT / "sandbox" / "pi-extensions" / "compact-session.ts"
NOTIFICATIONS = REPO_ROOT / "sandbox" / "pi-extensions" / "terminal-notify.ts"

CASES = [
    "native-success", "notification-first", "notifications-absent", "non-tty-notifications",
    "autonomous-successive-slices", "immediate-loop-rejected",
    "tui-steering-ordinary", "tui-steering-synchronous", "tui-steering-delayed",
    "tui-followup-ordinary", "tui-followup-delayed", "tui-multiple-mixed",
    "tui-multiple-mixed-delayed", "preexisting-steering", "preexisting-followup", "preexisting-mixed",
    "native-provider-failure", "native-hook-cancel", "native-hook-summary", "manual-compaction-unowned",
    "native-api-abort", "native-small-session",
    "changed-acknowledgement", "standalone-mixed-rejected", "standalone-duplicate-rejected",
    "empty-prompt-rejected", "stale-branch-callback", "sdk-direct-disposal",
    "escape-accepted", "escape-waiting-idle", "escape-summary", "escape-persisted",
    "escape-handoff", "escape-resumed", "escape-native-queue-restoration",
    "escape-autocomplete", "escape-editor-shortcut", "escape-remapped", "escape-remapped-away",
    "escape-kitty", "escape-ordinary-data-and-release", "escape-delegating-editor",
    "escape-listener-before", "escape-listener-after", "escape-earlier-consumer-limit",
    "inactive-print", "inactive-json", "inactive-rpc", "inactive-print-after-reload",
    "excluded-tool", "excluded-tool-after-reload", "explicit-tools-preserved",
    "no-tools-preserved", "runtime-new", "runtime-fork", "runtime-switch", "runtime-reload",
    "runtime-tree", "runtime-shutdown",
]


def _managed_pi_package_root(install):
    """Resolve the launcher's selected release; corrupt managed state must not skip tests."""
    try:
        root = install.resolve(strict=True)
        marker = json.loads((root / "managed-install.json").read_text())
        if (not isinstance(marker, dict) or marker.get("kind") != "pi-managed-install"
                or type(marker.get("schemaVersion")) is not int or marker["schemaVersion"] != 1
                or marker.get("layout") != "releases-v1"):
            raise ValueError("managed-install.json must identify schema 1, releases-v1")
        selector = (root / "current-version").read_bytes().decode("utf-8")
        version = selector.removesuffix("\n")
        if (not selector.endswith("\n") or version in {".", ".."}
                or not re.fullmatch(r"[0-9A-Za-z._+-]+", version)):
            raise ValueError("current-version must contain one safe release name followed by a newline")
        releases = root / "releases"
        release = (releases / version).resolve(strict=True)
        if not release.is_relative_to(releases):
            raise ValueError("selected release resolves outside the managed releases directory")
        package = (release / "node_modules" / "@earendil-works" / "pi-coding-agent").resolve(strict=True)
        if not package.is_relative_to(release):
            raise ValueError("selected package resolves outside its managed release")
        manifest = json.loads((package / "package.json").read_text())
        if not isinstance(manifest, dict) or manifest.get("name") != "@earendil-works/pi-coding-agent":
            raise ValueError("selected package.json must identify @earendil-works/pi-coding-agent")
        return package
    except (OSError, ValueError, RuntimeError) as error:
        raise AssertionError(f"Invalid managed Pi installation at {install}: {error}") from error


def pi_package_root():
    """Discover an explicit SDK, the selected managed release, or an ordinary executable package."""
    explicit = os.environ.get("PI_TEST_PACKAGE_ROOT")
    candidates = [Path(explicit).expanduser().resolve()] if explicit else []
    if not explicit:
        executable = shutil.which("pi")
        if executable:
            launcher = Path(executable).resolve()
            install = launcher.parent.parent / "install"
            if launcher.parent.name == "bin" and (install.exists() or install.is_symlink()):
                return _managed_pi_package_root(install)
            candidates = list(launcher.parents)
    for path in candidates:
        manifest = path / "package.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text())
                if isinstance(data, dict) and data.get("name") == "@earendil-works/pi-coding-agent":
                    return path
            except (OSError, ValueError):
                continue
    if explicit:
        raise AssertionError("PI_TEST_PACKAGE_ROOT must point to an installed @earendil-works/pi-coding-agent package")
    return None


class PiCompactionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = pi_package_root()
        if package is None:
            raise unittest.SkipTest("Pi SDK unavailable; install Pi or set PI_TEST_PACKAGE_ROOT to run required lifecycle coverage")
        result = subprocess.run(
            ["node", "--experimental-import-meta-resolve", str(RUNNER), str(package), str(EXTENSION), str(NOTIFICATIONS)],
            cwd=REPO_ROOT, text=True, capture_output=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if not payload["passed"]:
            raise AssertionError(payload)
        cls.package_version = payload["packageVersion"]
        cls.reports = {report["name"]: report for report in payload["reports"]}
        if set(cls.reports) != set(CASES):
            raise AssertionError("Lifecycle runner/Python scenario inventory mismatch")


def lifecycle_case(case):
    def test(self):
        self.assertTrue(self.reports[case]["passed"], self.reports[case])
    return test


for case in CASES:
    setattr(PiCompactionLifecycleTests, f"test_{case.replace('-', '_')}", lifecycle_case(case))


if __name__ == "__main__":
    unittest.main()
