# Chrome Integration

The workcell provides two browser-control modes through the `browser` CLI:

- `browser sandbox <command>` controls sandbox-local headless Chromium. This is the default choice for agents opening arbitrary links, checking documentation, inspecting JavaScript-rendered pages, and testing container dev servers without a user-visible browser.
- `browser host <command>` controls Chrome running on the host machine through the Chrome DevTools Protocol (CDP). This is for user-visible browser workflows, host profile/auth/session access, or cases where the user explicitly wants host Chrome.

Bare commands such as `browser goto` are invalid; always choose `sandbox` or `host`.

## Sandbox Headless Mode

Sandbox mode runs Chromium inside the container and exposes a local CDP endpoint to the agent. It keeps browser/page state across CLI calls while the sandbox browser process is running.

Common commands:

```bash
browser sandbox test
browser sandbox goto https://example.com
browser sandbox text
browser sandbox links --json
browser sandbox eval --json 'document.title'
browser sandbox screenshot
browser sandbox status
browser sandbox stop
```

In sandbox mode, `localhost` means inside the container. A dev server running in the workcell can usually be reached directly without exposing the port to the host:

```bash
npm run dev -- --host 127.0.0.1 --port 3000
browser sandbox goto http://localhost:3000
```

Screenshots default to `.workcell/artifacts/screenshots/` when the current workspace has a `.workcell/` directory.

If sandbox mode reports that Chromium is missing, rebuild the workcell image so the base image includes Chromium.

## Host Chrome Mode

Host mode requires Chrome and `socat` on the host. Use it when the user wants to see the browser, when host profile/auth state is required, or when a workflow explicitly asks for host Chrome.

### Prerequisites

- Google Chrome installed on the host.
- `socat` installed on the host.

On macOS:

```bash
brew install socat
```

### Setup

Create a dedicated Chrome profile for agent work:

1. Open Chrome and click the profile icon in the top-right corner.
2. Click **Add** to create a new profile.
3. Name it `Agent`, or another name you prefer.
4. Open `chrome://version` in the new profile.
5. Find **Profile Path** and note the last folder name, such as `Profile 3`.

Create your local config file if it does not exist:

```bash
cp config.template.sh config.sh
```

Edit `config.sh` and set `CHROME_PROFILE` to the folder name from `chrome://version`:

```bash
CHROME_PROFILE="Profile 3"
```

The default Chrome settings in `config.template.sh` are:

```bash
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_USER_DATA="$HOME/Library/Application Support/Google/Chrome"
CHROME_DEBUG_DATA="$HOME/Library/Application Support/Google/Chrome-Debug"
CHROME_PROFILE="CHANGE_ME"
CHROME_DEBUG_PORT=9222
CHROME_INTERNAL_PORT=19222
CHROME_LOG_FILE="/tmp/chrome-debug.log"
```

### Usage

Start a workcell with host Chrome support:

```bash
workcell claude run --with-chrome
```

For host-visible web development, also expose the dev-server port:

```bash
workcell codex run --with-chrome --port 3000
```

This automatically:

1. Starts Chrome with remote debugging using your configured profile.
2. Sets up port forwarding through `socat`.
3. Makes host Chrome available to the sandboxed agent.
4. Cleans up the Chrome process started by the workcell when the session exits.

Inside the sandbox, use explicit host commands:

```bash
browser host test
browser host goto http://localhost:3000
browser host screenshot -o .workcell/artifacts/screenshots/host-preview.png
```

### Start Chrome Separately

Start Chrome independently if you want to keep it running across workcell sessions:

```bash
# Start Chrome with remote debugging
workcell start-chrome

# Auto-restart if Chrome is running
workcell start-chrome --restart

# Override settings from config.sh
workcell start-chrome --port 9333 --profile "Profile 1"
```

Then run the workcell with a matching Chrome/debug setup available to the container.

For host-visible web apps, ask the agent to start the dev server on an exposed port. Servers must bind to `0.0.0.0` inside the container so host Chrome can reach them through `localhost:<port>`.

## URL Semantics

- Sandbox mode: `localhost:<port>` is inside the container.
- Host mode: `localhost:<port>` is on the host. Container dev servers are reachable only when published with `--port <port>` and bound to `0.0.0.0`.
- From the container to a host service, use `host.docker.internal`.

## How Host Chrome Works

There are two communication paths for host mode.

### Container to Host: Chrome Control

Chrome on macOS ignores `--remote-debugging-address=0.0.0.0` and binds remote debugging to `127.0.0.1`. Docker containers cannot reach the host's localhost directly, so the workcell uses `socat` as a bridge:

```text
HOST

Chrome             socat              Docker network
127.0.0.1:19222 <- 0.0.0.0:9222 <- host.docker.internal:9222
internal CDP       bridge             container access
```

### Host to Container: Dev Servers

Dev servers in the container are published to the host with `--port`:

```bash
workcell opencode run --with-chrome --port 3000
```

```text
HOST

Browser -> localhost:3000 -> Docker port publish -> container app on 0.0.0.0:3000
```

## Troubleshooting

Sandbox mode:

- Chromium is missing: rebuild the workcell image so the base image includes Chromium.
- Page cannot load: check that the container dev server is running, and remember that `localhost` is inside the container.
- State is stale: run `browser sandbox stop`, then retry.

Host mode:

- Chrome is not reachable: start the workcell with `--with-chrome` or run `workcell start-chrome` on the host.
- Dev server is unreachable from Chrome: start the server with `--host 0.0.0.0` and expose the matching port with `--port`.
- Port is already in use: change `CHROME_DEBUG_PORT`, change the requested `--port`, or stop the process using the port.
- Profile is not found: confirm `CHROME_PROFILE` matches the final folder name shown in `chrome://version`.

Check the configured Chrome log file on the host for host-mode failures. By default this is `/tmp/chrome-debug.log`.
