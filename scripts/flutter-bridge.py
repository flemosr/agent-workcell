#!/usr/bin/env python3
"""
Flutter Host Bridge

HTTP API server for controlling a Flutter app from a Docker container.
Uses only Python standard library.

Configuration is passed via command-line arguments.

Endpoints:
    GET    /health       - Health check (no auth)
    POST   /health       - Health check with auth (for token verification)
    GET    /status       - Bridge status (auth required)
    GET    /devices      - List available devices (auth required)
    POST   /launch       - Launch Flutter app (auth required)
    POST   /attach       - Attach to running Flutter app (auth required)
    POST   /detach       - Detach/stop Flutter app (auth required)
    POST   /hot-reload   - Hot reload (auth required)
    POST   /hot-restart  - Hot restart (auth required)
    POST   /stop         - Shutdown bridge
    GET    /logs         - Recent log lines (auth required)
    GET    /screenshot   - Take screenshot, returns PNG (auth required)
"""

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse


# ---- Threaded HTTP Server ----

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ---- Bridge State ----

class BridgeState:
    def __init__(self, token, project_dir, device_id, target, flutter_path,
                 run_args):
        self.token = token
        self.project_dir = project_dir
        self.device_id = device_id
        self.target = target
        self.flutter_path = flutter_path
        self.run_args = parse_run_args(run_args)

        self.process = None
        self.subprocess_type = None
        self.subprocess_lock = threading.Lock()
        self.log_buffer = deque(maxlen=1000)
        self.vm_service_url = None
        self._status = "idle"
        self._status_message = ""
        self.stop_event = threading.Event()

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    def to_status_dict(self):
        return {
            "status": self._status,
            "subprocess_type": self.subprocess_type,
            "vm_service_url": self.vm_service_url,
            "device_id": self.device_id,
            "message": self._status_message,
        }

    def add_log(self, line):
        self.log_buffer.append(line)

    def get_logs(self):
        return list(self.log_buffer)


# ---- Flutter Subprocess Management ----

def _reader_thread(state, proc):
    """Read and buffer stdout from the Flutter subprocess."""
    vm_patterns = [
        re.compile(
            r'(?:A\s+)?(?:Observatory|Dart VM Service|VM Service)'
            r'(?: debugger and profiler)?(?: on .+?)?'
            r' is available at:?\s+(https?://[^\s]+)',
            re.IGNORECASE,
        ),
    ]

    try:
        for line in iter(proc.stdout.readline, ''):
            if state.stop_event.is_set():
                break
            line = line.rstrip('\n\r')
            state.add_log(line)

            if state.vm_service_url is None:
                for pat in vm_patterns:
                    m = pat.search(line)
                    if m:
                        state.vm_service_url = m.group(1)
                        state.add_log(
                            f"[BRIDGE] Detected VM service URL: {state.vm_service_url}"
                        )
                        if state.subprocess_type == "run":
                            state.status = "running"
                        elif state.subprocess_type == "attach":
                            state.status = "attached"
                        break

        returncode = proc.wait()
        if not state.stop_event.is_set():
            state.add_log(
                f"[BRIDGE] Flutter process exited with code {returncode}"
            )
            state.status = "idle"
            state.subprocess_type = None
            state.process = None
            state.vm_service_url = None
    except Exception as e:
        if not state.stop_event.is_set():
            state.add_log(f"[BRIDGE] Error reading subprocess output: {e}")
            state.status = "idle"
            state.subprocess_type = None
            state.process = None
            state.vm_service_url = None
    finally:
        with state.subprocess_lock:
            if state.process is not None:
                state.process = None


def start_subprocess(state, mode, device_id):
    """Start a Flutter subprocess in run or attach mode."""
    with state.subprocess_lock:
        if state.process is not None and state.process.poll() is None:
            return {
                "error": f"Flutter app is already {state.subprocess_type or 'running'} "
                f"(status: {state.status}). Detach first."
            }

        if not os.path.isdir(state.project_dir):
            return {
                "error": f"Project directory not found: {state.project_dir}"
            }

        cmd = [state.flutter_path, mode]
        if device_id:
            cmd.extend(["-d", device_id])
        if state.target and mode == "run":
            cmd.extend(["-t", state.target])
        if state.run_args:
            cmd.extend(state.run_args)

        state.add_log(f"[BRIDGE] Running: {' '.join(cmd)}")

        try:
            state.status = "launching"
            state.subprocess_type = mode
            state.device_id = device_id
            state.vm_service_url = None

            proc = subprocess.Popen(
                cmd,
                cwd=state.project_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
            )
            state.process = proc

            reader = threading.Thread(
                target=_reader_thread,
                args=(state, proc),
                daemon=True,
            )
            reader.start()

            return {
                "status": "launching",
                "subprocess_type": mode,
                "message": f"Flutter {mode} started for device {device_id or 'default'}",
            }
        except Exception as e:
            state.status = "error"
            state.subprocess_type = None
            state.vm_service_url = None
            state.add_log(f"[BRIDGE] Failed to start flutter {mode}: {e}")
            return {"error": f"Failed to start flutter {mode}: {e}"}


