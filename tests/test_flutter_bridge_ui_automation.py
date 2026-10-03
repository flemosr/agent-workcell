import importlib.util
import io
import json
import pathlib
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = load_module("flutter_bridge", "scripts/flutter-bridge.py")
import flutter_bridge_lib.ios as bridge_ios
import flutter_bridge_lib.macos as bridge_macos

flutterctl = load_module(
    "flutterctl", "sandbox/flutter-tools/flutterctl.py"
)
package_config_guard = load_module(
    "package_config_guard", "sandbox/flutter-tools/package_config_guard.py"
)


def subprocess_result(returncode=0, stdout="", stderr=""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def ios_device(device_id="8F0F", name="iPhone 15"):
    return {
        "id": device_id,
        "name": name,
        "targetPlatform": "ios",
        "emulator": True,
        "sdk": "iOS 17 Simulator",
    }


def simulator_window(x, y, width, height):
    return {
        "window_id": 42,
        "pid": 123,
        "owner_name": "Simulator",
        "name": "iPhone 17",
        "bounds": {"x": x, "y": y, "width": width, "height": height},
    }


def logical_snapshot(width, height, elements, **metadata):
    return {
        "coordinate_space": "flutter-logical-points",
        "root_size": {"width": width, "height": height},
        "elements": elements,
        **metadata,
    }


def content_match_result(rect, **metadata):
    return {
        "best_match": {"simulator_window_rect_estimate": dict(rect)},
        **metadata,
    }


class PackageConfigGuardTests(unittest.TestCase):
    def test_host_bridge_detects_missing_package_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            dart_tool = project / ".dart_tool"
            dart_tool.mkdir()
            (dart_tool / "package_config.json").write_text(json.dumps({
                "configVersion": 2,
                "packages": [{
                    "name": "flutter",
                    "rootUri": "file:///definitely/missing/flutter",
                    "packageUri": "lib/",
                }],
            }))

            invalid = bridge._package_config_invalid_roots(str(project))

        self.assertEqual(len(invalid), 1)
        self.assertIn("flutter", invalid[0])

    def test_container_guard_detects_host_package_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            (project / "pubspec.yaml").write_text("name: demo\n")
            dart_tool = project / ".dart_tool"
            dart_tool.mkdir()
            (dart_tool / "package_config.json").write_text(json.dumps({
                "configVersion": 2,
                "packages": [{
                    "name": "flutter_lints",
                    "rootUri": "file:///Users/me/.pub-cache/flutter_lints",
                    "packageUri": "lib/",
                }],
            }))

            self.assertTrue(
                package_config_guard.package_config_has_foreign_paths(project)
            )

    def test_container_guard_accepts_container_package_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            (project / "pubspec.yaml").write_text("name: demo\n")
            dart_tool = project / ".dart_tool"
            dart_tool.mkdir()
            (dart_tool / "package_config.json").write_text(json.dumps({
                "configVersion": 2,
                "packages": [{
                    "name": "flutter",
                    "rootUri": "file:///opt/flutter-sdk/packages/flutter",
                    "packageUri": "lib/",
                }],
            }))

            self.assertFalse(
                package_config_guard.package_config_has_foreign_paths(project)
            )


class UiAutomationCapabilityTests(unittest.TestCase):
    def test_classifies_devices(self):
        cases = [
            ("classifies_ios_simulator", ios_device(), {
                "backend": "ios-simulator", "target_platform": "ios",
                "device_kind": "simulator",
            }),
            ("classifies_macos_desktop", {
                "id": "macos", "name": "macOS",
                "targetPlatform": "darwin", "emulator": False,
            }, {
                "backend": "macos-desktop", "target_platform": "macos",
                "device_kind": "desktop",
            }),
            ("classifies_android_as_unsupported", {
                "id": "emulator-5554", "name": "Android SDK built for arm64",
                "targetPlatform": "android-arm64", "emulator": True,
            }, {"backend": "unsupported", "target_platform": "android"}),
        ]
        for name, metadata, expected in cases:
            with self.subTest(case=name):
                target = bridge.classify_device(metadata["id"], metadata)
                for field, value in expected.items():
                    self.assertEqual(target[field], value)

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
            status["actions"]["tap"]["selectors"],
            ["coordinates", "text", "key"],
        )
        self.assertEqual(
            status["actions"]["tap"]["coordinate_space"],
            "app-window-points",
        )
        self.assertTrue(status["actions"]["press"]["supported"])
        self.assertTrue(status["actions"]["type"]["supported"])
        self.assertTrue(status["actions"]["scroll"]["supported"])
        self.assertEqual(
            status["actions"]["scroll"]["moves"], ["top", "up", "down"]
        )
        self.assertTrue(status["actions"]["inspect"]["supported"])
        self.assertEqual(
            status["actions"]["inspect"]["selectors"], ["text", "key"]
        )
        self.assertTrue(status["actions"]["wait"]["supported"])
        self.assertEqual(
            status["actions"]["wait"]["selectors"], ["text", "key"]
        )

    def test_screenshot_status_reports_macos_app_window_capture(self):
        target = bridge.classify_device(
            "macos", {"id": "macos", "targetPlatform": "darwin"}
        )

        status = bridge.build_screenshot_status(
            bridge_status="running",
            has_process=True,
            device_id="macos",
            target=target,
        )

        self.assertTrue(status["supported"])
        self.assertTrue(status["available"])
        self.assertEqual(status["method"], "screencapture-window")
        self.assertEqual(status["scope"], "app-window-only")
        self.assertIn("macOS Screen Recording permission", status["requires"])

    def test_screenshot_status_reports_ios_mobile_capture(self):
        target = bridge.classify_device("8F0F", ios_device())

        status = bridge.build_screenshot_status(
            bridge_status="running",
            has_process=True,
            device_id="8F0F",
            target=target,
        )

        self.assertTrue(status["supported"])
        self.assertTrue(status["available"])
        self.assertEqual(status["method"], "flutter screenshot")
        self.assertEqual(status["scope"], "device-screen")

    def test_status_reports_ios_inspect_and_wait_capabilities(self):
        target = bridge.classify_device("8F0F", ios_device())

        status = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=True,
            device_id="8F0F",
            target=target,
            tools={"xcrun": True, "osascript": True, "screencapture": True},
        )

        self.assertTrue(status["ready"])
        self.assertEqual(status["backend"], "ios-simulator")
        self.assertEqual(status["coordinate_space"], "simulator-window-points")
        self.assertEqual(
            status["tools"],
            {"xcrun": True, "osascript": True, "screencapture": True},
        )
        self.assertEqual(status["permissions"], {"accessibility": "unknown"})
        self.assertTrue(status["actions"]["tap"]["supported"])
        self.assertEqual(
            status["actions"]["tap"]["selectors"],
            ["coordinates", "text", "key"],
        )
        self.assertEqual(
            status["actions"]["tap"]["coordinate_space"],
            "simulator-window-points",
        )
        self.assertTrue(status["actions"]["type"]["supported"])
        self.assertEqual(
            status["actions"]["type"]["method"],
            "host-keystroke-to-simulator",
        )
        self.assertEqual(
            status["actions"]["type"]["requires"], ["focused text field"]
        )
        self.assertTrue(status["actions"]["press"]["supported"])
        self.assertEqual(
            status["actions"]["press"]["method"],
            "host-keypress-to-simulator",
        )
        self.assertTrue(status["actions"]["scroll"]["supported"])
        self.assertEqual(
            status["actions"]["scroll"]["method"],
            "host-keypress-to-simulator",
        )
        self.assertEqual(
            status["actions"]["scroll"]["moves"], ["top", "up", "down"]
        )
        self.assertEqual(
            status["actions"]["scroll"]["scroll_model"],
            "key-approximation",
        )
        self.assertTrue(status["actions"]["inspect"]["supported"])
        self.assertEqual(
            status["actions"]["inspect"]["selectors"], ["text", "key"]
        )
        self.assertEqual(
            status["actions"]["inspect"]["coordinate_space"],
            "flutter-logical-points",
        )
        self.assertTrue(status["actions"]["wait"]["supported"])
        self.assertEqual(
            status["actions"]["wait"]["selectors"], ["text", "key"]
        )

    def test_ios_screen_error_disables_coordinate_tap_capability(self):
        target = bridge.classify_device("8F0F", ios_device())
        status = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=True,
            device_id="8F0F",
            target=target,
            tools={"xcrun": True, "screencapture": True},
        )
        status["screen"] = {"error": "no visible Simulator window found"}

        bridge._disable_ios_window_dependent_actions_when_unavailable(status)

        self.assertFalse(status["actions"]["tap"]["supported"])
        self.assertEqual(status["actions"]["tap"]["selectors"], [])
        self.assertIn(
            "Simulator window unavailable",
            status["actions"]["tap"]["reason"],
        )
        self.assertTrue(status["actions"]["inspect"]["supported"])
        self.assertTrue(status["actions"]["wait"]["supported"])

    def test_ios_missing_osascript_disables_type_press_and_scroll(self):
        target = bridge.classify_device("8F0F", ios_device())
        status = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=True,
            device_id="8F0F",
            target=target,
            tools={"xcrun": True, "osascript": False, "screencapture": True},
        )

        bridge._disable_ios_host_keyboard_actions_when_unavailable(status)

        self.assertFalse(status["actions"]["type"]["supported"])
        self.assertFalse(status["actions"]["press"]["supported"])
        self.assertFalse(status["actions"]["scroll"]["supported"])
        self.assertIn("osascript", status["actions"]["type"]["reason"])
        self.assertTrue(status["actions"]["tap"]["supported"])
        self.assertTrue(status["actions"]["inspect"]["supported"])
        self.assertTrue(status["actions"]["wait"]["supported"])

    def test_ios_missing_screencapture_disables_selector_taps_only(self):
        target = bridge.classify_device("8F0F", ios_device())
        status = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=True,
            device_id="8F0F",
            target=target,
            tools={"xcrun": True, "screencapture": False},
        )

        bridge._disable_ios_content_match_actions_when_unavailable(status)

        self.assertTrue(status["actions"]["tap"]["supported"])
        self.assertEqual(status["actions"]["tap"]["selectors"], ["coordinates"])
        self.assertIn(
            "screencapture", status["actions"]["tap"]["selector_reason"]
        )
        self.assertTrue(status["actions"]["inspect"]["supported"])
        self.assertTrue(status["actions"]["wait"]["supported"])

    def test_status_reports_ios_actions_unverified_without_xcrun(self):
        target = bridge.classify_device("8F0F", ios_device())

        status = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=True,
            device_id="8F0F",
            target=target,
            tools={"xcrun": False},
        )

        self.assertFalse(status["ready"])
        self.assertFalse(status["actions"]["inspect"]["supported"])
        self.assertIn(
            "Required host UI automation tool",
            status["actions"]["inspect"]["reason"],
        )

    def test_ios_simulator_probe_reports_missing_xcrun(self):
        with mock.patch.object(bridge.shutil, "which", return_value=None):
            result = bridge.ios_simulator_probe("8F0F")

        self.assertFalse(result["available"])
        self.assertEqual(result["xcrun"], None)
        self.assertFalse(result["input_backend"]["coordinate_tap"]["viable"])
        self.assertIn(
            "xcrun", result["input_backend"]["coordinate_tap"]["reason"]
        )

    def test_ios_simulator_probe_parses_fixed_simctl_help(self):
        def fake_run(command, capture_output, text, timeout):
            self.assertTrue(capture_output)
            self.assertTrue(text)
            stdout = ""
            if command[-2:] == ["simctl", "help"]:
                stdout = "Usage: simctl\n    io\n    ui\n"
            elif command[-2:] in (["help", "io"], ["io", "help"]):
                stdout = "Usage: simctl io <device> screenshot\n"
            elif command[-2:] in (["help", "ui"], ["ui", "help"]):
                stdout = "Usage: simctl ui <device> appearance|content_size\n"
            elif command[-4:] == ["list", "devices", "booted", "--json"]:
                stdout = '{"devices":{}}'
            return subprocess_result(stdout=stdout)

        with mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge.subprocess, "run", side_effect=fake_run
        ):
            result = bridge.ios_simulator_probe("8F0F")

        self.assertTrue(result["available"])
        self.assertTrue(result["features"]["simctl_io_subcommand"])
        self.assertTrue(result["features"]["simctl_ui_subcommand"])
        self.assertFalse(result["features"]["mentions_touch_or_tap"])
        self.assertFalse(result["features"]["mentions_keyboard_or_text"])
        self.assertFalse(result["input_backend"]["coordinate_tap"]["viable"])
        self.assertFalse(result["input_backend"]["text_entry"]["viable"])
        self.assertEqual(
            result["commands"]["simctl_io_help"]["command"],
            ["/usr/bin/xcrun", "simctl", "io", "help"],
        )
        self.assertEqual(
            result["commands"]["selected_screenshot"]["command"][:5],
            ["/usr/bin/xcrun", "simctl", "io", "8F0F", "screenshot"],
        )

    def test_screenshot_status_does_not_depend_on_ui_automation_readiness(self):
        target = bridge.classify_device(
            "macos", {"id": "macos", "targetPlatform": "darwin"}
        )

        screenshot = bridge.build_screenshot_status(
            bridge_status="running",
            has_process=True,
            device_id="macos",
            target=target,
        )
        ui_automation = bridge.build_ui_automation_status(
            bridge_status="running",
            has_process=True,
            has_vm_service=False,
            device_id="macos",
            target=target,
            tools={"osascript": True},
        )

        self.assertTrue(screenshot["supported"])
        self.assertTrue(screenshot["available"])
        self.assertFalse(ui_automation["ready"])

    def test_screenshot_status_reports_target_dependent_when_none_selected(self):
        target = bridge.classify_device(None, None)

        status = bridge.build_screenshot_status(
            bridge_status="idle",
            has_process=False,
            device_id=None,
            target=target,
        )

        self.assertIsNone(status["supported"])
        self.assertFalse(status["available"])
        self.assertEqual(
            status["supported_targets"]["macos"]["method"],
            "screencapture-window",
        )
        self.assertEqual(
            status["supported_targets"]["macos"]["scope"],
            "app-window-only",
        )
        self.assertIn("No target device selected", status["reason"])


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
            bridge_macos, "_macos_get_process_id", return_value=(123, None)
        ), mock.patch.object(
            bridge_macos, "_macos_coregraphics_windows", return_value=[]
        ):
            window, error = bridge._macos_get_app_window_info("demo_app")

        self.assertIsNone(window)
        self.assertIn("no visible app window", error)

    def test_filters_ios_simulator_window_candidates(self):
        windows = [
            {
                "pid": 1,
                "window_id": 2,
                "owner_name": "Simulator",
                "name": "iPhone 17",
                "layer": 0,
                "onscreen": True,
                "alpha": 1,
                "bounds": (10, 20, 300, 600),
            },
            {
                "pid": 3,
                "window_id": 4,
                "owner_name": "Terminal",
                "name": "shell",
                "layer": 0,
                "onscreen": True,
                "alpha": 1,
                "bounds": (0, 0, 500, 500),
            },
        ]
        with mock.patch.object(
            bridge_ios, "_macos_coregraphics_windows", return_value=windows
        ):
            result = bridge._ios_simulator_window_candidates()

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["candidates"][0]["owner_name"], "Simulator")
        self.assertEqual(result["candidates"][0]["bounds"]["height"], 600)

    def test_ios_first_simulator_window_prefers_matching_device_name(self):
        candidates = {
            "candidates": [
                {
                    "window_id": 1,
                    "owner_name": "Simulator",
                    "name": "iPad Pro",
                    "bounds": {"x": 0, "y": 0, "width": 800, "height": 1000},
                },
                {
                    "window_id": 2,
                    "owner_name": "Simulator",
                    "name": "iPhone 17",
                    "bounds": {"x": 0, "y": 0, "width": 456, "height": 972},
                },
            ],
            "count": 2,
        }
        with mock.patch.object(
            bridge_ios, "_ios_simulator_window_candidates", return_value=candidates
        ):
            window, error = bridge._ios_first_simulator_window("iPhone 17")

        self.assertIsNone(error)
        self.assertEqual(window["window_id"], 2)
        self.assertEqual(window["selection"], "device-name-match")

    def test_ios_first_simulator_window_rejects_ambiguous_unmatched_device(self):
        candidates = {
            "candidates": [
                {
                    "window_id": 1,
                    "name": "iPad Pro",
                    "bounds": {"x": 0, "y": 0, "width": 800, "height": 1000},
                },
                {
                    "window_id": 2,
                    "name": "iPhone 17",
                    "bounds": {"x": 0, "y": 0, "width": 456, "height": 972},
                },
            ],
            "count": 2,
        }
        with mock.patch.object(
            bridge_ios, "_ios_simulator_window_candidates", return_value=candidates
        ):
            window, error = bridge._ios_first_simulator_window("iPhone SE")

        self.assertIsNone(window)
        self.assertIn("matched device 'iPhone SE'", error)

    def test_png_dimensions_reads_png_header(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            f.write(
                b"\x89PNG\r\n\x1a\n"
                b"\x00\x00\x00\rIHDR"
                b"\x00\x00\x04\xb0"
                b"\x00\x00\t\x30"
            )
            f.flush()

            dimensions = bridge._png_dimensions(f.name)

        self.assertEqual(dimensions, {"width": 1200, "height": 2352})

    def test_png_decode_rgb_reads_unfiltered_rgb_png(self):
        width = 2
        height = 1
        pixels = bytes((10, 20, 30, 40, 50, 60))
        raw = b"\x00" + pixels
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

        def chunk(name, data):
            return (
                struct.pack(">I", len(data)) + name + data +
                struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
            )

        png = (
            b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw)) +
            chunk(b"IEND", b"")
        )
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            f.write(png)
            f.flush()

            image, error = bridge._png_decode_rgb(f.name)

        self.assertIsNone(error)
        self.assertEqual(image["width"], width)
        self.assertEqual(image["height"], height)
        self.assertEqual(image["pixels"], pixels)

    def test_ios_host_window_content_match_estimates_device_rect(self):
        native_width = 4
        native_height = 6
        native_pixels = bytearray()
        for y in range(native_height):
            for x in range(native_width):
                native_pixels.extend((x * 40, y * 30, (x + y) * 20))
        native = {
            "width": native_width,
            "height": native_height,
            "pixels": bytes(native_pixels),
        }

        host_width = 10
        host_height = 14
        host_pixels = bytearray([240] * host_width * host_height * 3)
        crop_x = 1
        crop_y = 1
        crop_width = 8
        crop_height = 12
        for y in range(crop_height):
            for x in range(crop_width):
                source = bridge._rgb_at(
                    native,
                    int((x + 0.5) / crop_width * native_width),
                    int((y + 0.5) / crop_height * native_height),
                )
                i = ((crop_y + y) * host_width + crop_x + x) * 3
                host_pixels[i:i + 3] = bytes(source)
        host = {
            "width": host_width,
            "height": host_height,
            "pixels": bytes(host_pixels),
        }
        window = {
            "bounds": {"x": 100, "y": 200, "width": 8, "height": 12}
        }

        result = bridge._estimate_ios_host_window_content_match(
            native, host, window
        )

        self.assertTrue(result["available"])
        self.assertLess(result["score_mean_abs_rgb"], 1)
        self.assertEqual(
            result["best_match"]["simulator_window_rect_estimate"],
            {
                "x": 0,
                "y": 0,
                "w": 8,
                "h": 12,
                "coordinate_space": "simulator-window-points",
            },
        )

    def test_ios_coordinate_map_reports_mapping_estimates(self):
        window = simulator_window(100, 200, 456, 972)
        inspector = logical_snapshot(402, 874, [{
            "key": "new_item_button",
            "rect": {"x": 16, "y": 134, "w": 282, "h": 56},
            "coordinate_space": "flutter-logical-points",
        }])
        screenshot = {
            "returncode": 0,
            "image": {"width": 1206, "height": 2622, "size_bytes": 123},
        }
        with mock.patch.object(bridge.shutil, "which", return_value="/usr/bin/xcrun"), \
                mock.patch.object(
                    bridge_ios, "_ios_simulator_screen_metadata",
                    return_value={"simulator_window": window},
                ), mock.patch.object(
                    bridge_ios, "_run_simctl_screenshot_probe",
                    return_value=screenshot,
                ), mock.patch.object(
                    bridge_ios, "_run_screencapture_window_probe", return_value={},
                ), mock.patch.object(
                    bridge_ios, "_ios_simulator_accessibility_snapshot", return_value={},
                ), mock.patch.object(
                    bridge_ios, "_flutter_inspector_snapshot",
                    return_value=(inspector, None),
                ), mock.patch.object(
                    bridge_ios,
                    "_ios_host_window_content_match_probe",
                    return_value=content_match_result(
                        {"x": 34, "y": 70, "w": 393, "h": 854},
                        available=True,
                    ),
                ):
            result = bridge.ios_coordinate_map(
                "http://127.0.0.1:123/abc=/",
                device_id="8F0F",
                device_name="iPhone 17",
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["device_id"], "8F0F")
        self.assertEqual(result["device_name"], "iPhone 17")
        self.assertEqual(
            result["coordinate_spaces"]["tap"], "simulator-window-points"
        )
        self.assertEqual(
            result["mapping"]["flutter_logical_to_native_pixels"]["scale_x"],
            3,
        )
        self.assertEqual(
            result["mapping"]["flutter_logical_to_native_pixels"]["scale_y"],
            3,
        )
        self.assertEqual(
            result["mapping"]["flutter_logical_to_window_points_estimate"]["model"],
            "full-window-linear-estimate",
        )
        self.assertEqual(result["elements"][0]["center"], {"x": 157, "y": 162})
        self.assertAlmostEqual(
            result["elements"][0]["estimated_simulator_window_center"]["x"],
            178.08955223880596,
            places=3,
        )
        self.assertAlmostEqual(
            result["elements"][0]["estimated_simulator_window_center"]["y"],
            180.16475972540046,
            places=3,
        )
        self.assertEqual(
            result["mapping"]["flutter_logical_to_window_points_matched_estimate"]["model"],
            "sampled-image-match",
        )
        self.assertAlmostEqual(
            result["elements"][0]["matched_simulator_window_center_estimate"]["x"],
            187.48507462686567,
            places=3,
        )
        self.assertAlmostEqual(
            result["elements"][0]["matched_simulator_window_center_estimate"]["y"],
            228.2929061784897,
            places=3,
        )

    def test_ios_coordinate_map_reports_logical_to_native_without_window(self):
        inspector = logical_snapshot(402, 874, [])
        screenshot = {
            "returncode": 0,
            "image": {"width": 1206, "height": 2622, "size_bytes": 123},
        }
        with mock.patch.object(bridge.shutil, "which", return_value="/usr/bin/xcrun"), \
                mock.patch.object(
                    bridge_ios, "_ios_simulator_screen_metadata",
                    return_value={"error": "no visible Simulator window found"},
                ), mock.patch.object(
                    bridge_ios, "_run_simctl_screenshot_probe",
                    return_value=screenshot,
                ), mock.patch.object(
                    bridge_ios, "_run_screencapture_window_probe", return_value={},
                ), mock.patch.object(
                    bridge_ios, "_ios_simulator_accessibility_snapshot", return_value={},
                ), mock.patch.object(
                    bridge_ios, "_flutter_inspector_snapshot",
                    return_value=(inspector, None),
                ):
            result = bridge.ios_coordinate_map("http://127.0.0.1:123/abc=/")

        self.assertEqual(
            result["mapping"]["flutter_logical_to_native_pixels"]["scale_x"],
            3,
        )
        self.assertEqual(
            result["mapping"]["flutter_logical_to_native_pixels"]["scale_y"],
            3,
        )
        self.assertNotIn(
            "flutter_logical_to_window_points_estimate",
            result["mapping"],
        )

    def test_ios_simulator_accessibility_snapshot_reports_local_frames(self):
        window = simulator_window(100, 200, 456, 972)
        stdout = (
            "AXWindow\t\tiPhone 17\t\t\ttrue\t100\t200\t456\t972\n"
            "AXGroup\t\tLCD\t\t\t\t105\t270\t446\t902\n"
        )
        with mock.patch.object(
            bridge_ios, "_ios_first_simulator_window", return_value=(window, None)
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/osascript"
        ), mock.patch.object(
            bridge_ios, "_run_osascript_capture", return_value=(stdout, None)
        ):
            result = bridge._ios_simulator_accessibility_snapshot("iPhone 17")

        self.assertEqual(result["element_count"], 2)
        self.assertEqual(result["raw_line_count"], 2)
        self.assertEqual(result["parsed_element_count"], 2)
        self.assertEqual(
            result["elements"][0]["coordinate_space"],
            "simulator-window-points",
        )
        self.assertEqual(
            result["elements"][1]["rect"],
            {"x": 5, "y": 70, "w": 446, "h": 902},
        )

    def test_ios_simulator_accessibility_snapshot_reports_unframed_sample(self):
        window = simulator_window(100, 200, 456, 972)
        stdout = "AXGroup\t\tContainer\t\t\t\t\t\t\t\n"
        with mock.patch.object(
            bridge_ios, "_ios_first_simulator_window", return_value=(window, None)
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/osascript"
        ), mock.patch.object(
            bridge_ios, "_run_osascript_capture", return_value=(stdout, None)
        ):
            result = bridge._ios_simulator_accessibility_snapshot("iPhone 17")

        self.assertEqual(result["raw_line_count"], 1)
        self.assertEqual(result["parsed_element_count"], 1)
        self.assertEqual(result["element_count"], 0)
        self.assertEqual(result["unframed_sample"][0]["label"], "Container")

    def test_screencapture_window_probe_reports_image_dimensions(self):
        window = simulator_window(100, 200, 456, 972)

        def fake_run_probe(command, timeout=8):
            output_path = command[-1]
            with open(output_path, "wb") as f:
                f.write(
                    b"\x89PNG\r\n\x1a\n"
                    b"\x00\x00\x00\rIHDR"
                    b"\x00\x00\x03\x90"
                    b"\x00\x00\x07\x98"
                )
            return {"command": command, "returncode": 0, "ok": True}

        with mock.patch.object(
            bridge.shutil, "which", return_value="/usr/sbin/screencapture"
        ), mock.patch.object(
            bridge_ios, "_run_probe_command", side_effect=fake_run_probe
        ):
            result = bridge._run_screencapture_window_probe(window)

        self.assertEqual(
            result["command"][:2], ["screencapture", "-x"]
        )
        self.assertEqual(result["image"]["width"], 912)
        self.assertEqual(result["image"]["height"], 1944)
        self.assertEqual(result["image"]["size_bytes"], 24)
        self.assertEqual(result["window"], window)

    def test_ios_coordinate_map_reports_missing_xcrun(self):
        with mock.patch.object(bridge.shutil, "which", return_value=None):
            result = bridge.ios_coordinate_map("http://127.0.0.1:123/abc=/")

        self.assertFalse(result["available"])
        self.assertIn("xcrun", result["error"])


