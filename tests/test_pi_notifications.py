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
        steps=None,
        has_pending_messages=False,
    ):
        scenario = {
            "mode": mode,
            "isTTY": is_tty,
            "isIdle": is_idle,
            "invocations": invocations,
            "hasPendingMessages": has_pending_messages,
        }
        if steps is not None:
            scenario["steps"] = steps
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

    def test_registers_settlement_and_session_lifecycle_handlers(self):
        result = self.run_extension(invocations=0)

        self.assertEqual(result["registeredEvents"], ["session_start", "session_shutdown", "agent_settled"])
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

    @staticmethod
    def activity(active, *, request="request-1", session="session-1", outcome=None, ready=False):
        return {"kind": "activity", "state": {
            "sessionId": session, "requestId": request, "active": active,
            "outcome": outcome, "ready": ready,
        }}

    def test_suppresses_intermediate_compaction_settlement(self):
        result = self.run_extension(steps=[self.activity(True), {"kind": "settled"}])
        self.assertEqual(result["writes"], [])

    def test_success_waits_for_resumed_settlement(self):
        result = self.run_extension(steps=[
            self.activity(True), {"kind": "settled"},
            self.activity(False, outcome="resumed"), {"kind": "settled"},
        ])
        self.assertEqual(result["writes"], [NOTIFICATION])

    def test_terminal_failure_or_cancel_notifies_once_without_later_settlement(self):
        for outcome in ["failed", "canceled"]:
            with self.subTest(outcome=outcome):
                terminal = self.activity(False, outcome=outcome, ready=True)
                result = self.run_extension(steps=[self.activity(True), {"kind": "settled"}, terminal, terminal])
                self.assertEqual(result["writes"], [NOTIFICATION])

    def test_invalidation_does_not_notify(self):
        result = self.run_extension(steps=[
            self.activity(True), {"kind": "settled"},
            self.activity(False, outcome="invalidated", ready=True),
        ])
        self.assertEqual(result["writes"], [])

    def test_ignores_other_sessions_and_stale_request_outcomes(self):
        result = self.run_extension(steps=[
            self.activity(True, session="other"), {"kind": "settled"},
            self.activity(True, request="new"),
            self.activity(False, request="old", outcome="failed", ready=True),
            {"kind": "settled"},
            self.activity(False, request="new", outcome="resumed"), {"kind": "settled"},
        ])
        self.assertEqual(result["writes"], [NOTIFICATION, NOTIFICATION])

    def test_terminal_outcome_preserves_mode_tty_idle_and_pending_checks(self):
        steps = [self.activity(True), self.activity(False, outcome="failed", ready=True)]
        for overrides in [
            {"mode": "print"}, {"is_tty": False}, {"is_idle": False},
            {"has_pending_messages": True},
        ]:
            with self.subTest(overrides=overrides):
                result = self.run_extension(steps=steps, **overrides)
                self.assertEqual(result["writes"], [])

    def test_reset_and_idempotent_cleanup(self):
        result = self.run_extension(steps=[
            self.activity(True), {"kind": "start", "sessionId": "session-2"},
            self.activity(False, outcome="failed", ready=True), {"kind": "settled"},
            {"kind": "shutdown"}, {"kind": "shutdown"},
        ])
        self.assertEqual(result["writes"], [NOTIFICATION])
        self.assertEqual(result["listeners"], 0)


if __name__ == "__main__":
    unittest.main()