def stop_subprocess(state):
    """Stop the Flutter subprocess."""
    with state.subprocess_lock:
        if state.process is None:
            return {"status": "idle", "message": "No Flutter process running"}

        state.add_log("[BRIDGE] Stopping Flutter process...")
        state.stop_event.set()

        try:
            if state.process.stdin:
                try:
                    state.process.stdin.write('q\n')
                    state.process.stdin.flush()
                except Exception as e:
                    state.add_log(f"[BRIDGE] Could not send quit command: {e}")

            time.sleep(0.5)

            if state.process.poll() is None:
                try:
                    if hasattr(os, 'killpg') and hasattr(os, 'getpgid'):
                        os.killpg(
                            os.getpgid(state.process.pid), signal.SIGTERM
                        )
                    else:
                        state.process.terminate()
                except (ProcessLookupError, OSError):
                    pass

                try:
                    state.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        if hasattr(os, 'killpg') and hasattr(os, 'getpgid'):
                            os.killpg(
                                os.getpgid(state.process.pid), signal.SIGKILL
                            )
                        else:
                            state.process.kill()
                        state.process.wait(timeout=2)
                    except (subprocess.TimeoutExpired, ProcessLookupError,
                            OSError):
                        pass
        except Exception as e:
            state.add_log(f"[BRIDGE] Error stopping process: {e}")
        finally:
            state.process = None
            state.subprocess_type = None
            state.vm_service_url = None
            state.status = "idle"
            state.stop_event.clear()
            state.add_log("[BRIDGE] Flutter process stopped")

        return {"status": "idle", "message": "Flutter process stopped"}


def send_key_to_subprocess(state, key):
    """Send a key to the Flutter subprocess stdin."""
    with state.subprocess_lock:
        if state.process is None or state.process.poll() is not None:
            return {"error": "No Flutter process running"}

        try:
            state.process.stdin.write(key + '\n')
            state.process.stdin.flush()
            state.add_log(f"[BRIDGE] Sent '{key}' to Flutter process")
            return {"status": state.status, "message": f"Sent '{key}' command"}
        except (BrokenPipeError, OSError) as e:
            return {"error": f"Failed to send command: {e}"}


# ---- HTTP Request Handler ----

