# Chrome Integration

The workcell can control Chrome running on the host machine through the Chrome DevTools Protocol
(CDP). This is intended for web development workflows where the agent edits code inside the
container, starts a dev server there, and verifies the result in host Chrome.

## Prerequisites

- Google Chrome installed on the host.
- `socat` installed on the host.

On macOS:

```bash
brew install socat
```

## Setup

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

## Usage

Start a workcell with Chrome support:

```bash
workcell run claude --with-chrome
```

For web development, also expose the dev-server port:

```bash
workcell run codex --with-chrome --port 3000
```

This automatically:

1. Starts Chrome with remote debugging using your configured profile.
2. Sets up port forwarding through `socat`.
3. Makes host Chrome available to the sandboxed agent.
4. Cleans up the Chrome process started by the workcell when the session exits.

## Start Chrome Separately

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

For web apps, ask the agent to start the dev server on an exposed port. Servers must bind to
`0.0.0.0` inside the container so host Chrome can reach them through `localhost:<port>`.

## How It Works

There are two communication paths.

### Container to Host: Chrome Control

Chrome on macOS ignores `--remote-debugging-address=0.0.0.0` and binds remote debugging to
`127.0.0.1`. Docker containers cannot reach the host's localhost directly, so the workcell uses
`socat` as a bridge:

```text
HOST

Chrome             socat              Docker network
127.0.0.1:19222 <- 0.0.0.0:9222 <- host.docker.internal:9222
internal CDP       bridge             container access
```

### Host to Container: Dev Servers

Dev servers in the container are published to the host with `--port`:

```bash
workcell run opencode --with-chrome --port 3000
```

```text
HOST

Browser -> localhost:3000 -> Docker port publish -> container app on 0.0.0.0:3000
```

## Troubleshooting

Check the configured Chrome log file on the host. By default this is `/tmp/chrome-debug.log`.

Common issues:

- Chrome is not reachable: start the workcell with `--with-chrome` or run
  `workcell start-chrome` on the host.
- Dev server is unreachable from Chrome: start the server with `--host 0.0.0.0` and expose the
  matching port with `--port`.
- Port is already in use: change `CHROME_DEBUG_PORT`, change the requested `--port`, or stop the
  process using the port.
- Profile is not found: confirm `CHROME_PROFILE` matches the final folder name shown in
  `chrome://version`.
