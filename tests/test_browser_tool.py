import importlib.util
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
BROWSER_TOOL = REPO_ROOT / "sandbox" / "browser-tools" / "browser.py"


def load_browser_module():
    spec = importlib.util.spec_from_file_location("browser_tool", BROWSER_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BrowserToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_browser_module()

    def test_get_ws_url_uses_localhost_host_header_for_version_request(self):
        browser = self.module.Browser.host(cdp_url="http://host.docker.internal:9222")

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"webSocketDebuggerUrl":"ws://localhost/devtools/browser/test-id"}'

        captured_requests = []

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            self.assertEqual(timeout, 10)
            return FakeResponse()

        with mock.patch.object(self.module.urllib.request, "urlopen", side_effect=fake_urlopen):
            ws_url = browser._get_ws_url()

        self.assertEqual(ws_url, "ws://host.docker.internal:9222/devtools/browser/test-id")
        self.assertEqual(captured_requests[0].get_header("Host"), "localhost")

    async def test_host_connect_passes_localhost_host_header_to_cdp_websocket(self):
        browser = self.module.Browser.host(cdp_url="http://host.docker.internal:9222")
        browser._get_ws_url = mock.Mock(return_value="ws://host.docker.internal:9222/devtools/browser/test-id")

        class FakePage:
            def on(self, event, callback):
                pass

        class FakeContext:
            pages = [FakePage()]

        class FakeBrowser:
            contexts = [FakeContext()]

        fake_chromium = mock.AsyncMock()
        fake_chromium.connect_over_cdp.return_value = FakeBrowser()
        fake_playwright = mock.Mock(chromium=fake_chromium)

        class FakePlaywrightStarter:
            async def start(self):
                return fake_playwright

        with mock.patch.object(self.module, "async_playwright", return_value=FakePlaywrightStarter()):
            await browser.connect()

        fake_chromium.connect_over_cdp.assert_awaited_once_with(
            "ws://host.docker.internal:9222/devtools/browser/test-id",
            headers={"Host": "localhost"},
        )

    async def test_sandbox_connect_starts_local_headless_browser_before_cdp_connection(self):
        browser = self.module.Browser.sandbox()
        browser._get_ws_url = mock.Mock(return_value="ws://127.0.0.1:19223/devtools/browser/test-id")

        class FakePage:
            def on(self, event, callback):
                pass

        class FakeContext:
            pages = [FakePage()]

        class FakeBrowser:
            contexts = [FakeContext()]

        fake_chromium = mock.AsyncMock()
        fake_chromium.connect_over_cdp.return_value = FakeBrowser()
        fake_playwright = mock.Mock(chromium=fake_chromium)

        class FakePlaywrightStarter:
            async def start(self):
                return fake_playwright

        fake_manager = mock.Mock()
        fake_manager.ensure_running.return_value = "http://127.0.0.1:19223"

        with (
            mock.patch.object(self.module, "SandboxBrowser", return_value=fake_manager),
            mock.patch.object(self.module, "async_playwright", return_value=FakePlaywrightStarter()),
        ):
            await browser.connect()

        fake_manager.ensure_running.assert_called_once_with()
        self.assertEqual(browser.cdp_url, "http://127.0.0.1:19223")
        fake_chromium.connect_over_cdp.assert_awaited_once_with(
            "ws://127.0.0.1:19223/devtools/browser/test-id",
            headers={"Host": "localhost"},
        )

    def test_sandbox_status_reports_local_cdp_state(self):
        manager = self.module.SandboxBrowser(port=19777)
        with (
            mock.patch.object(manager, "is_running", return_value=True),
            mock.patch.object(manager, "_read_pid", return_value=1234),
            mock.patch.object(manager, "_pid_alive", return_value=True),
            mock.patch.object(manager, "executable", return_value="/usr/bin/chromium"),
        ):
            status = manager.status()

        self.assertEqual(status["cdp_url"], "http://127.0.0.1:19777")
        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], 1234)
        self.assertEqual(status["executable"], "/usr/bin/chromium")


if __name__ == "__main__":
    unittest.main()
