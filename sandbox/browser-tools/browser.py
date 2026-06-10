#!/usr/bin/env python3
"""
Browser control utility for Agent Workcell.

The CLI requires an explicit browser backend:

    browser sandbox <command>   # sandbox-local headless Chromium
    browser host <command>      # host Chrome via CDP

The Python API defaults to sandbox-local headless Chromium:

    from browser import Browser

    async with Browser.sandbox() as b:
        await b.goto("https://example.com")
        await b.screenshot()
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

# Activate the virtual environment when the module is run outside the wrapper.
venv_path = Path.home() / ".local/python-venv"
if venv_path.exists():
    sys.path.insert(0, str(venv_path / "lib" / "python3.11" / "site-packages"))

from playwright.async_api import async_playwright  # noqa: E402  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from playwright.async_api import Browser as PWBrowser, Page  # noqa: E402  # type: ignore[import-not-found]


WaitUntilType = Literal["commit", "domcontentloaded", "load", "networkidle"]
BrowserMode = Literal["sandbox", "host"]


class SandboxBrowser:
    """Lifecycle manager for the sandbox-local headless Chromium CDP process."""

    DEFAULT_PORT = 19223
    DEFAULT_HOST = "127.0.0.1"
    STATE_DIR = Path.home() / ".cache" / "workcell" / "browser-headless"
    PROFILE_DIR = STATE_DIR / "profile"
    PID_FILE = STATE_DIR / "chromium.pid"
    LOG_FILE = STATE_DIR / "chromium.log"

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or os.environ.get("WORKCELL_BROWSER_SANDBOX_HOST", self.DEFAULT_HOST)
        self.port = port or int(os.environ.get("WORKCELL_BROWSER_SANDBOX_PORT", str(self.DEFAULT_PORT)))
        self.cdp_url = f"http://{self.host}:{self.port}"

    def _version_url(self) -> str:
        return f"{self.cdp_url}/json/version"

    def is_running(self) -> bool:
        """Return true when a CDP endpoint answers on the sandbox browser port."""
        try:
            req = urllib.request.Request(self._version_url(), headers={"Host": "localhost"})
            with urllib.request.urlopen(req, timeout=1) as response:
                return response.status == 200
        except Exception:
            return False

    def _read_pid(self) -> int | None:
        try:
            return int(self.PID_FILE.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _cleanup_stale_pid(self) -> None:
        pid = self._read_pid()
        if pid is not None and not self._pid_alive(pid):
            self.PID_FILE.unlink(missing_ok=True)

    def executable(self) -> str | None:
        """Find the Chromium/Chrome executable for sandbox mode."""
        configured = os.environ.get("WORKCELL_CHROMIUM")
        if configured:
            return configured if Path(configured).exists() else shutil.which(configured)
        for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
            path = shutil.which(candidate)
            if path:
                return path
        return None

    def ensure_running(self) -> str:
        """Start sandbox Chromium when needed and return its CDP URL."""
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_pid()

        if self.is_running():
            return self.cdp_url

        exe = self.executable()
        if not exe:
            raise RuntimeError(
                "Chromium is not installed for sandbox browser mode. "
                "Rebuild the workcell image with the Chromium browser package installed."
            )

        cmd = [
            exe,
            "--headless=new",
            f"--remote-debugging-address={self.host}",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-sandbox",
            "about:blank",
        ]

        with self.LOG_FILE.open("ab") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.PID_FILE.write_text(f"{process.pid}\n")

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.PID_FILE.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Sandbox Chromium exited during startup with code {process.returncode}. "
                    f"See {self.LOG_FILE}"
                )
            if self.is_running():
                return self.cdp_url
            time.sleep(0.2)

        process.terminate()
        self.PID_FILE.unlink(missing_ok=True)
        raise RuntimeError(f"Timed out waiting for sandbox Chromium at {self.cdp_url}. See {self.LOG_FILE}")

    def stop(self) -> bool:
        """Stop the sandbox Chromium process if this tool started it."""
        pid = self._read_pid()
        stopped = False
        if pid is not None and self._pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self._pid_alive(pid):
                time.sleep(0.1)
            if self._pid_alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    os.kill(pid, signal.SIGKILL)
            stopped = True
        self.PID_FILE.unlink(missing_ok=True)
        return stopped

    def status(self) -> dict:
        pid = self._read_pid()
        return {
            "cdp_url": self.cdp_url,
            "running": self.is_running(),
            "pid": pid,
            "pid_alive": self._pid_alive(pid) if pid is not None else False,
            "profile_dir": str(self.PROFILE_DIR),
            "log_file": str(self.LOG_FILE),
            "executable": self.executable(),
        }


class Browser:
    """Browser control via Chrome DevTools Protocol."""

    HOST_CDP_URL = "http://host.docker.internal:9222"
    SANDBOX_CDP_URL = f"http://{SandboxBrowser.DEFAULT_HOST}:{SandboxBrowser.DEFAULT_PORT}"
    DEFAULT_CDP_URL = HOST_CDP_URL  # Backward-compatible constant for callers that referenced it.

    def __init__(self, cdp_url: str | None = None, mode: BrowserMode = "sandbox", auto_start: bool = True):
        self.mode = mode
        if cdp_url is None:
            if mode == "host":
                cdp_url = os.environ.get("CHROME_CDP_URL", self.HOST_CDP_URL)
            else:
                cdp_url = os.environ.get("WORKCELL_BROWSER_SANDBOX_CDP_URL", self.SANDBOX_CDP_URL)
        self.cdp_url = cdp_url
        self.auto_start = auto_start
        self._playwright = None
        self._browser: PWBrowser | None = None
        self._page: Page | None = None
        self._console_messages: list[dict] = []

    @classmethod
    def sandbox(cls, cdp_url: str | None = None, auto_start: bool = True) -> "Browser":
        return cls(cdp_url=cdp_url, mode="sandbox", auto_start=auto_start)

    @classmethod
    def host(cls, cdp_url: str | None = None) -> "Browser":
        return cls(cdp_url=cdp_url, mode="host", auto_start=False)

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Not connected to browser. Call connect() first.")
        return self._page

    def _require_browser(self) -> PWBrowser:
        if self._browser is None:
            raise RuntimeError("Not connected to browser. Call connect() first.")
        return self._browser

    def _cdp_headers(self) -> dict[str, str]:
        host_header = os.environ.get("CHROME_CDP_HOST_HEADER", "localhost")
        return {"Host": host_header}

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    def _get_ws_url(self) -> str | None:
        """Fetch WebSocket URL from Chrome, using localhost Host header to bypass security checks."""
        url = f"{self.cdp_url}/json/version"
        req = urllib.request.Request(url, headers=self._cdp_headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                ws_url = data.get("webSocketDebuggerUrl")
                if ws_url:
                    cdp_parsed = urlparse(self.cdp_url)
                    ws_url = ws_url.replace("ws://localhost", f"ws://{cdp_parsed.hostname}")
                    ws_url = ws_url.replace("ws://127.0.0.1", f"ws://{cdp_parsed.hostname}")
                    if cdp_parsed.port and f":{cdp_parsed.port}" not in ws_url:
                        ws_url = ws_url.replace(
                            f"ws://{cdp_parsed.hostname}/",
                            f"ws://{cdp_parsed.hostname}:{cdp_parsed.port}/",
                        )
                return ws_url
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to Chrome at {self.cdp_url}: {e}") from e

    async def connect(self):
        """Connect to a Chrome-compatible browser via CDP."""
        if self.mode == "sandbox" and self.auto_start:
            self.cdp_url = SandboxBrowser().ensure_running()

        self._playwright = await async_playwright().start()

        ws_url = self._get_ws_url()
        if not ws_url:
            raise ConnectionError("Could not get WebSocket URL from Chrome")

        self._browser = await self._playwright.chromium.connect_over_cdp(
            ws_url,
            headers=self._cdp_headers(),
        )

        browser = self._require_browser()
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context()

        pages = context.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = await context.new_page()

        page = self._require_page()
        page.on("console", lambda msg: self._console_messages.append({
            "type": msg.type,
            "text": msg.text,
            "timestamp": datetime.now().isoformat(),
        }))

        return self

    async def disconnect(self):
        """Disconnect from the CDP browser without stopping the browser process."""
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self) -> Page:
        browser = self._require_browser()
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        self._page = await context.new_page()
        page = self._require_page()
        page.on("console", lambda msg: self._console_messages.append({
            "type": msg.type,
            "text": msg.text,
            "timestamp": datetime.now().isoformat(),
        }))
        return page

    @property
    def page(self) -> Page | None:
        return self._page

    async def goto(self, url: str, wait_until: WaitUntilType = "domcontentloaded") -> dict:
        page = self._require_page()
        await page.goto(url, wait_until=wait_until)
        return {"url": page.url, "title": await page.title()}

    def _default_screenshot_path(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cwd = Path.cwd()
        for parent in (cwd, *cwd.parents):
            if (parent / ".workcell").is_dir():
                out_dir = parent / ".workcell" / "artifacts" / "screenshots"
                out_dir.mkdir(parents=True, exist_ok=True)
                return str(out_dir / f"browser_{timestamp}.png")
        out_dir = cwd / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        return str(out_dir / f"browser_{timestamp}.png")

    async def screenshot(self, path: str | None = None, full_page: bool = False) -> str:
        if path is None:
            path = self._default_screenshot_path()
        page = self._require_page()
        await page.screenshot(path=path, full_page=full_page)
        return path

    async def click(self, selector: str):
        page = self._require_page()
        await page.click(selector)

    async def fill(self, selector: str, text: str):
        page = self._require_page()
        await page.fill(selector, text)

    async def type(self, selector: str, text: str, delay: int = 50):
        page = self._require_page()
        await page.type(selector, text, delay=delay)

    async def press(self, key: str):
        page = self._require_page()
        await page.keyboard.press(key)

    async def wait_for(self, selector: str, timeout: int = 30000):
        page = self._require_page()
        await page.wait_for_selector(selector, timeout=timeout)

    async def get_text(self, selector: str) -> str | None:
        page = self._require_page()
        return await page.text_content(selector)

    async def get_html(self, selector: str = "body") -> str:
        page = self._require_page()
        return await page.inner_html(selector)

    async def evaluate(self, expression: str):
        page = self._require_page()
        return await page.evaluate(expression)

    async def get_console_logs(self, clear: bool = False) -> list:
        logs = self._console_messages.copy()
        if clear:
            self._console_messages.clear()
        return logs

    async def clear_console_logs(self):
        self._console_messages.clear()

    async def get_page_info(self) -> dict:
        page = self._require_page()
        return {
            "url": page.url,
            "title": await page.title(),
            "viewport": page.viewport_size,
        }

    async def scroll(self, x: int = 0, y: int = 0):
        page = self._require_page()
        await page.evaluate(f"window.scrollTo({x}, {y})")

    async def scroll_by(self, x: int = 0, y: int = 0):
        page = self._require_page()
        await page.evaluate(f"window.scrollBy({x}, {y})")

    async def scroll_into_view(self, selector: str):
        page = self._require_page()
        element = await page.wait_for_selector(selector, timeout=5000)
        if element:
            await element.scroll_into_view_if_needed()

    async def scroll_to_bottom(self):
        page = self._require_page()
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    async def get_all_links(self) -> list:
        page = self._require_page()
        return await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({href: a.href, text: a.textContent.trim()}))
        """)

    async def wait_for_network_idle(self, timeout: int = 30000):
        page = self._require_page()
        await page.wait_for_load_state("networkidle", timeout=timeout)


