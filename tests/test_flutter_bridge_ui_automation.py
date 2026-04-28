import importlib.util
import json
import pathlib
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = load_module("flutter_bridge", "scripts/flutter-bridge.py")
flutterctl = load_module(
    "flutterctl", "sandbox/flutter-tools/flutterctl.py"
)


class UiAutomationCapabilityTests(unittest.TestCase):
    def test_classifies_ios_simulator(self):
        target = bridge.classify_device(
            "8F0F",
            {
                "id": "8F0F",
                "name": "iPhone 15",
                "targetPlatform": "ios",
                "emulator": True,
                "sdk": "iOS 17 Simulator",
            },
        )

        self.assertEqual(target["backend"], "ios-simulator")
        self.assertEqual(target["target_platform"], "ios")
        self.assertEqual(target["device_kind"], "simulator")

    def test_classifies_macos_desktop(self):
        target = bridge.classify_device(
            "macos",
            {
                "id": "macos",
                "name": "macOS",
                "targetPlatform": "darwin",
                "emulator": False,
            },
        )

        self.assertEqual(target["backend"], "macos-desktop")
        self.assertEqual(target["target_platform"], "macos")
        self.assertEqual(target["device_kind"], "desktop")

    def test_classifies_android_as_unsupported(self):
        target = bridge.classify_device(
            "emulator-5554",
            {
                "id": "emulator-5554",
                "name": "Android SDK built for arm64",
                "targetPlatform": "android-arm64",
                "emulator": True,
            },
        )

        self.assertEqual(target["backend"], "unsupported")
        self.assertEqual(target["target_platform"], "android")

    def test_status_reports_no_app_running(self):
        target = bridge.classify_device(
            "macos", {"id": "macos", "targetPlatform": "darwin"}
        )
        status = bridge.build_ui_automation_status(
            bridge_status="idle",
            has_process=False,
            has_vm_service=False,
            device_id="macos",
            target=target,
            tools={"osascript": True},
        )

        self.assertFalse(status["ready"])
        self.assertIn("tap", status["actions"])
        self.assertFalse(status["actions"]["tap"]["supported"])
        self.assertEqual(status["actions"]["tap"]["selectors"], [])
        self.assertIn("No Flutter app", status["actions"]["tap"]["reason"])

    def test_status_reports_macos_desktop_capabilities(self):
        target = bridge.classify_device(
            "macos", {"id": "macos", "targetPlatform": "darwin"}
        )
        status = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=True,
            device_id="macos",
            target=target,
            tools={"osascript": True},
        )

        self.assertTrue(status["ready"])
        self.assertEqual(status["coordinate_space"], "app-window-points")
        self.assertEqual(status["tools"], {"osascript": True})
        self.assertEqual(status["permissions"], {"accessibility": "unknown"})
        self.assertTrue(status["actions"]["tap"]["supported"])
        self.assertEqual(
            status["actions"]["tap"]["selectors"], ["coordinates", "text"]
        )
        self.assertEqual(
            status["actions"]["tap"]["coordinate_space"],
            "app-window-points",
        )
        self.assertTrue(status["actions"]["press"]["supported"])
        self.assertTrue(status["actions"]["type"]["supported"])
        self.assertTrue(status["actions"]["scroll"]["supported"])
        self.assertTrue(status["actions"]["inspect"]["supported"])
        self.assertEqual(status["actions"]["inspect"]["selectors"], ["text"])
        self.assertTrue(status["actions"]["wait"]["supported"])
        self.assertEqual(status["actions"]["wait"]["selectors"], ["text"])