class MacosBackendDispatchTests(unittest.TestCase):
    def setUp(self):
        cache_patch = mock.patch.dict(bridge._ios_tap_snapshot_cache, clear=True)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def test_scroll_dispatch_uses_backend_error_status(self):
        with mock.patch.object(
            bridge_macos,
            "_macos_press",
            return_value={"error": "osascript failed", "code": "BACKEND_ERROR"},
        ):
            result, status = bridge._macos_desktop_dispatch(
                "demo_app", "scroll", {"move": "down"}
            )

        self.assertEqual(status, 500)
        self.assertEqual(result["code"], "BACKEND_ERROR")

    def test_scroll_dispatch_reports_key_approximation(self):
        with mock.patch.object(
            bridge_macos,
            "_macos_press",
            return_value={"action": "press", "key": "pagedown"},
        ):
            result, status = bridge._macos_desktop_dispatch(
                "demo_app", "scroll", {"move": "down"}
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["action"], "scroll")
        self.assertEqual(result["move"], "down")
        self.assertEqual(result["dispatch"], "key")
        self.assertEqual(result["key"], "pagedown")
        self.assertEqual(result["scroll_model"], "key-approximation")

    def test_tap_coordinates_are_app_window_local_points(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        with mock.patch.object(
            bridge_macos, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge_macos, "_macos_post_mouse_click", return_value=None
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
            bridge_macos, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(bridge_macos, "_macos_post_mouse_click") as post_click:
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

    def test_extracts_flutter_inspector_key_with_app_window_rect(self):
        window = {"window_id": 4, "bounds": (100, 200, 800, 632)}
        summary_root = {
            "valueId": "root",
            "children": [{
                "valueId": "button-1",
                "description": "ElevatedButton-[<'add_item_button'>]",
                "widgetRuntimeType": "ElevatedButton",
            }],
        }
        layout_root = {
            "valueId": "root",
            "size": {"width": "800.0", "height": "600.0"},
            "children": [{
                "valueId": "button-1",
                "description": "ElevatedButton-[<'add_item_button'>]",
                "widgetRuntimeType": "ElevatedButton",
                "size": {"width": "96.0", "height": "48.0"},
                "parentData": {"offsetX": "680.0", "offsetY": "64.0"},
            }],
        }

        elements = bridge._flutter_inspector_elements_from_trees(
            summary_root, layout_root, window
        )

        self.assertEqual(elements[0]["key"], "add_item_button")
        self.assertEqual(elements[0]["text"], "")
        self.assertEqual(elements[0]["source_field"], "key")
        self.assertEqual(
            elements[0]["rect"], {"x": 680, "y": 96, "w": 96, "h": 48}
        )

    def test_extracts_key_from_flutter_diagnostics_property(self):
        node = {
            "valueId": "button-1",
            "description": "ElevatedButton",
            "widgetRuntimeType": "ElevatedButton",
            "properties": [{
                "name": "key",
                "description": "key: [<'add_item_button'>]",
            }],
        }

        key_info = bridge._flutter_key_info_from_node(node)

        self.assertEqual(key_info["key"], "add_item_button")
        self.assertEqual(key_info["widget_type"], "ElevatedButton")

    def test_extracts_semantics_identifier_with_global_rect(self):
        dump = """
SemanticsNode#0
 │ Rect.fromLTRB(0.0, 0.0, 1206.0, 2622.0)
 │
 └─SemanticsNode#1
   │ Rect.fromLTRB(0.0, 0.0, 402.0, 874.0) scaled by 3.0x
   │
   └─SemanticsNode#35
       Rect.fromLTRB(22.0, 576.0, 380.0, 632.0)
       actions: focus, tap
       flags: isTextField, isFocused, hasEnabledState, isEnabled
       identifier: "task_title_field"
       label: "Title"
       value: "Draft"
"""

        snapshot = bridge._flutter_semantics_snapshot_from_dump(dump)

        self.assertEqual(snapshot["root_size"], {"width": 402, "height": 874})
        self.assertEqual(len(snapshot["elements"]), 1)
        element = snapshot["elements"][0]
        self.assertEqual(element["key"], "task_title_field")
        self.assertEqual(element["semantics_identifier"], "task_title_field")
        self.assertEqual(
            element["rect"], {"x": 22, "y": 576, "w": 358, "h": 56}
        )
        self.assertEqual(element["label"], "Title")
        self.assertEqual(element["value"], "Draft")
        self.assertEqual(element["source"], "flutter-semantics")

    def test_extracts_semantics_identifier_in_overlay_with_root_rect(self):
        dump = """
SemanticsNode#0
 │ Rect.fromLTRB(0.0, 0.0, 1206.0, 2622.0)
 │
 └─SemanticsNode#1
   │ Rect.fromLTRB(0.0, 0.0, 402.0, 874.0) scaled by 3.0x
   │
   └─SemanticsNode#61
     │ Rect.fromLTRB(0.0, 0.0, 402.0, 874.0)
     │ flags: scopesRoute, namesRoute
     │
     └─SemanticsNode#62
       │ Rect.fromLTRB(0.0, 487.0, 402.0, 874.0)
       │ identifier: "new_task_sheet"
       │ label: "New task"
       │
       ├─SemanticsNode#63
       │ │ Rect.fromLTRB(22.0, 89.0, 380.0, 145.0)
       │ │ flags: isTextField
       │ │ identifier: "task_title_field"
       │ │
       │ └─SemanticsNode#64
       │     Rect.fromLTRB(0.0, 0.0, 358.0, 56.0)
       │
       └─SemanticsNode#67
         │ Rect.fromLTRB(22.0, 281.0, 380.0, 335.0)
         │ flags: isButton
         │ identifier: "add_task_button"
         │
         └─SemanticsNode#68
             Rect.fromLTRB(0.0, 0.0, 358.0, 54.0)
"""

        snapshot = bridge._flutter_semantics_snapshot_from_dump(dump)
        by_key = {element["key"]: element for element in snapshot["elements"]}

        self.assertEqual(snapshot["root_size"], {"width": 402, "height": 874})
        self.assertEqual(
            by_key["new_task_sheet"]["rect"],
            {"x": 0, "y": 487, "w": 402, "h": 387},
        )
        self.assertEqual(
            by_key["task_title_field"]["rect"],
            {"x": 22, "y": 576, "w": 358, "h": 56},
        )
        self.assertEqual(
            by_key["add_task_button"]["rect"],
            {"x": 22, "y": 768, "w": 358, "h": 54},
        )

    def test_keyed_element_without_text_tolerates_missing_offset(self):
        window = {"window_id": 4, "bounds": (100, 200, 800, 632)}
        summary_root = {
            "valueId": "root",
            "children": [{
                "valueId": "list-1",
                "description": "ListView-[<'todo_list'>]",
                "widgetRuntimeType": "ListView",
            }],
        }
        layout_root = {
            "valueId": "root",
            "size": {"width": "800.0", "height": "600.0"},
            "children": [{
                "valueId": "list-1",
                "description": "ListView-[<'todo_list'>]",
                "widgetRuntimeType": "ListView",
                "size": {"width": "768.0", "height": "480.0"},
            }],
        }

        elements = bridge._flutter_inspector_elements_from_trees(
            summary_root, layout_root, window
        )

        self.assertEqual(elements[0]["key"], "todo_list")
        self.assertEqual(elements[0]["rect_source"], "layout-offset")

    def test_does_not_double_count_reused_render_object_offset(self):
        window = {"window_id": 4, "bounds": (100, 200, 800, 632)}
        summary_root = {
            "valueId": "root",
            "children": [{
                "valueId": "button-1",
                "description": "IconButton-[<'delete_item_0'>]",
                "widgetRuntimeType": "IconButton",
            }],
        }
        shared_render_object = {
            "valueId": "render-shared",
            "properties": [{
                "name": "parentData",
                "description": "offset=Offset(0.0, 64.0) (can use size)",
            }],
        }
        layout_root = {
            "valueId": "root",
            "size": {"width": "800.0", "height": "600.0"},
            "children": [{
                "valueId": "expanded",
                "description": "Expanded",
                "renderObject": shared_render_object,
                "children": [{
                    "valueId": "focus",
                    "description": "Focus",
                    "renderObject": shared_render_object,
                    "children": [{
                        "valueId": "button-1",
                        "description": "IconButton-[<'delete_item_0'>]",
                        "widgetRuntimeType": "IconButton",
                        "size": {"width": "40.0", "height": "40.0"},
                        "parentData": {"offsetX": "680.0", "offsetY": "4.0"},
                    }],
                }],
            }],
        }

        elements = bridge._flutter_inspector_elements_from_trees(
            summary_root, layout_root, window
        )

        self.assertEqual(elements[0]["key"], "delete_item_0")
        self.assertEqual(
            elements[0]["rect"], {"x": 680, "y": 100, "w": 40, "h": 40}
        )

    def test_stacks_listview_children_without_explicit_offsets(self):
        window = {"window_id": 4, "bounds": (100, 200, 800, 632)}
        summary_root = {
            "valueId": "root",
            "children": [
                {
                    "valueId": "delete-0",
                    "description": "IconButton-[<'delete_item_0'>]",
                    "widgetRuntimeType": "IconButton",
                },
                {
                    "valueId": "delete-1",
                    "description": "IconButton-[<'delete_item_1'>]",
                    "widgetRuntimeType": "IconButton",
                },
                {
                    "valueId": "delete-2",
                    "description": "IconButton-[<'delete_item_2'>]",
                    "widgetRuntimeType": "IconButton",
                },
            ],
        }

        def row(value_id, key):
            return {
                "valueId": f"card-{key}",
                "description": "Card",
                "widgetRuntimeType": "Card",
                "size": {"width": "768.0", "height": "56.0"},
                "children": [{
                    "valueId": f"semantics-{key}",
                    "description": "Semantics",
                    "widgetRuntimeType": "Semantics",
                    "parentData": {"offsetX": "680.0", "offsetY": "4.0"},
                    "children": [{
                        "valueId": value_id,
                        "description": f"IconButton-[<'delete_item_{key}'>]",
                        "widgetRuntimeType": "IconButton",
                        "size": {"width": "40.0", "height": "40.0"},
                    }],
                }],
            }

        layout_root = {
            "valueId": "root",
            "size": {"width": "800.0", "height": "600.0"},
            "children": [{
                "valueId": "list",
                "description": "ListView-[<'todo_list'>]",
                "widgetRuntimeType": "ListView",
                "parentData": {"offsetX": "16.0", "offsetY": "140.0"},
                "size": {"width": "768.0", "height": "448.0"},
                "children": [
                    row("delete-0", "0"),
                    row("delete-1", "1"),
                    row("delete-2", "2"),
                ],
            }],
        }

        elements = bridge._flutter_inspector_elements_from_trees(
            summary_root, layout_root, window
        )

        rects_by_key = {
            element["key"]: element["rect"]
            for element in elements
        }
        self.assertEqual(rects_by_key["delete_item_0"]["y"], 176)
        self.assertEqual(rects_by_key["delete_item_1"]["y"], 232)
        self.assertEqual(rects_by_key["delete_item_2"]["y"], 288)

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
            bridge_macos, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge_macos, "_run_osascript_capture", return_value=(stdout, None)
        ):
            result = bridge._macos_inspect("demo_app", {"text": "ready"})

        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["elements"][0]["text"], "Ready")

    def test_inspect_filters_by_semantics_identifier(self):
        window = {"window_id": 4, "bounds": (100, 200, 300, 400)}
        semantics_snapshot = logical_snapshot(300, 360, [{
            "type": "flutter_semantics",
            "text": "",
            "key": "add_item_button",
            "label": "",
            "description": "SemanticsNode#4",
            "value": "",
            "role": "",
            "subrole": "",
            "enabled": None,
            "rect": {"x": 1, "y": 2, "w": 3, "h": 4},
            "coordinate_space": "flutter-logical-points",
            "source": "flutter-semantics",
        }])
        with mock.patch.object(
            bridge_macos, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge_macos,
            "_flutter_semantics_snapshot",
            return_value=(semantics_snapshot, None),
        ) as semantics, mock.patch.object(
            bridge_macos, "_run_osascript_capture"
        ) as osascript:
            result = bridge._macos_inspect(
                "demo_app",
                {"key": "add_item_button"},
                vm_service_url="http://127.0.0.1:123/abc=/",
            )

        semantics.assert_called_once_with("http://127.0.0.1:123/abc=/")
        osascript.assert_not_called()
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["elements"][0]["key"], "add_item_button")
        self.assertEqual(result["elements"][0]["source"], "flutter-semantics")
        self.assertEqual(result["elements"][0]["coordinate_space"], "app-window-points")
        self.assertEqual(result["elements"][0]["rect"]["y"], 42)

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
            bridge_macos, "_macos_get_app_window_info", return_value=(window, None)
        ), mock.patch.object(
            bridge_macos, "_run_osascript_capture", return_value=("", None)
        ), mock.patch.object(
            bridge_macos,
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
            bridge_macos,
            "_macos_inspect",
            return_value={"elements": [element], "match_count": 1},
        ), mock.patch.object(
            bridge_macos,
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

    def test_tap_key_uses_matching_semantics_identifier_center(self):
        element = {
            "type": "flutter_semantics",
            "key": "add_item_button",
            "source": "flutter-semantics",
            "enabled": True,
            "rect": {"x": 10, "y": 20, "w": 80, "h": 40},
        }
        with mock.patch.object(
            bridge_macos,
            "_macos_inspect",
            return_value={"elements": [element], "match_count": 1},
        ), mock.patch.object(
            bridge_macos,
            "_macos_tap_coordinates",
            return_value={
                "action": "tap",
                "x": 50,
                "y": 40,
                "coordinate_space": "app-window-points",
            },
        ) as tap_coordinates:
            result = bridge._macos_tap_key("demo_app", "add_item_button")

        tap_coordinates.assert_called_once_with("demo_app", 50.0, 40.0)
        self.assertEqual(result["key"], "add_item_button")
        self.assertTrue(result["element_found"])

    def test_wait_times_out_when_text_never_appears(self):
        with mock.patch.object(
            bridge_macos,
            "_macos_inspect",
            return_value={"elements": [], "match_count": 0},
        ):
            result = bridge._macos_wait(
                "demo_app", {"text": "Ready", "timeout_ms": 1}
            )

        self.assertEqual(result["code"], "TIMEOUT")

    def test_wait_returns_when_key_appears(self):
        with mock.patch.object(
            bridge_macos,
            "_macos_inspect",
            return_value={"elements": [{"key": "add_item_button"}],
                          "match_count": 1},
        ):
            result = bridge._macos_wait(
                "demo_app", {"key": "add_item_button", "timeout_ms": 100}
            )

        self.assertEqual(result["action"], "wait")
        self.assertEqual(result["key"], "add_item_button")

    def test_ios_inspect_filters_flutter_inspector_elements(self):
        flutter_elements = [
            {
                "type": "flutter_widget",
                "text": "Sandbox Flutter Demo",
                "label": "Sandbox Flutter Demo",
                "description": "Text",
                "value": "",
                "role": "",
                "subrole": "",
                "enabled": None,
                "rect": {"x": 0, "y": 32, "w": 200, "h": 28},
                "coordinate_space": "flutter-logical-points",
                "source": "flutter-inspector",
            },
            {
                "type": "flutter_widget",
                "text": "Other",
                "label": "Other",
                "description": "Text",
                "value": "",
                "role": "",
                "subrole": "",
                "enabled": None,
                "rect": {"x": 0, "y": 80, "w": 100, "h": 28},
                "coordinate_space": "flutter-logical-points",
                "source": "flutter-inspector",
            },
        ]
        with mock.patch.object(
            bridge_ios,
            "_flutter_inspector_elements",
            return_value=(flutter_elements, None),
        ) as inspector:
            result = bridge._ios_inspect(
                {"text": "sandbox"},
                vm_service_url="http://127.0.0.1:123/abc=/",
            )

        inspector.assert_called_once_with(
            "http://127.0.0.1:123/abc=/",
            coordinate_space="flutter-logical-points",
        )
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["coordinate_space"], "flutter-logical-points")
        self.assertEqual(result["elements"][0]["text"], "Sandbox Flutter Demo")

    def test_ios_wait_returns_when_key_appears(self):
        with mock.patch.object(
            bridge_ios,
            "_ios_inspect",
            return_value={"elements": [{"key": "add_item_button"}],
                          "match_count": 1},
        ):
            result = bridge._ios_wait(
                {"key": "add_item_button", "timeout_ms": 100},
                vm_service_url="http://127.0.0.1:123/abc=/",
            )

        self.assertEqual(result["action"], "wait")
        self.assertEqual(result["key"], "add_item_button")

    def test_ios_type_text_sends_keystrokes_without_echoing_text(self):
        with mock.patch.object(
            bridge_ios, "_macos_type", return_value={"action": "type"}
        ) as type_text:
            result = bridge._ios_type_text("secret text")

        type_text.assert_called_once_with("Simulator", "secret text")
        self.assertEqual(result["action"], "type")
        self.assertEqual(result["text_length"], len("secret text"))
        self.assertEqual(result["method"], "host-keystroke-to-simulator")
        self.assertNotIn("text", result)

    def test_ios_press_key_sends_key_to_simulator(self):
        with mock.patch.object(
            bridge_ios, "_macos_press", return_value={"action": "press"}
        ) as press:
            result = bridge._ios_press_key("enter")

        press.assert_called_once_with("Simulator", "enter")
        self.assertEqual(result["action"], "press")
        self.assertEqual(result["method"], "host-keypress-to-simulator")

    def test_ios_dispatch_type_and_press(self):
        with mock.patch.object(
            bridge_ios,
            "_ios_type_text",
            return_value={"action": "type"},
        ) as type_text:
            type_result, type_status = bridge._ios_simulator_dispatch(
                "type", {"text": "hello"}, device_id="8F0F"
            )
        with mock.patch.object(
            bridge_ios,
            "_ios_press_key",
            return_value={"action": "press"},
        ) as press_key:
            press_result, press_status = bridge._ios_simulator_dispatch(
                "press", {"key": "enter"}, device_id="8F0F"
            )

        type_text.assert_called_once_with("hello")
        press_key.assert_called_once_with("enter")
        self.assertEqual(type_status, 200)
        self.assertEqual(press_status, 200)
        self.assertEqual(type_result["action"], "type")
        self.assertEqual(press_result["action"], "press")

    def test_ios_scroll_dispatch_reports_key_approximation(self):
        with mock.patch.object(
            bridge_ios,
            "_ios_press_key",
            return_value={"action": "press", "key": "pagedown"},
        ) as press_key:
            result, status = bridge._ios_simulator_dispatch(
                "scroll", {"move": "down"}, device_id="8F0F"
            )

        press_key.assert_called_once_with("pagedown")
        self.assertEqual(status, 200)
        self.assertEqual(result["action"], "scroll")
        self.assertEqual(result["move"], "down")
        self.assertEqual(result["dispatch"], "key")
        self.assertEqual(result["key"], "pagedown")
        self.assertEqual(result["scroll_model"], "key-approximation")
        self.assertEqual(result["method"], "host-keypress-to-simulator")

    def test_ios_scroll_dispatch_uses_backend_error_status(self):
        with mock.patch.object(
            bridge_ios,
            "_ios_press_key",
            return_value={"error": "osascript failed", "code": "BACKEND_ERROR"},
        ):
            result, status = bridge._ios_simulator_dispatch(
                "scroll", {"move": "up"}, device_id="8F0F"
            )

        self.assertEqual(status, 500)
        self.assertEqual(result["code"], "BACKEND_ERROR")

    def test_ios_tap_key_prefers_semantics_identifier_rect(self):
        semantics_snapshot = logical_snapshot(402, 874, [{
            "key": "task_title_field",
            "semantics_identifier": "task_title_field",
            "type": "flutter_semantics",
            "enabled": True,
            "rect": {"x": 22, "y": 576, "w": 358, "h": 56},
            "source": "flutter-semantics",
        }])
        window = simulator_window(100, 200, 456, 972)
        content_match = content_match_result(
            {"x": 28, "y": 64, "w": 401, "h": 872}, score_mean_abs_rgb=3.68,
        )

        with mock.patch.object(
            bridge_ios,
            "_flutter_semantics_snapshot",
            return_value=(semantics_snapshot, None),
        ) as semantics, mock.patch.object(
            bridge_ios, "_flutter_inspector_snapshot"
        ) as inspector, mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge_ios, "_ios_first_simulator_window", return_value=(window, None)
        ), mock.patch.object(
            bridge_ios,
            "_ios_host_window_content_match_probe",
            return_value=content_match,
        ), mock.patch.object(
            bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
        ) as tap:
            result = bridge._ios_tap_selector(
                "key",
                "task_title_field",
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_id="8F0F",
                device_name="iPhone 17",
            )

        semantics.assert_called_once_with("http://127.0.0.1:123/abc=/")
        inspector.assert_not_called()
        tap.assert_called_once()
        x, y = tap.call_args.args[:2]
        self.assertAlmostEqual(x, 228.5, places=3)
        self.assertAlmostEqual(y, 666.618, places=3)
        self.assertEqual(result["action"], "tap")
        self.assertEqual(result["key"], "task_title_field")
        self.assertEqual(
            result["method"], "flutter-semantics-identifier-rect-center"
        )
        self.assertEqual(result["element"]["source"], "flutter-semantics")

    def test_ios_inspect_key_does_not_fall_back_to_inspector_value_key(self):
        semantics_snapshot = logical_snapshot(402, 874, [])

        with mock.patch.object(
            bridge_ios,
            "_flutter_semantics_snapshot",
            return_value=(semantics_snapshot, None),
        ), mock.patch.object(
            bridge_ios, "_flutter_inspector_elements"
        ) as inspector:
            result = bridge._ios_inspect(
                {"key": "legacy_value_key"},
                vm_service_url="http://127.0.0.1:123/abc=/",
            )

        inspector.assert_not_called()
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(result["method"], "flutter-semantics")

    def test_ios_tap_key_does_not_fall_back_to_inspector_value_key(self):
        semantics_snapshot = logical_snapshot(402, 874, [])

        with mock.patch.object(
            bridge_ios,
            "_flutter_semantics_snapshot",
            return_value=(semantics_snapshot, None),
        ), mock.patch.object(
            bridge_ios, "_flutter_inspector_snapshot"
        ) as inspector:
            result = bridge._ios_tap_selector(
                "key",
                "legacy_value_key",
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_id="8F0F",
                device_name="iPhone 17",
            )

        inspector.assert_not_called()
        self.assertEqual(result["code"], "ELEMENT_NOT_FOUND")
        self.assertEqual(result["key"], "legacy_value_key")

    def test_ios_tap_text_uses_matched_content_rect_when_image_unavailable(self):
        window = simulator_window(100, 200, 456, 972)
        snapshot = logical_snapshot(402, 874, [{
            "text": "New item",
            "type": "flutter_widget",
            "enabled": True,
            "rect": {"x": 16, "y": 134, "w": 282.7955207824707, "h": 56},
        }])
        content_match = content_match_result(
            {"x": 18, "y": 60, "w": 401, "h": 872}, score_mean_abs_rgb=3.68,
        )
        with mock.patch.object(
            bridge_ios,
            "_flutter_inspector_snapshot",
            return_value=(snapshot, None),
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge_ios, "_ios_first_simulator_window", return_value=(window, None)
        ), mock.patch.object(
            bridge_ios,
            "_ios_host_window_content_match_probe",
            return_value=content_match,
        ), mock.patch.object(
            bridge_ios,
            "_run_simctl_screenshot_image",
            return_value=(
                None,
                {"error": "screenshot failed", "code": "BACKEND_ERROR"},
            ),
        ) as screenshot_image, mock.patch.object(
            bridge_ios, "_flutter_inspector_widget_screenshot"
        ) as widget_screenshot, mock.patch.object(
            bridge_ios, "_image_template_match"
        ) as template_match, mock.patch.object(
            bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
        ) as tap:
            result = bridge._ios_tap_selector(
                "text",
                "New item",
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_id="8F0F",
                device_name="iPhone 17",
            )

        screenshot_image.assert_called_once()
        widget_screenshot.assert_not_called()
        template_match.assert_not_called()
        tap.assert_called_once()
        x, y = tap.call_args.args[:2]
        self.assertAlmostEqual(x, 175.0062236738442, places=3)
        self.assertAlmostEqual(y, 221.62929061784897, places=3)
        self.assertEqual(result["action"], "tap")
        self.assertEqual(result["text"], "New item")
        self.assertEqual(result["method"], "flutter-inspector-rect-center")
        self.assertEqual(result["inspector_snapshot"], "live")

    def test_ios_tap_key_retries_poor_content_match(self):
        snapshot = logical_snapshot(402, 874, [{
            "key": "new_task_fab",
            "type": "flutter_semantics",
            "enabled": True,
            "rect": {"x": 318, "y": 754, "w": 62, "h": 62},
            "source": "flutter-semantics",
        }])
        poor_match = content_match_result(
            {"x": 32, "y": 154, "w": 350, "h": 760}, score_mean_abs_rgb=15.65,
        )
        good_match = content_match_result(
            {"x": 28, "y": 64, "w": 401, "h": 872}, score_mean_abs_rgb=4.9,
        )
        small_match = content_match_result(
            {"x": 32, "y": 154, "w": 350, "h": 760}, score_mean_abs_rgb=1.0,
        )
        with mock.patch.object(
            bridge_ios,
            "_flutter_semantics_snapshot",
            return_value=(snapshot, None),
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge_ios, "_ios_first_simulator_window",
            return_value=({"bounds": {"width": 456, "height": 972}}, None),
        ), mock.patch.object(
            bridge_ios,
            "_ios_host_window_content_match_probe",
            side_effect=[poor_match, small_match, good_match],
        ) as content_match, mock.patch.object(
            bridge.time, "sleep"
        ), mock.patch.object(
            bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
        ) as tap:
            result = bridge._ios_tap_selector(
                "key",
                "new_task_fab",
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_id="8F0F",
                device_name="iPhone 17",
            )

        self.assertEqual(content_match.call_count, 3)
        x, y = tap.call_args.args[:2]
        self.assertAlmostEqual(x, 376.1318407960199, places=3)
        self.assertAlmostEqual(y, 847.2036613272311, places=3)
        self.assertEqual(result["match_score_mean_abs_rgb"], 4.9)
        self.assertEqual(
            result["method"], "flutter-semantics-identifier-rect-center"
        )

    def test_ios_tap_key_falls_back_to_full_window_for_implausible_match(self):
        snapshot = logical_snapshot(402, 874, [{
            "key": "new_task_fab",
            "type": "flutter_semantics",
            "enabled": True,
            "rect": {"x": 318, "y": 754, "w": 62, "h": 62},
            "source": "flutter-semantics",
        }])
        small_match = content_match_result(
            {"x": 32, "y": 154, "w": 350, "h": 760}, score_mean_abs_rgb=15.65,
        )
        with mock.patch.object(
            bridge_ios,
            "_flutter_semantics_snapshot",
            return_value=(snapshot, None),
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge_ios, "_ios_first_simulator_window",
            return_value=({"bounds": {"width": 456, "height": 972}}, None),
        ), mock.patch.object(
            bridge_ios,
            "_ios_host_window_content_match_probe",
            return_value=small_match,
        ), mock.patch.object(
            bridge.time, "sleep"
        ), mock.patch.object(
            bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
        ) as tap:
            result = bridge._ios_tap_selector(
                "key",
                "new_task_fab",
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_id="8F0F",
                device_name="iPhone 17",
            )

        x, y = tap.call_args.args[:2]
        self.assertAlmostEqual(x, 395.88059701492534, places=3)
        self.assertAlmostEqual(y, 873.0205949656751, places=3)
        self.assertEqual(
            result["method"],
            "flutter-semantics-identifier-rect-center-full-window-fallback",
        )

    def test_ios_tap_text_uses_widget_screenshot_match(self):
        native_pixels = bytearray([255] * 100 * 200 * 3)
        for yy in range(20):
            for xx in range(40):
                i = ((120 + yy) * 100 + 30 + xx) * 3
                native_pixels[i:i + 3] = bytes((12, 90, 180))
        native = {
            "width": 100, "height": 200, "pixels": bytes(native_pixels),
        }
        widget = {
            "width": 40, "height": 20,
            "pixels": bytes((12, 90, 180) * 40 * 20),
        }
        for name, widget_metadata in [
            ("text_field", {"widget_type": "SynthTextField"}),
            ("untyped_widget", {}),
        ]:
            with self.subTest(case=name):
                snapshot = logical_snapshot(50, 100, [{
                    "text": "Task title",
                    "type": "flutter_widget",
                    "enabled": True,
                    "value_id": "field-1",
                    "rect": {"x": 2, "y": 8, "w": 4, "h": 2},
                    **widget_metadata,
                }], isolate_id="isolates/1")
                content_match = content_match_result(
                    {"x": 0, "y": 0, "w": 50, "h": 100}, score_mean_abs_rgb=1.2,
                )
                with mock.patch.object(
                    bridge_ios, "_flutter_inspector_snapshot",
                    return_value=(snapshot, None),
                ), mock.patch.object(
                    bridge.shutil, "which", return_value="/usr/bin/xcrun"
                ), mock.patch.object(
                    bridge_ios, "_ios_first_simulator_window",
                    return_value=({"bounds": {"width": 60, "height": 120}}, None),
                ), mock.patch.object(
                    bridge_ios, "_ios_host_window_content_match_probe",
                    return_value=content_match,
                ), mock.patch.object(
                    bridge_ios, "_run_simctl_screenshot_image",
                    return_value=(native, None),
                ), mock.patch.object(
                    bridge_ios, "_flutter_inspector_widget_screenshot",
                    return_value=(widget, None),
                ), mock.patch.object(
                    bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
                ) as tap:
                    result = bridge._ios_tap_selector(
                        "text", "Task title",
                        vm_service_url="http://127.0.0.1:123/abc=/",
                        device_id="8F0F", device_name="iPhone 17",
                    )

                tap.assert_called_once()
                x, y = tap.call_args.args[:2]
                self.assertGreaterEqual(x, 24)
                self.assertLessEqual(x, 26)
                self.assertGreaterEqual(y, 64)
                self.assertLessEqual(y, 66)
                self.assertEqual(
                    result["method"], "flutter-inspector-widget-screenshot-match"
                )
                self.assertEqual(result["text"], "Task title")
                self.assertEqual(
                    result["element_image_match"]["coordinate_space"],
                    "native-device-pixels",
                )

    def test_ios_tap_text_field_falls_back_when_widget_match_is_poor(self):
        snapshot = logical_snapshot(50, 100, [{
            "text": "Task title",
            "type": "flutter_widget",
            "widget_type": "SynthTextField",
            "enabled": True,
            "value_id": "field-1",
            "rect": {"x": 2, "y": 8, "w": 4, "h": 2},
        }], isolate_id="isolates/1")
        content_match = content_match_result(
            {"x": 10, "y": 20, "w": 50, "h": 100}, score_mean_abs_rgb=4.9,
        )
        poor_element_match = {
            "x": 30, "y": 120, "w": 8, "h": 4,
            "score_mean_abs_rgb": 164.97,
            "coordinate_space": "native-device-pixels",
        }
        with mock.patch.object(
            bridge_ios, "_flutter_inspector_snapshot",
            return_value=(snapshot, None),
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge_ios, "_ios_first_simulator_window",
            return_value=({"bounds": {"width": 60, "height": 120}}, None),
        ), mock.patch.object(
            bridge_ios, "_ios_host_window_content_match_probe",
            return_value=content_match,
        ), mock.patch.object(
            bridge_ios, "_run_simctl_screenshot_image",
            return_value=({"width": 100, "height": 200, "pixels": b""}, None),
        ), mock.patch.object(
            bridge_ios, "_flutter_inspector_widget_screenshot",
            return_value=({"width": 8, "height": 4, "pixels": b""}, None),
        ), mock.patch.object(
            bridge_ios, "_image_template_match", return_value=poor_element_match,
        ), mock.patch.object(
            bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
        ) as tap:
            result = bridge._ios_tap_selector(
                "text", "Task title",
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_id="8F0F", device_name="iPhone 17",
            )

        # Logical center (4, 9), unit scale, content origin (10, 20).
        tap.assert_called_once_with(14.0, 29.0, device_name="iPhone 17")
        self.assertEqual(result["action"], "tap")
        self.assertEqual(result["text"], "Task title")
        self.assertEqual(result["method"], "flutter-inspector-rect-center")
        self.assertNotIn("element_image_match", result)
        self.assertEqual(
            result["element_image_match_error"]["code"], "BACKEND_ERROR"
        )

    def test_ios_tap_selector_uses_recent_cached_snapshot_after_timeout(self):
        cache_key = ("http://127.0.0.1:123/abc=/", "8F0F")
        snapshot = logical_snapshot(402, 874, [{
            "text": "Add item",
            "type": "button",
            "enabled": True,
            "rect": {"x": 310.8, "y": 138, "w": 75.2, "h": 48},
        }])
        content_match = content_match_result(
            {"x": 18, "y": 60, "w": 401, "h": 872}, score_mean_abs_rgb=3.68,
        )
        bridge._ios_tap_snapshot_cache[cache_key] = {
            "timestamp": time.time(),
            "snapshot": snapshot,
        }
        with mock.patch.object(
            bridge_ios,
            "_flutter_inspector_snapshot",
            return_value=(
                None,
                {"error": "timed out", "code": "BACKEND_ERROR"},
            ),
        ), mock.patch.object(
            bridge.shutil, "which", return_value="/usr/bin/xcrun"
        ), mock.patch.object(
            bridge_ios,
            "_ios_first_simulator_window",
            return_value=({"bounds": {"width": 456, "height": 972}}, None),
        ), mock.patch.object(
            bridge_ios,
            "_ios_host_window_content_match_probe",
            return_value=content_match,
        ), mock.patch.object(
            bridge_ios,
            "_run_simctl_screenshot_image",
            return_value=(
                None,
                {"error": "screenshot failed", "code": "BACKEND_ERROR"},
            ),
        ), mock.patch.object(
            bridge_ios, "_ios_tap_coordinates", return_value={"action": "tap"}
        ):
            result = bridge._ios_tap_selector(
                "text",
                "Add item",
                vm_service_url=cache_key[0],
                device_id=cache_key[1],
                device_name="iPhone 17",
            )

        self.assertEqual(result["action"], "tap")
        self.assertEqual(
            result["inspector_snapshot"], "cached-after-inspector-error"
        )

    def test_ios_dispatch_selector_tap(self):
        with mock.patch.object(
            bridge_ios,
            "_ios_tap_selector",
            return_value={"action": "tap"},
        ) as tap_selector:
            result, status = bridge._ios_simulator_dispatch(
                "tap",
                {"key": "add_item_button"},
                vm_service_url="http://127.0.0.1:123/abc=/",
                device_name="iPhone 17",
                device_id="8F0F",
            )

        tap_selector.assert_called_once_with(
            "key",
            "add_item_button",
            vm_service_url="http://127.0.0.1:123/abc=/",
            device_id="8F0F",
            device_name="iPhone 17",
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["action"], "tap")

    def test_ios_tap_coordinates_use_simulator_window(self):
        window = simulator_window(100, 200, 456, 972)
        with mock.patch.object(
            bridge_ios, "_ios_first_simulator_window", return_value=(window, None)
        ), mock.patch.object(
            bridge_ios, "_macos_post_mouse_click", return_value=None
        ) as post_click:
            result, status = bridge._ios_simulator_dispatch(
                "tap",
                {"x": 10, "y": 20},
                vm_service_url="http://127.0.0.1:123/abc=/",
            )

        self.assertEqual(status, 200)
        post_click.assert_called_once_with(110, 220)
        self.assertEqual(result["coordinate_space"], "simulator-window-points")
        self.assertEqual(result["window"], window)

    def test_ios_tap_coordinates_reject_outside_simulator_window(self):
        window = simulator_window(100, 200, 456, 972)
        with mock.patch.object(
            bridge_ios, "_ios_first_simulator_window", return_value=(window, None)
        ):
            result = bridge._ios_tap_coordinates(456, 20)

        self.assertEqual(result["code"], "INVALID_BODY")
        self.assertIn("outside", result["error"])


