import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "sandbox" / "pi-extensions" / "compact-session-runtime.ts"
RUNNER = REPO_ROOT / "tests" / "fixtures" / "run_pi_compaction_extension.mjs"

CASES = [
    "success", "queued", "empty-optional", "pending-duplicate", "unrelated-turn",
    "reentrant", "late-old-callback", "synchronous-throw", "send-throw",
    "invalid-empty", "invalid-whitespace", "invalid-type", "invalid-focus",
    "invalid-mixed", "invalid-duplicate", "invalid-origin", "invalid-replay", "invalid-name",
    "invalid-mode", "invalid-session", "invalid-aborted",
    "loop-immediate", "loop-failed-work", "loop-user", "loop-work",
    "changed-result", "failed-result", "missing-result", "wrong-source",
    "cancel-accepted", "cancel-summary", "cancel-handoff", "native-abort",
    "branch-before", "branch-after", "shared-prefix-branch", "session-after", "invalidate",
    "start-no-abort", "tree-no-abort", "stale", "disposed-bus", "failure",
]


class PiCompactionControllerTests(unittest.TestCase):
    def run_case(self, case):
        result = subprocess.run(
            ["node", "--experimental-strip-types", str(RUNNER), str(RUNTIME), case],
            cwd=REPO_ROOT, text=True, capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])


def controller_case(case):
    def test(self):
        self.run_case(case)
    return test


for case in CASES:
    setattr(PiCompactionControllerTests, f"test_{case.replace('-', '_')}", controller_case(case))


if __name__ == "__main__":
    unittest.main()