class MacosScreenshotHelperTests(unittest.TestCase):
    def test_selects_first_visible_layer_zero_window_for_pid(self):
        window = bridge._select_macos_app_window(
            [
                {
                    "pid": 123,
                    "window_id": 1,
                    "layer": 1,
                    "onscreen": True,
                    "alpha": 1,
                    "bounds": (0, 0, 10, 10),
                },
                {
                    "pid": 456,
                    "window_id": 2,
                    "layer": 0,
                    "onscreen": True,
                    "alpha": 1,
                    "bounds": (0, 0, 10, 10),
                },
                {
                    "pid": 123,
                    "window_id": 3,
                    "layer": 0,
                    "onscreen": True,
                    "alpha": 1,
                    "bounds": (12.5, 30.1, 400.8, 300.2),
                },
            ],
            123,
        )

        self.assertEqual(
            window, {"window_id": 3, "bounds": (12, 30, 400, 300)}
        )

    def test_screencapture_command_uses_window_id_only(self):
        command = bridge._macos_screencapture_command(42, "/tmp/screen.png")

        self.assertEqual(
            command, ["screencapture", "-x", "-l42", "/tmp/screen.png"]
        )
        self.assertNotIn("-R", command)

    def test_get_app_window_info_reports_missing_visible_window(self):
        with mock.patch.object(
            bridge, "_macos_get_process_id", return_value=(123, None)
        ), mock.patch.object(
            bridge, "_macos_coregraphics_windows", return_value=[]
        ):
            window, error = bridge._macos_get_app_window_info("demo_app")

        self.assertIsNone(window)
        self.assertIn("no visible app window", error)