def _add_browser_commands(subparsers: argparse._SubParsersAction) -> None:
    goto_parser = subparsers.add_parser("goto", help="Navigate to URL")
    goto_parser.add_argument("url", help="URL to navigate to")

    ss_parser = subparsers.add_parser("screenshot", help="Take screenshot")
    ss_parser.add_argument("--output", "-o", help="Output path")
    ss_parser.add_argument("--full-page", "-f", action="store_true", help="Full page screenshot")

    click_parser = subparsers.add_parser("click", help="Click an element")
    click_parser.add_argument("selector", help="CSS selector")

    fill_parser = subparsers.add_parser("fill", help="Fill a form field")
    fill_parser.add_argument("selector", help="CSS selector")
    fill_parser.add_argument("text", help="Text to fill")

    subparsers.add_parser("console", help="Get console logs")
    subparsers.add_parser("info", help="Get page info")
    subparsers.add_parser("test", help="Test browser connection")

    wait_parser = subparsers.add_parser("wait", help="Wait for an element to appear")
    wait_parser.add_argument("selector", help="CSS selector to wait for")
    wait_parser.add_argument("--timeout", "-t", type=int, default=30000, help="Timeout in ms (default: 30000)")

    eval_parser = subparsers.add_parser("eval", help="Execute JavaScript in page context")
    eval_parser.add_argument("js", help="JavaScript code to execute")
    eval_parser.add_argument("--json", "-j", action="store_true", help="Output result as JSON")

    scroll_parser = subparsers.add_parser("scroll", help="Scroll the page")
    scroll_parser.add_argument("target", nargs="?", help="Pixels (number), CSS selector, or 'bottom'")
    scroll_parser.add_argument("--by", action="store_true", help="Scroll by relative amount (with pixel value)")


