"""Real Pi SDK context snapshots and tool execution; no network or user resources."""
import json
import subprocess
import unittest
from pathlib import Path

from test_pi_compaction_lifecycle import pi_package_root

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "fixtures" / "run_pi_context_usage.mjs"
EXTENSION = REPO_ROOT / "sandbox" / "pi-extensions" / "context-usage.ts"
CASES = [
    "roundtrip", "empty-zero", "heuristic-trailing", "post-compaction",
    "unavailable-limit", "fractional-over-window", "active-branch", "virtual-selection",
    "invalid-inputs", "nested-access", "mode-tui", "mode-print", "mode-json", "mode-rpc",
    "default-availability", "allowlist", "allowlist-omits", "exclude-getter", "no-tools",
    "no-builtin-tools",
]


class PiContextUsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = pi_package_root()
        if package is None:
            raise unittest.SkipTest("Pi SDK unavailable; install Pi or set PI_TEST_PACKAGE_ROOT")
        result = subprocess.run(
            ["node", "--experimental-import-meta-resolve", str(RUNNER), str(package), str(EXTENSION)],
            cwd=REPO_ROOT, text=True, capture_output=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        cls.reports = {report["name"]: report for report in payload["reports"]}
        if not payload["passed"] or set(cls.reports) != set(CASES):
            raise AssertionError(payload)


def sdk_case(case):
    def test(self):
        self.assertTrue(self.reports[case]["passed"], self.reports[case])
    return test


for case in CASES:
    setattr(PiContextUsageTests, f"test_{case.replace('-', '_')}", sdk_case(case))


if __name__ == "__main__":
    unittest.main()