class MacosBackendDispatchTests(unittest.TestCase):
    def test_backend_error_uses_500_status(self):
        result = {"error": "osascript failed", "code": "BACKEND_ERROR"}

        self.assertEqual(bridge._ui_backend_status(result), 500)

    def test_scroll_dispatch_uses_backend_error_status(self):
        with mock.patch.object(
            bridge,
            "_macos_press",
            return_value={"error": "osascript failed", "code": "BACKEND_ERROR"},
        ):
            result, status = bridge._macos_desktop_dispatch(
                "demo_app", "scroll", {"dy": 600}
            )

        self.assertEqual(status, 500)
        self.assertEqual(result["code"], "BACKEND_ERROR")

    def test_scroll_dispatch_reports_key_approximation(self):
        with mock.patch.object(
            bridge,
            "_macos_press",
            return_value={"action": "press", "key": "pagedown"},
        ):
            result, status = bridge._macos_desktop_dispatch(
                "demo_app", "scroll", {"dy": 600}
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["action"], "scroll")
        self.assertEqual(result["dy"], 600)
        self.assertEqual(result["dispatch"], "key")
        self.assertEqual(result["key"], "pagedown")
        self.assertEqual(result["scroll_model"], "key-approximation")

    def test_tap_coordinates_are_app_window_local_points(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        with mock.patch.object(
            bridge, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge, "_macos_post_mouse_click", return_value=None
        ) as post_click:
            result = bridge._macos_tap_coordinates("demo_app", 12.5, 34.0)

        post_click.assert_called_once_with(112.5, 234.0)
        self.assertEqual(result["action"], "tap")
        self.assertEqual(result["coordinate_space"], "app-window-points")
        self.assertEqual(result["screen_x"], 112.5)
        self.assertEqual(result["screen_y"], 234.0)
        self.assertEqual(
            result["window"],
            {"id": 4, "x": 100, "y": 200, "width": 300, "height": 400},
        )

    def test_tap_rejects_coordinates_outside_app_window(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        with mock.patch.object(
            bridge, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(bridge, "_macos_post_mouse_click") as post_click:
            result = bridge._macos_tap_coordinates("demo_app", 300, 100)

        post_click.assert_not_called()
        self.assertEqual(result["code"], "INVALID_BODY")
        self.assertEqual(result["window"]["width"], 300)

    def test_parses_inspect_output_as_app_window_local_rects(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        stdout = (
            "AXButton\t\tSave\tbutton\t\ttrue\t150\t260\t80\t40\n"
            "AXStaticText\t\tReady\t\t\t\t120\t230\t60\t20\n"
        )

        elements = bridge._parse_macos_inspect_output(stdout, window)

        self.assertEqual(elements[0]["type"], "button")
        self.assertEqual(elements[0]["text"], "Save")
        self.assertEqual(
            elements[0]["rect"], {"x": 50, "y": 60, "w": 80, "h": 40}
        )
        self.assertTrue(elements[0]["enabled"])
        self.assertEqual(elements[1]["type"], "text")

    def test_parses_missing_value_as_empty_text(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        stdout = "\t\tmissing value\t\t\t\t\t\t\t\n"

        elements = bridge._parse_macos_inspect_output(stdout, window)

        self.assertEqual(elements[0]["text"], "")
        self.assertEqual(elements[0]["label"], "")

    def test_extracts_flutter_inspector_text_with_app_window_rect(self):
        window = {"window_id": 4, "bounds": (100, 200, 800, 632)}
        summary_root = {
            "valueId": "root",
            "children": [{
                "valueId": "text-1",
                "textPreview": "Button taps recorded",
                "widgetRuntimeType": "Text",
            }],
        }
        layout_root = {
            "valueId": "root",
            "size": {"width": "800.0", "height": "600.0"},
            "children": [{
                "valueId": "container",
                "parentData": {"offsetX": "24.0", "offsetY": "40.0"},
                "children": [{
                    "valueId": "text-1",
                    "description": "Text",
                    "size": {"width": "200.0", "height": "24.0"},
                    "renderObject": {
                        "properties": [{
                            "name": "parentData",
                            "description": (
                                "offset=Offset(10.0, 20.0) "
                                "(can use size)"
                            ),
                        }]
                    },
                }],
            }],
        }

        elements = bridge._flutter_inspector_elements_from_trees(
            summary_root, layout_root, window
        )

        self.assertEqual(elements[0]["text"], "Button taps recorded")
        self.assertEqual(elements[0]["source"], "flutter-inspector")
        self.assertEqual(
            elements[0]["rect"], {"x": 34, "y": 92, "w": 200, "h": 24}
        )

    def test_extracts_fab_tooltip_with_default_material_rect(self):
        window = {"window_id": 4, "bounds": (100, 200, 800, 632)}
        summary_root = {
            "valueId": "root",
            "children": [{
                "valueId": "fab-1",
                "description": "FloatingActionButton",
                "widgetRuntimeType": "FloatingActionButton",
            }],
        }
        layout_root = {
            "valueId": "root",
            "size": {"width": "800.0", "height": "600.0"},
            "children": [{
                "valueId": "fab-1",
                "description": "FloatingActionButton",
                "widgetRuntimeType": "FloatingActionButton",
                "size": {"width": "56.0", "height": "56.0"},
                "renderObject": {
                    "properties": [{
                        "name": "parentData",
                        "description": "<none> (can use size)",
                    }]
                },
            }],
        }
        debug_dump = (
            ' └FloatingActionButton(tooltip: "Increment", '
            "dependencies: [Directionality])"
        )

        elements = bridge._flutter_inspector_elements_from_trees(
            summary_root, layout_root, window, debug_dump
        )

        self.assertEqual(elements[0]["text"], "Increment")
        self.assertEqual(elements[0]["widget_type"], "FloatingActionButton")
        self.assertEqual(elements[0]["source_field"], "tooltip")
        self.assertEqual(
            elements[0]["rect"], {"x": 728, "y": 560, "w": 56, "h": 56}
        )
        self.assertEqual(
            elements[0]["rect_source"], "material-default-fab-location"
        )

    def test_inspect_filters_by_text(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        stdout = (
            "AXButton\t\tSave\tbutton\t\ttrue\t150\t260\t80\t40\n"
            "AXStaticText\t\tReady\t\t\t\t120\t230\t60\t20\n"
        )
        with mock.patch.object(
            bridge, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge, "_run_osascript_capture", return_value=(stdout, None)
        ):
            result = bridge._macos_inspect("demo_app", {"text": "ready"})

        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["elements"][0]["text"], "Ready")

    def test_inspect_merges_flutter_inspector_text_fallback(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        flutter_element = {
            "type": "flutter_widget",
            "text": "Button taps recorded",
            "label": "Button taps recorded",
            "description": "Text",
            "value": "",
            "role": "",
            "subrole": "",
            "enabled": None,
            "rect": {"x": 1, "y": 2, "w": 3, "h": 4},
            "coordinate_space": "app-window-points",
            "source": "flutter-inspector",
        }
        with mock.patch.object(
            bridge, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge, "_run_osascript_capture", return_value=("", None)
        ), mock.patch.object(
            bridge,
            "_flutter_inspector_elements",
            return_value=([flutter_element], None),
        ):
            result = bridge._macos_inspect(
                "demo_app",
                {"text": "button taps"},
                vm_service_url="http://127.0.0.1:123/abc=/",
            )

        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["elements"][0]["source"], "flutter-inspector")

    def test_tap_text_uses_first_matching_element_center(self):
        element = {
            "type": "button",
            "text": "Increment",
            "enabled": True,
            "rect": {"x": 10, "y": 20, "w": 80, "h": 40},
        }
        with mock.patch.object(
            bridge,
            "_macos_inspect",
            return_value={"elements": [element], "match_count": 1},
        ), mock.patch.object(
            bridge,
            "_macos_tap_coordinates",
            return_value={
                "action": "tap",
                "x": 50,
                "y": 40,
                "coordinate_space": "app-window-points",
            },
        ) as tap_coordinates:
            result = bridge._macos_tap_text("demo_app", "Increment")

        tap_coordinates.assert_called_once_with("demo_app", 50.0, 40.0)
        self.assertEqual(result["text"], "Increment")
        self.assertTrue(result["element_found"])

    def test_wait_times_out_when_text_never_appears(self):
        with mock.patch.object(
            bridge,
            "_macos_inspect",
            return_value={"elements": [], "match_count": 0},
        ):
            result = bridge._macos_wait(
                "demo_app", {"text": "Ready", "timeout_ms": 1}
            )

        self.assertEqual(result["code"], "TIMEOUT")


class UiAutomationValidationTests(unittest.TestCase):
    def test_validates_coordinate_tap(self):
        parsed, error = bridge.validate_ui_action("tap", {"x": 12, "y": 34})

        self.assertIsNone(error)
        self.assertEqual(parsed, {"x": 12, "y": 34})

    def test_rejects_mixed_tap_selector_modes(self):
        parsed, error = bridge.validate_ui_action(
            "tap", {"x": 12, "y": 34, "text": "Sign in"}
        )

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "INVALID_BODY")

    def test_rejects_unknown_press_key(self):
        parsed, error = bridge.validate_ui_action("press", {"key": "F13"})

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "UNKNOWN_KEY")

    def test_accepts_modifier_press_key(self):
        parsed, error = bridge.validate_ui_action(
            "press", {"key": "command+r"}
        )

        self.assertIsNone(error)
        self.assertEqual(parsed, {"key": "command+r"})

    def test_accepts_modifier_press_key_with_spaces(self):
        parsed, error = bridge.validate_ui_action(
            "press", {"key": "command + r"}
        )

        self.assertIsNone(error)
        self.assertEqual(parsed, {"key": "command+r"})

    def test_accepts_single_alpha_press_key(self):
        parsed, error = bridge.validate_ui_action("press", {"key": "a"})

        self.assertIsNone(error)
        self.assertEqual(parsed, {"key": "a"})

    def test_rejects_modifier_only_press_key(self):
        parsed, error = bridge.validate_ui_action(
            "press", {"key": "command+shift"}
        )

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "UNKNOWN_KEY")

    def test_rejects_empty_press_key_segment(self):
        parsed, error = bridge.validate_ui_action(
            "press", {"key": "command++r"}
        )

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "UNKNOWN_KEY")

    def test_rejects_null_bytes_in_text(self):
        parsed, error = bridge.validate_ui_action(
            "type", {"text": "bad\x00text"}
        )

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "INVALID_BODY")

    def test_validates_scroll_delta(self):
        parsed, error = bridge.validate_ui_action(
            "scroll", {"dx": -25, "dy": 100}
        )

        self.assertIsNone(error)
        self.assertEqual(parsed, {"dx": -25, "dy": 100})

    def test_validates_scroll_edge(self):
        parsed, error = bridge.validate_ui_action(
            "scroll", {"edge": "bottom"}
        )

        self.assertIsNone(error)
        self.assertEqual(parsed, {"edge": "bottom"})

    def test_rejects_scroll_edge_and_delta(self):
        parsed, error = bridge.validate_ui_action(
            "scroll", {"edge": "bottom", "dy": 100}
        )

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "INVALID_BODY")

    def test_rejects_zero_scroll_delta(self):
        parsed, error = bridge.validate_ui_action("scroll", {"dy": 0})

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "INVALID_BODY")

    def test_validates_empty_inspect_body(self):
        parsed, error = bridge.validate_ui_action("inspect", {})

        self.assertIsNone(error)
        self.assertEqual(parsed, {})

    def test_validates_inspect_selector_body(self):
        parsed, error = bridge.validate_ui_action(
            "inspect", {"text": "Settings"}
        )

        self.assertIsNone(error)
        self.assertEqual(parsed, {"text": "Settings"})

    def test_rejects_inspect_with_both_text_and_key(self):
        parsed, error = bridge.validate_ui_action(
            "inspect", {"text": "Settings", "key": "settingsButton"}
        )

        self.assertIsNone(parsed)
        self.assertEqual(error["code"], "INVALID_BODY")

    def test_validates_wait_timeout(self):
        parsed, error = bridge.validate_ui_action(
            "wait", {"text": "Welcome", "timeout_ms": 1000}
        )

        self.assertIsNone(error)
        self.assertEqual(parsed["timeout_ms"], 1000)


