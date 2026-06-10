---
name: chrome-integration
description: Use for browser-based web development, visual UI checks, container dev servers, host Chrome, sandbox-headless browsing, and the browser CLI inside Agent Workcell sandboxes.
---

# Chrome Integration Agent Context

Use this document when a task involves browser-based web development, visual UI verification, container dev servers, arbitrary web links, or the `browser` CLI.

## Browser Model

The `browser` CLI has two explicit modes:

- `browser sandbox <command>` controls sandbox-local headless Chromium. Use this by default for ordinary links, documentation pages, JavaScript-rendered pages, DOM inspection, autonomous form/click workflows, and container dev servers that do not need to be visible to the user.
- `browser host <command>` controls Chrome running on the host through the Chrome DevTools Protocol. Use this only when the user explicitly requests host Chrome, when the workflow needs the user's host profile/auth/session, or when the user needs to see/interact with the browser window.

Bare commands such as `browser goto` or `browser test` are invalid. Always choose `sandbox` or `host`.

URL semantics differ by mode:

- In sandbox mode, `localhost` and `127.0.0.1` mean inside the container. Container dev servers can be reached directly at `http://localhost:<port>` without exposing the port to the host.
- In host mode, `localhost` means the host. Container dev servers must bind to `0.0.0.0` and use a port exposed with `--port <port>` so host Chrome can reach `http://localhost:<port>`.
- Host services from inside the container still use `host.docker.internal`; that is separate from host Chrome reaching a container dev server.

## Project Scaffolding

Interactive scaffolding prompts usually do not work in this environment. Use non-interactive flags:

```bash
# Vite
npm create vite@latest my-app -- --template react-ts
npm create vite@latest my-app -- --template vue-ts
npm create vite@latest my-app -- --template svelte-ts

# Next.js
npx create-next-app@latest my-app --typescript --eslint --app --src-dir --no-tailwind --import-alias "@/*"

# Create React App
npx create-react-app my-app --template typescript
```

The `--` before Vite template flags is required so npm passes the arguments to the scaffolding tool.

## Availability Checks

For sandbox-contained browsing, check/start the headless browser with:

```bash
browser sandbox test
browser sandbox status
```

If sandbox mode reports that Chromium is missing, the workcell image needs to be rebuilt with the current base image.

For host-visible Chrome workflows, check exposed ports and host Chrome control before relying on it:

```bash
echo "$EXPOSED_PORTS"
browser host test
```

Host Chrome can be closed by the user at any time. If host mode is unavailable, tell the user they can either run `./start-chrome-debug.sh` on the host or restart the sandbox with `--with-chrome`.

## Dev Server Rules

### Default: sandbox-headless browser

For autonomous checks, start dev servers normally inside the container and navigate sandbox Chromium to the container-local URL:

```bash
# Vite
npm run dev -- --host 127.0.0.1 --port 3000

# Next.js
npm run dev -- -H 127.0.0.1 -p 3000

# Create React App
HOST=127.0.0.1 PORT=3000 npm start

browser sandbox goto "http://localhost:3000"
```

Binding to `0.0.0.0` is also fine, but it is not required for sandbox mode.

### Explicit host Chrome mode

When using host Chrome, start dev servers on an exposed port and bind to `0.0.0.0`, not `localhost` or `127.0.0.1`:

```bash
# Vite
npm run dev -- --host 0.0.0.0 --port 3000

# Next.js
npm run dev -- -H 0.0.0.0 -p 3000

# Create React App
HOST=0.0.0.0 PORT=3000 npm start

browser host goto "http://localhost:3000"
```

If the requested port is not exposed for host mode, use an exposed port when possible. If no suitable port is exposed, tell the user to restart with `--port <port>`.

## Browser CLI

Use sandbox mode by default:

```bash
browser sandbox test                    # Test/start sandbox headless Chromium
browser sandbox goto <url>              # Navigate to URL
browser sandbox links [--json] [--all]  # List page links
browser sandbox text [selector]         # Print visible text; alias: content
browser sandbox screenshot [-o path]    # Take screenshot; defaults under .workcell/artifacts/screenshots/ when available
browser sandbox click <selector>        # Click by CSS selector
browser sandbox fill <selector> <text>  # Fill form field
browser sandbox console                 # Read browser console logs
browser sandbox info                    # Current page URL and title
browser sandbox wait <selector>         # Wait for element
browser sandbox eval <js>               # Execute JavaScript; use --json for JSON output
browser sandbox scroll [target]         # Scroll pixels, selector, or bottom; use --by for relative
browser sandbox start|stop|status       # Manage sandbox headless Chromium lifecycle
```

Use host mode only for explicit host-visible workflows:

```bash
browser host test
browser host goto "http://localhost:3000"
browser host screenshot -o .workcell/artifacts/screenshots/host-preview.png
```

Python API defaults should be explicit too:

```python
from browser import Browser

async with Browser.sandbox() as b:
    await b.goto("http://localhost:3000")
    print(await b.get_page_text())
    print(await b.get_links())

async with Browser.host() as b:
    await b.goto("http://localhost:3000")
    await b.screenshot(".workcell/artifacts/screenshots/20260429-132400-preview.png")
```

## Link And Page Inspection Workflow

Prefer DOM/text inspection before screenshots:

1. `browser sandbox goto <url>`.
2. `browser sandbox text` for readable page content.
3. `browser sandbox links --json` for navigable targets.
4. `browser sandbox eval --json '<js>'` for structured state not covered by built-ins.
5. Use `click`, `fill`, `wait`, and `scroll` to interact.
6. Take screenshots only when layout, graphics, or visual state matters.

## Verification Workflow

For frontend work, verify with sandbox mode unless the user needs to see the browser or host profile/auth is required:

1. Start the dev server in the container.
2. Navigate with `browser sandbox goto http://localhost:<port>`.
3. Check text/links for basic page state.
4. Check the console for errors.
5. Interact with the page for key workflows.
6. Take screenshots for visual layout checks when useful.

For host-visible verification, first confirm the port is exposed, bind the server to `0.0.0.0`, and use `browser host ...` commands.

Save temporary screenshots and other generated verification artifacts under `.workcell/artifacts/`. Use optional subdirectories such as `screenshots/`, `logs/`, and `mockups/` when they help organize related files. Prefer timestamped filenames such as `screenshots/20260429-132400-dashboard.png`.

## Troubleshooting

Sandbox mode:

- Chromium missing: rebuild the workcell image so the base image includes Chromium.
- Page cannot load: remember that `localhost` is inside the container; check that the container dev server is running and listening on the requested port.
- Browser state is stale: run `browser sandbox stop`, then retry.

Host mode:

- Chrome control unavailable: host Chrome is not running with debugging enabled, or the sandbox was not started with Chrome support.
- Page cannot load: the dev server is not bound to `0.0.0.0`, the port is not exposed, or Chrome was pointed at the wrong host URL.
- Server works in the container but not in host Chrome: re-check `$EXPOSED_PORTS` and ensure Chrome uses `localhost:<port>`.

Check host Chrome debug logs when host browser control fails:

```bash
cat "$CHROME_LOG"
```
