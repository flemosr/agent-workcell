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
        browser = self.module.Browser(cdp_url="http://host.docker.internal:9222")

        class FakeResponse:
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

    async def test_connect_passes_localhost_host_header_to_cdp_websocket(self):
        browser = self.module.Browser(cdp_url="http://host.docker.internal:9222")
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


if __name__ == "__main__":
    unittest.main()