class UiAutomationUnavailableTests(unittest.TestCase):
    class State:
        def __init__(self, automation, live_process=True):
            self._automation = automation
            self._live_process = live_process

        def has_live_process(self):
            return self._live_process

        def ui_automation_status(self):
            return self._automation

    def automation(self, ready, backend, reason, missing=None):
        return {
            "ready": ready,
            "backend": backend,
            "missing": missing or [],
            "actions": bridge.unsupported_actions(reason),
        }

    def test_missing_host_tool_reports_unsupported_target(self):
        state = self.State(
            self.automation(
                ready=False,
                backend="ios-simulator",
                reason="Required host UI automation tool is unavailable",
                missing=["xcrun"],
            )
        )

        error, status = bridge.ui_action_unavailable_error(
            state, "tap", {"x": 1, "y": 2}
        )

        self.assertEqual(status, 501)
        self.assertEqual(error["code"], "UNSUPPORTED_TARGET")
        self.assertEqual(error["x"], 1)
        self.assertEqual(error["y"], 2)

    def test_live_process_without_vm_service_reports_ui_not_ready(self):
        state = self.State(
            self.automation(
                ready=False,
                backend="macos-desktop",
                reason="Flutter process exists, but UI automation is not ready yet",
            )
        )

        error, status = bridge.ui_action_unavailable_error(
            state, "tap", {"x": 1, "y": 2}
        )

        self.assertEqual(status, 409)
        self.assertEqual(error["code"], "UI_NOT_READY")

    def test_key_tap_rejected_when_backend_does_not_advertise_key_selector(self):
        state = self.State({
            "ready": True,
            "backend": "macos-desktop",
            "missing": [],
            "actions": bridge._backend_action_capabilities("macos-desktop"),
        })

        error, status = bridge.ui_action_unavailable_error(
            state, "tap", {"key": "loginButton"}
        )

        self.assertEqual(status, 501)
        self.assertEqual(error["code"], "UNSUPPORTED_TARGET")
        self.assertIn("Selector 'key'", error["error"])

    def test_dispatch_uses_provided_automation_status(self):
        state = mock.Mock()
        state.ui_automation_status.side_effect = AssertionError(
            "status should be provided by caller"
        )

        result, status = bridge.dispatch_ui_action(
            state,
            "tap",
            {"x": 1, "y": 2},
            automation={"backend": "unsupported"},
        )

        state.ui_automation_status.assert_not_called()
        self.assertEqual(status, 501)
        self.assertEqual(result["code"], "UNSUPPORTED_TARGET")