class UiAutomationValidationTests(unittest.TestCase):
    def test_validates_actions(self):
        cases = [
            ("validates_coordinate_tap", "tap", {"x": 12, "y": 34}, {"x": 12, "y": 34}),
            ("accepts_modifier_press_key", "press", {"key": "command+r"}, {"key": "command+r"}),
            ("accepts_modifier_press_key_with_spaces", "press",
             {"key": "command + r"}, {"key": "command+r"}),
            ("accepts_single_alpha_press_key", "press", {"key": "a"}, {"key": "a"}),
            ("validates_scroll_move", "scroll", {"move": "down"}, {"move": "down"}),
            ("validates_scroll_move_top", "scroll", {"move": "top"}, {"move": "top"}),
            ("validates_empty_inspect_body", "inspect", {}, {}),
            ("validates_inspect_selector_body", "inspect", {"text": "Settings"}, {"text": "Settings"}),
            ("validates_wait_timeout", "wait", {"text": "Welcome", "timeout_ms": 1000},
             {"text": "Welcome", "timeout_ms": 1000}),
        ]
        for name, action, body, expected in cases:
            with self.subTest(case=name):
                parsed, error = bridge.validate_ui_action(action, body)
                self.assertIsNone(error)
                self.assertEqual(parsed, expected)

    def test_rejects_invalid_actions(self):
        cases = [
            ("rejects_mixed_tap_selector_modes", "tap",
             {"x": 12, "y": 34, "text": "Sign in"}, "INVALID_BODY"),
            ("rejects_unknown_press_key", "press", {"key": "F13"}, "UNKNOWN_KEY"),
            ("rejects_modifier_only_press_key", "press", {"key": "command+shift"}, "UNKNOWN_KEY"),
            ("rejects_empty_press_key_segment", "press", {"key": "command++r"}, "UNKNOWN_KEY"),
            ("rejects_null_bytes_in_text", "type", {"text": "bad\x00text"}, "INVALID_BODY"),
            ("rejects_scroll_legacy_delta", "scroll", {"dy": 100}, "INVALID_BODY"),
            ("rejects_scroll_move_with_extra_arguments", "scroll",
             {"move": "down", "dy": 100}, "INVALID_BODY"),
            ("rejects_unknown_scroll_move", "scroll", {"move": "left"}, "INVALID_BODY"),
            ("rejects_inspect_with_both_text_and_key", "inspect",
             {"text": "Settings", "key": "settingsButton"}, "INVALID_BODY"),
        ]
        for name, action, body, code in cases:
            with self.subTest(case=name):
                parsed, error = bridge.validate_ui_action(action, body)
                self.assertIsNone(parsed)
                self.assertEqual(error["code"], code)


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

    def test_selector_rejected_when_backend_does_not_advertise_it(self):
        actions = bridge._backend_action_capabilities("macos-desktop")
        actions["tap"] = {
            **actions["tap"],
            "selectors": ["coordinates", "text"],
        }
        state = self.State({
            "ready": True,
            "backend": "macos-desktop",
            "missing": [],
            "actions": actions,
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
    def test_serializes_ui_commands(self):
        cases = [
            ("tap_serializes_coordinates", "tap", (), {"x": 1, "y": 2},
             ("POST", "/tap", {"x": 1, "y": 2})),
            ("wait_serializes_timeout_and_selector", "wait", (),
             {"text": "Ready", "timeout_ms": 2500},
             ("POST", "/wait", {"timeout_ms": 2500, "text": "Ready"})),
            ("scroll_serializes_move", "scroll", ("down",), {},
             ("POST", "/scroll", {"move": "down"})),
            ("ios_probe_uses_fixed_probe_endpoint", "ios_probe", (), {},
             ("GET", "/ios-simulator-probe", None)),
            ("ios_map_uses_fixed_mapping_endpoint", "ios_map", (), {},
             ("GET", "/ios-coordinate-map", None)),
            ("restart_bridge_uses_fixed_restart_endpoint", "restart_bridge", (), {},
             ("POST", "/restart", None)),
        ]
        for name, command, args, kwargs, expected in cases:
            with self.subTest(case=name):
                ctl = RecordingFlutterCtl()
                getattr(ctl, command)(*args, **kwargs)
                self.assertEqual(len(ctl.calls), 1)
                self.assertEqual(ctl.calls[0][:3], expected)

    def test_tap_rejects_partial_coordinates_client_side(self):
        ctl = RecordingFlutterCtl()

        with self.assertRaises(ValueError):
            ctl.tap(x=1)

        self.assertEqual(ctl.calls, [])


class FlutterSubprocessStateTests(unittest.TestCase):
    def test_reader_reports_launch_failure_in_status_message(self):
        state = bridge.BridgeState(
            "token",
            tempfile.gettempdir(),
            "ios",
            "lib/main.dart",
            "flutter",
            [],
        )
        state.update_devices_cache([ios_device(device_id="ios")])
        proc = mock.Mock(
            stdout=io.StringIO(
                "No supported devices found with name or id matching 'ios'.\n"
            ),
            **{"wait.return_value": 1},
        )
        state.process = proc
        state.status = "launching"
        state.subprocess_type = "run"

        bridge._reader_thread(state, proc)

        status = state.to_status_dict()
        self.assertEqual(status["status"], "error")
        self.assertIsNone(state.process)
        self.assertIsNone(state.subprocess_type)
        self.assertIn("exited with code 1", status["message"])
        self.assertIn("before the VM service", status["message"])
        self.assertIn("No supported devices", "\n".join(state.get_logs()))


class BridgeHttpUiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state = bridge.BridgeState(
            token="secret",
            project_dir=self.tmpdir.name,
            device_id="macos",
            target="lib/main.dart",
            flutter_path="flutter",
            run_args="",
        )
        self.state.update_devices_cache([{
            "id": "macos", "name": "macOS", "targetPlatform": "darwin",
            "emulator": False,
        }])
        state_patch = mock.patch.object(
            bridge.FlutterBridgeHandler, "bridge_state", self.state
        )
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.server = bridge.ThreadingHTTPServer(
            ("127.0.0.1", 0), bridge.FlutterBridgeHandler
        )
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.thread.join, timeout=2)
        self.addCleanup(self.server.shutdown)
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

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

    def get_request(self, path, token="secret"):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return urllib.request.Request(
            f"{self.base_url}{path}",
            headers=headers,
            method="GET",
        )

    def test_ui_endpoints_require_auth(self):
        for name, path, body in [
            ("auth_required_for_ui_action", "/tap", {"x": 1, "y": 2}),
            ("restart_bridge_requires_auth", "/restart", None),
        ]:
            with self.subTest(case=name):
                req = self.request(path, body, token=None)
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5)
                with ctx.exception:
                    self.assertEqual(ctx.exception.code, 401)

    def test_restart_bridge_starts_restart_thread(self):
        restarted = threading.Event()

        def fake_restart(handler):
            restarted.set()

        req = self.request("/restart")
        with mock.patch.object(
            bridge.FlutterBridgeHandler,
            "_restart_bridge",
            autospec=True,
            side_effect=fake_restart,
        ):
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode())

            self.assertEqual(resp.status, 200)
            self.assertIn("Restarting bridge", payload["message"])
            self.assertTrue(restarted.wait(timeout=2))

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

    def test_ios_coordinate_map_rejects_non_ios_target(self):
        req = self.get_request("/ios-coordinate-map")

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 501)
        payload = json.loads(ctx.exception.read().decode())
        self.assertEqual(payload["code"], "UNSUPPORTED_TARGET")
        self.assertEqual(payload["backend"], "macos-desktop")
        self.assertIn("iOS Simulator", payload["error"])

    def test_ios_coordinate_map_dispatches_for_ios_simulator(self):
        self.state.device_id = "8F0F"
        self.state.update_devices_cache([ios_device(name="iPhone 17")])
        req = self.get_request("/ios-coordinate-map")

        with mock.patch.object(
            bridge_ios,
            "ios_coordinate_map",
            return_value={"available": True, "ok": True},
        ) as coordinate_map:
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode())

        self.assertEqual(resp.status, 200)
        self.assertEqual(payload["ok"], True)
        coordinate_map.assert_called_once_with(
            self.state.vm_service_url,
            device_id="8F0F",
            device_name="iPhone 17",
        )

    def test_ui_action_reports_ui_not_ready_while_launching(self):
        class _MockProcess:
            def poll(self):
                return None

        # Test readiness rather than host tool availability.
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