async def _run_browser_command(args: argparse.Namespace, browser: Browser) -> None:
    async with browser:
        if args.command == "test":
            info = await browser.get_page_info()
            print("Connected to browser successfully!")
            print(f"Current page: {info['url']}")
            print(f"Title: {info['title']}")

        elif args.command == "goto":
            result = await browser.goto(args.url)
            print(f"Navigated to: {result['url']}")
            print(f"Title: {result['title']}")

        elif args.command == "screenshot":
            path = await browser.screenshot(args.output, args.full_page)
            print(f"Screenshot saved to: {path}")

        elif args.command == "click":
            await browser.click(args.selector)
            print(f"Clicked: {args.selector}")

        elif args.command == "fill":
            await browser.fill(args.selector, args.text)
            print(f"Filled {args.selector} with text")

        elif args.command == "console":
            logs = await browser.get_console_logs()
            print(json.dumps(logs, indent=2))

        elif args.command == "info":
            info = await browser.get_page_info()
            print(json.dumps(info, indent=2))

        elif args.command == "wait":
            await browser.wait_for(args.selector, timeout=args.timeout)
            print(f"Element found: {args.selector}")

        elif args.command == "eval":
            result = await browser.evaluate(args.js)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(result if result is not None else "")

        elif args.command == "scroll":
            target = args.target
            if target is None:
                pos = await browser.evaluate("({x: window.scrollX, y: window.scrollY})")
                print(json.dumps(pos, indent=2))
            elif target == "bottom":
                await browser.scroll_to_bottom()
                print("Scrolled to bottom")
            elif target.lstrip("-").isdigit():
                pixels = int(target)
                if args.by:
                    await browser.scroll_by(0, pixels)
                    print(f"Scrolled by {pixels}px")
                else:
                    await browser.scroll(0, pixels)
                    print(f"Scrolled to y={pixels}px")
            else:
                await browser.scroll_into_view(target)
                print(f"Scrolled to: {target}")


