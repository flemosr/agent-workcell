# Flutter Integration

Agent Workcell supports Flutter development in two complementary ways:

- **In-container Flutter SDK** — tests, analysis, formatting, code generation, and package
  management run inside the sandbox with no host Flutter setup required.
- **Host Flutter bridge** — native/device runs use Flutter on the host machine while the agent edits
  code in the container workspace.

For Flutter web, use [Chrome integration](chrome-integration.md) instead.

## In-container Flutter SDK

Workcell images include Flutter and Dart. Inside a sandbox, agents can run commands such as:

```bash
flutter test
flutter analyze
dart format .
flutter pub get
```

These commands use the SDK bundled with the Workcell image and are suitable for normal source-level
verification. Pub packages are cached in the selected harness's persisted Docker volume.

## Host Flutter bridge

Native/device targets require host-side tooling such as Xcode, Android Studio, simulators,
emulators, desktop windows, or physical devices. The Flutter bridge connects the sandbox to a host
Flutter process so an agent can launch, attach to, hot reload, capture screenshots, and perform
supported UI interactions without broad host shell access.

The bridge is intended for native/device targets only. It is not needed for tests, analysis,
formatting, or Flutter web.

## Prerequisites

- Flutter SDK installed on the host machine.
- At least one configured Flutter target, such as iOS Simulator, Android Emulator, macOS desktop, or
  a physical device.
- macOS host for the primary supported path. Linux Android Emulator support can follow.
- For macOS desktop UI automation and screenshots, host privacy permissions such as Accessibility
  and Screen Recording may be required.

## Setup

Create your local config file if it does not exist:

```bash
cp config.template.sh config.sh
```

Default bridge settings are:

```bash
FLUTTER_DEFAULT_BRIDGE_PORT=8765
FLUTTER_BRIDGE_LOG_FILE="/tmp/flutter-bridge.log"
```

If `flutter` is not on the host `PATH`, set `FLUTTER_PATH` in `config.sh`:

```bash
FLUTTER_PATH="/usr/local/bin/flutter"
```

Project-specific Flutter run settings can live in `.workcell/flutter-config.json`:

```json
{
  "target": "lib/main_dev.dart",
  "run_args": [
    "--flavor",
    "staging",
    "--dart-define",
    "API_BASE_URL=https://api.example.test"
  ]
}
```

When a bridge starts, Workcell also writes runtime connection details such as `token` and `port` to
that file. The bridge port is selected from:

1. `--bridge-port`, if supplied.
2. `.workcell/flutter-config.json`.
3. `FLUTTER_DEFAULT_BRIDGE_PORT`.
4. `8765`.

## Usage

Run from the host Flutter project directory:

```bash
workcell claude run --with-flutter
```

If the Flutter project is in a workspace subdirectory, pass the project path relative to the
workspace root:

```bash
workcell codex run --with-flutter --flutter-project-dir ./gui
```

This automatically:

1. Starts the host Flutter bridge on the selected port.
2. Generates a per-session bearer token.
3. Makes the bridge available inside the sandbox.
4. Mounts the bridge log file for troubleshooting.
5. Cleans up the bridge started by Workcell when the session exits.

Use `--bridge-port` to select a bridge port for one run:

```bash
workcell claude run --with-flutter --bridge-port 8765
workcell opencode run --yolo --with-flutter --bridge-port 8766
```

`--with-flutter` and `--with-chrome` cannot be used together. Use `--with-chrome` for Flutter web
and `--with-flutter` for native/device targets. In Flutter mode, `--port` can still expose a
container dev-server port to the host:

```bash
workcell codex run --with-flutter --bridge-port 8766 --port 3000
```

## Start the bridge separately

Start the bridge independently if you want it to keep running across Workcell sessions:

```bash
# Start using defaults and project-local settings
workcell start-flutter-bridge

# Override bridge settings
workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
workcell start-flutter-bridge --flutter-project-dir ./gui
```

Then run the workcell without `--with-flutter`. The launcher writes connection details to
`.workcell/flutter-config.json`, and future sessions can reuse those connection details.

## What agents can do through the bridge

Agents receive detailed bridge workflow guidance through the bundled `flutter-integration` skill.
At a high level, the bridge supports:

- listing host Flutter devices;
- launching or attaching to a Flutter app;
- hot reload and hot restart;
- reading recent Flutter logs;
- screenshots for supported targets;
- limited UI inspection and interaction on supported macOS-hosted targets.

The bridge exposes a fixed-purpose API. It does not provide arbitrary host command execution.

## UI automation and screenshots

UI automation support is intentionally narrow. It is currently focused on macOS hosts targeting iOS
Simulator and macOS desktop apps. Android, Linux desktop, Windows desktop, physical iOS, Flutter
web, and non-macOS hosts are not supported by the bridge UI action API.

For reliable agent-driven UI interaction, app code should expose stable Flutter semantics
identifiers on important controls and containers, for example:

```dart
Semantics(
  identifier: 'login_button',
  child: ElevatedButton(
    onPressed: signIn,
    child: const Text('Sign in'),
  ),
)
```

Screenshots are supported when a Flutter app is running under the bridge. Mobile targets use
Flutter's device screenshot support. On macOS desktop, screenshots capture only the Flutter app
window; if the window cannot be found or macOS Screen Recording permission blocks capture, the
request fails instead of falling back to a full-screen screenshot.

## How it works

```text
HOST

Flutter bridge HTTP API, usually 0.0.0.0:8765 with bearer-token auth
  - flutter run / flutter attach subprocess management
  - screenshots
  - flutter devices
  - hot reload / hot restart
  - limited UI automation actions

Flutter SDK, simulators, emulators, desktop apps, or devices

CONTAINER

Sandboxed agent -> fixed-purpose bridge API
```

The host owns native/device Flutter execution and OS-level automation permissions. The container
owns source edits, in-container Flutter/Dart tooling, and authenticated calls to the bridge API.

## Limitations

- One bridge is intended for one sandbox/agent. Multiple sandboxes should use distinct bridge ports
  and run from the corresponding host Flutter project directories.
- macOS is the primary supported host platform.
- Flutter web is handled by Chrome integration, not the Flutter bridge.
- The bridge operates on a single project directory configured at startup.
- The bridge does not expose arbitrary host command execution.
- Concurrent bridge instances need manually configured ports.

## Troubleshooting

Check the Flutter bridge log:

```bash
cat /tmp/flutter-bridge.log
```

Common issues:

- Cannot reach Flutter bridge: start the workcell with `--with-flutter` or run
  `workcell start-flutter-bridge` from the Flutter project directory.
- Bridge is reachable but stale after Workcell changes: ask the agent to restart the bridge, or
  restart it from the host.
- Missing bridge token: when using `--with-flutter`, the token is auto-generated. For a separate
  bridge, start it from the workspace so `.workcell/flutter-config.json` is available.
- Concurrent sandbox needs a bridge: start a separate bridge on a different port.
- Port is already in use: use a different `--bridge-port`, update `.workcell/flutter-config.json`,
  or stop the existing process.
- Flutter subprocess fails to start: ensure the project compiles and the target device is
  available. Run `flutter doctor -v` on the host.
- Host bridge `flutter: command not found`: set host `FLUTTER_PATH` in `config.sh`.
- Container `flutter: command not found`: rebuild or update the Workcell image.