class FlutterBridgeHandler(BaseHTTPRequestHandler):

    bridge_state = None

    def log_message(self, format, *args):
        if self.bridge_state:
            self.bridge_state.add_log(
                f"[HTTP] {self.client_address[0]} {format % args}"
            )

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return None
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_binary(self, data, content_type='image/png'):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header(
            'Access-Control-Allow-Methods', 'GET, POST, OPTIONS'
        )
        self.send_header(
            'Access-Control-Allow-Headers',
            'Authorization, Content-Type',
        )
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/health':
            self._send_json({"status": "ok"})
            return

        if not self._authenticate():
            return

        try:
            if path == '/status':
                self._send_json(self.bridge_state.to_status_dict())
            elif path == '/devices':
                self._handle_devices()
            elif path == '/logs':
                self._send_json({"logs": self.bridge_state.get_logs()})
            elif path == '/screenshot':
                self._handle_screenshot()
            else:
                self._send_json(
                    {"error": f"Unknown endpoint: {path}"}, 404
                )
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/health':
            if self._authenticate():
                self._send_json({"status": "ok", "authenticated": True})
            return

        if not self._authenticate():
            return

        if path == '/stop':
            self._send_json({"message": "Stopping bridge..."})
            threading.Thread(
                target=self._shutdown_bridge, daemon=True
            ).start()
            return

        body = self._read_body()

        try:
            if path == '/launch':
                device = (body or {}).get("device", self.bridge_state.device_id)
                if not device:
                    self._send_json(
                        {
                            "error": "No device specified. Provide 'device' in "
                            "request body or set FLUTTER_DEVICE_ID in config."
                        },
                        400,
                    )
                    return
                result = start_subprocess(self.bridge_state, "run", device)
                status = 202 if "error" not in result else 400
                self._send_json(result, status)

            elif path == '/attach':
                device = (body or {}).get("device", self.bridge_state.device_id)
                if not device:
                    self._send_json(
                        {
                            "error": "No device specified. Provide 'device' in "
                            "request body or set FLUTTER_DEVICE_ID in config."
                        },
                        400,
                    )
                    return
                result = start_subprocess(self.bridge_state, "attach", device)
                status = 202 if "error" not in result else 400
                self._send_json(result, status)

            elif path == '/detach':
                result = stop_subprocess(self.bridge_state)
                self._send_json(result)

            elif path == '/hot-reload':
                result = send_key_to_subprocess(self.bridge_state, 'r')
                status = 200 if "error" not in result else 400
                self._send_json(result, status)

            elif path == '/hot-restart':
                result = send_key_to_subprocess(self.bridge_state, 'R')
                status = 200 if "error" not in result else 400
                self._send_json(result, status)

            else:
                self._send_json(
                    {"error": f"Unknown endpoint: {path}"}, 404
                )
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _authenticate(self):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            self._send_json(
                {"error": "Missing or invalid Authorization header"}, 401
            )
            return False
        token = auth[7:]
        if token != self.bridge_state.token:
            self._send_json({"error": "Invalid bearer token"}, 401)
            return False

        return True

    def _handle_devices(self):
        try:
            flutter_path = self.bridge_state.flutter_path
            result = subprocess.run(
                [flutter_path, "devices", "--machine"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self._send_json(
                    {"error": f"flutter devices failed: {result.stderr}"}, 500
                )
                return
            devices = json.loads(result.stdout)
            self._send_json({"devices": devices})
        except json.JSONDecodeError:
            # Fallback: try non-machine output
            try:
                result = subprocess.run(
                    [flutter_path, "devices"],
                    capture_output=True, text=True, timeout=30,
                )
                self._send_json(
                    {
                        "devices": [],
                        "raw_output": result.stdout,
                        "error": "Could not parse machine-readable output",
                    }
                )
            except Exception:
                self._send_json(
                    {"error": "Failed to parse flutter devices output"}, 500
                )
        except subprocess.TimeoutExpired:
            self._send_json({"error": "flutter devices timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_screenshot(self):
        fd, tmp_path = tempfile.mkstemp(
            suffix='.png', prefix='flutter_screenshot_'
        )
        os.close(fd)

        try:
            flutter_path = self.bridge_state.flutter_path
            project_dir = self.bridge_state.project_dir

            cmd = [flutter_path, "screenshot"]
            if self.bridge_state.device_id:
                cmd.extend(["-d", self.bridge_state.device_id])
            cmd.extend(["-o", tmp_path])

            result = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode != 0:
                self._send_json(
                    {"error": f"flutter screenshot failed: {result.stderr}"},
                    500,
                )
                return

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                self._send_json(
                    {"error": "Screenshot file is empty or not found"}, 500
                )
                return

            with open(tmp_path, 'rb') as f:
                data = f.read()
            self._send_binary(data, 'image/png')
        except subprocess.TimeoutExpired:
            self._send_json({"error": "flutter screenshot timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _shutdown_bridge(self):
        time.sleep(0.5)
        stop_subprocess(self.bridge_state)
        self.bridge_state.stop_event.set()
        os._exit(0)


# ---- Main ----

def parse_args():
    parser = argparse.ArgumentParser(description="Flutter Host Bridge")
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to listen on"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to"
    )
    parser.add_argument(
        "--project-dir", required=True, help="Flutter project directory"
    )
    parser.add_argument(
        "--device-id", default="", help="Default device ID"
    )
    parser.add_argument(
        "--target", default="lib/main.dart", help="Flutter target file"
    )
    parser.add_argument(
        "--flutter-path", default="flutter", help="Path to flutter executable"
    )
    parser.add_argument(
        "--token", required=True, help="Bearer token for auth"
    )
    parser.add_argument(
        "--log-file", default="", help="Log file path for bridge output"
    )
    parser.add_argument(
        "--run-args", default="", help="Extra args for flutter run"
    )
    return parser.parse_args()


def parse_run_args(value):
    """Parse optional flutter run args from JSON array or shell-style string."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return shlex.split(value)
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if isinstance(parsed, str):
        return shlex.split(parsed)
    return []


def main():
    args = parse_args()

    if not os.path.isdir(args.project_dir):
        print(
            f"Error: Project directory not found: {args.project_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    state = BridgeState(
        token=args.token,
        project_dir=args.project_dir,
        device_id=args.device_id,
        target=args.target,
        flutter_path=args.flutter_path,
        run_args=args.run_args,
    )

    def signal_handler(signum, frame):
        print("\nShutting down Flutter bridge...", file=sys.stderr)
        stop_subprocess(state)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.log_file:
        state.add_log(f"[BRIDGE] Logging to {args.log_file}")

    server = ThreadingHTTPServer((args.host, args.port), FlutterBridgeHandler)
    FlutterBridgeHandler.bridge_state = state

    print(
        f"Flutter Bridge running on http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    print(f"Project: {args.project_dir}", file=sys.stderr)
    if args.device_id:
        print(f"Device: {args.device_id}", file=sys.stderr)
    print(
        f"Token: {args.token[:8]}...",
        file=sys.stderr,
    )
    print(
        "Use FLUTTER_BRIDGE_TOKEN in container to authenticate.",
        file=sys.stderr,
    )
    print(file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nCleaning up...", file=sys.stderr)
        stop_subprocess(state)
        server.server_close()


if __name__ == "__main__":
    main()
