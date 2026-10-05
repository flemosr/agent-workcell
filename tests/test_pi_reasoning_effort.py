"""Real Pi SDK coverage; only model responses are scripted, with no network or user credentials."""
import json
import subprocess
import unittest
from pathlib import Path

from test_pi_compaction_lifecycle import pi_package_root

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "fixtures" / "run_pi_reasoning_effort.mjs"
EXTENSION = REPO_ROOT / "sandbox" / "pi-extensions" / "reasoning-effort.ts"
CASES = [
    "roundtrip", "filtered-levels", "non-reasoning", "invalid-inputs", "canceled",
    "native-alias-state", "sequential-batch", "virtual-selection",
    "mode-tui", "mode-json", "mode-rpc",
    "allowlist", "exclude-setter", "exclude-both", "no-tools",
]


class PiReasoningEffortTests(unittest.TestCase):
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
    setattr(PiReasoningEffortTests, f"test_{case.replace('-', '_')}", sdk_case(case))


if __name__ == "__main__":
    unittest.main()