async def main():
    parser = argparse.ArgumentParser(description="Browser control for Agent Workcell")
    mode_subparsers = parser.add_subparsers(dest="mode", required=True, help="Browser backend")

    sandbox_parser = mode_subparsers.add_parser("sandbox", help="Use sandbox-local headless Chromium")
    sandbox_parser.add_argument("--cdp", help="Override sandbox CDP endpoint URL")
    sandbox_commands = sandbox_parser.add_subparsers(dest="command", required=True, help="Sandbox commands")
    sandbox_commands.add_parser("start", help="Start sandbox Chromium")
    sandbox_commands.add_parser("stop", help="Stop sandbox Chromium")
    sandbox_commands.add_parser("status", help="Show sandbox Chromium status")
    _add_browser_commands(sandbox_commands)

    host_parser = mode_subparsers.add_parser("host", help="Use host Chrome via CDP")
    host_parser.add_argument("--cdp", default=Browser.HOST_CDP_URL, help="Host Chrome CDP endpoint URL")
    host_commands = host_parser.add_subparsers(dest="command", required=True, help="Host Chrome commands")
    _add_browser_commands(host_commands)

    args = parser.parse_args()

    try:
        if args.mode == "sandbox":
            manager = SandboxBrowser()
            if args.command == "start":
                print(f"Sandbox browser CDP: {manager.ensure_running()}")
                return
            if args.command == "stop":
                stopped = manager.stop()
                print("Sandbox browser stopped" if stopped else "Sandbox browser was not running")
                return
            if args.command == "status":
                print(json.dumps(manager.status(), indent=2))
                return
            await _run_browser_command(args, Browser.sandbox(cdp_url=args.cdp))
            return

        if args.mode == "host":
            await _run_browser_command(args, Browser.host(cdp_url=args.cdp))
            return

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
