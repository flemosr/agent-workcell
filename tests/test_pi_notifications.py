import base64
import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = REPO_ROOT / "sandbox" / "pi-extensions" / "terminal-notify.ts"
RUNNER = REPO_ROOT / "tests" / "fixtures" / "run_pi_notification_extension.mjs"
NOTIFICATION = b"\x1b]777;notify;Pi;Ready for input\x07"


class PiNotificationExtensionTests(unittest.TestCase):
    def run_extension(
        self,
        *,
        mode="tui",
        is_tty=True,
        is_idle=True,
        invocations=1,
    ):
        scenario = {
            "mode": mode,
            "isTTY": is_tty,
            "isIdle": is_idle,
            "invocations": invocations,
        }
        result = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                str(RUNNER),
                str(EXTENSION),
                json.dumps(scenario),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        payload["writes"] = [
            base64.b64decode(write) for write in payload["writes"]
        ]
        return payload

    def test_registers_only_settled_handler(self):
        result = self.run_extension(invocations=0)

        self.assertEqual(result["registeredEvents"], ["agent_settled"])
        self.assertEqual(result["writes"], [])

    def test_emits_exact_notification_once_per_settled_event(self):
        result = self.run_extension(invocations=3)

        self.assertEqual(result["writes"], [NOTIFICATION, NOTIFICATION, NOTIFICATION])

    def test_does_not_emit_outside_tui_mode(self):
        for mode in ["print", "json", "rpc", None, "unknown"]:
            with self.subTest(mode=mode):
                result = self.run_extension(mode=mode)
                self.assertEqual(result["writes"], [])

    def test_does_not_emit_without_tty_stdout(self):
        for is_tty in [False, None]:
            with self.subTest(is_tty=is_tty):
                result = self.run_extension(is_tty=is_tty)
                self.assertEqual(result["writes"], [])

    def test_does_not_emit_while_agent_is_not_idle(self):
        result = self.run_extension(is_idle=False)

        self.assertEqual(result["writes"], [])


if __name__ == "__main__":
    unittest.main()