class RecordingFlutterCtl(flutterctl.FlutterCtl):
    def __init__(self):
        self.calls = []
        self.bridge_url = "http://example.invalid"
        self.token = "token"

    def _request(self, method, path, body=None, accept_binary=False, timeout=30):
        self.calls.append((method, path, body, accept_binary, timeout))
        return {"ok": True}


class FlutterCtlUiCommandTests(unittest.TestCase):
    def test_tap_serializes_coordinates(self):
        ctl = RecordingFlutterCtl()

        ctl.tap(x=1, y=2)

        self.assertEqual(ctl.calls[-1][0], "POST")
        self.assertEqual(ctl.calls[-1][1], "/tap")
        self.assertEqual(ctl.calls[-1][2], {"x": 1, "y": 2})

    def test_tap_rejects_partial_coordinates_client_side(self):
        ctl = RecordingFlutterCtl()

        with self.assertRaises(ValueError):
            ctl.tap(x=1)

        self.assertEqual(ctl.calls, [])

    def test_wait_serializes_timeout_and_selector(self):
        ctl = RecordingFlutterCtl()

        ctl.wait(text="Ready", timeout_ms=2500)

        self.assertEqual(ctl.calls[-1][1], "/wait")
        self.assertEqual(
            ctl.calls[-1][2], {"timeout_ms": 2500, "text": "Ready"}
        )


class BridgeHttpUiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state = bridge.BridgeState(
            token="secret",
            project_dir=self.tmpdir.name,
            device_id="macos",
            target="lib/main.dart",
            flutter_path="flutter",
            run_args="",
        )
        bridge.FlutterBridgeHandler.bridge_state = self.state
        self.server = bridge.ThreadingHTTPServer(
            ("127.0.0.1", 0), bridge.FlutterBridgeHandler
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def request(self, path, body=None, token="secret"):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body).encode()
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method="POST",
        )

    def test_auth_required_for_ui_action(self):
        req = self.request("/tap", {"x": 1, "y": 2}, token=None)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 401)

    def test_ui_action_reports_no_running_app(self):
        req = self.request("/tap", {"x": 1, "y": 2})

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 409)
        payload = json.loads(ctx.exception.read().decode())
        self.assertEqual(payload["code"], "NO_APP_RUNNING")
        self.assertEqual(payload["x"], 1)
        self.assertEqual(payload["y"], 2)
        self.assertIn("elapsed_ms", payload)

    def test_validation_error_reports_elapsed_time(self):
        req = self.request("/press", {"key": "F13"})

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read().decode())
        self.assertEqual(payload["code"], "UNKNOWN_KEY")
        self.assertIn("elapsed_ms", payload)

    def test_launch_requires_explicit_device(self):
        req = self.request("/launch", {})

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read().decode())
        self.assertIn("Provide 'device' in request body", payload["error"])

    def test_ui_action_reports_ui_not_ready_while_launching(self):
        class _MockProcess:
            def poll(self):
                return None

        # Pre-populate caches so subprocess calls are skipped inside the
        # test env where flutter/osascript are not installed.
        self.state._devices_cache = [
            {"id": "macos", "name": "macOS", "targetPlatform": "darwin",
             "emulator": False},
        ]
        self.state._devices_cache_time = time.time()
        self.state._devices_cache_error = None
        self.state._tools_cache = {"macos-desktop": {"osascript": True}}

        with self.state.subprocess_lock:
            self.state.process = _MockProcess()
        self.state._status = "launching"
        self.state.vm_service_url = None

        req = self.request("/tap", {"x": 5, "y": 10})

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 409)
        payload = json.loads(ctx.exception.read().decode())
        self.assertEqual(payload["code"], "UI_NOT_READY")
        self.assertIn("elapsed_ms", payload)


if __name__ == "__main__":
    unittest.main()
