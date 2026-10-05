"""Local SDK-discovery fixtures; no installed Pi, credentials, or network required."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_pi_compaction_lifecycle import pi_package_root

PACKAGE_NAME = "@earendil-works/pi-coding-agent"


class PiPackageDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home with spaces"
        self.bin = self.home / ".local" / "bin"
        self.bin.mkdir(parents=True)
        self.entrypoint = self.bin / "pi"
        self.agent = self.home / "agent"
        self.launcher = self.agent / "bin" / "pi"
        self.install = self.agent / "install"
        self.version = "1.0.3"
        self.marker = {"kind": "pi-managed-install", "schemaVersion": 1, "layout": "releases-v1",
                       "entrypoint": {"type": "symlink", "path": str(self.entrypoint)}}
        environment = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def make_package(self, path: Path):
        path.mkdir(parents=True)
        (path / "package.json").write_text(json.dumps({"name": PACKAGE_NAME}))
        return path

    def make_executable(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 99\n")
        path.chmod(0o755)

    def link_entrypoint(self, target: Path, relative=False):
        self.entrypoint.unlink(missing_ok=True)
        self.entrypoint.symlink_to(os.path.relpath(target, self.bin) if relative else target)

    def make_release(self, version: str):
        return self.make_package(self.install / "releases" / version / "node_modules" / PACKAGE_NAME)

    def make_managed(self):
        self.make_executable(self.launcher)
        self.link_entrypoint(self.launcher)
        self.install.mkdir()
        (self.install / "managed-install.json").write_text(json.dumps(self.marker))
        (self.install / "current-version").write_text(self.version + "\n")
        return self.make_release(self.version)

    def make_ordinary(self):
        package = self.make_package(self.home / "npm" / "lib" / "node_modules" / PACKAGE_NAME)
        executable = package / "dist" / "bundle" / "cli.js"
        self.make_executable(executable)
        self.link_entrypoint(executable)
        return package

    def test_managed_path_links_find_selected_not_highest_release(self):
        selected = self.make_managed()
        newer = self.make_release("2.0.0")
        for relative in [False, True]:
            with self.subTest(relative=relative):
                self.link_entrypoint(self.launcher, relative=relative)
                self.assertEqual(pi_package_root(), selected)
        (self.install / "current-version").write_text("2.0.0\n")
        self.assertEqual(pi_package_root(), newer)
        (self.install / "current-version").write_text(self.version + "\n")
        self.assertEqual(pi_package_root(), selected)

    def test_prerelease_selector_is_accepted(self):
        self.version = "1.0.3-rc.1+build.7"
        package = self.make_managed()
        self.assertEqual(pi_package_root(), package)

    def test_invalid_markers_raise_instead_of_skipping(self):
        self.make_managed()
        markers = ["not json", "null", "[]", '"text"', "{}"]
        for field, value in [("kind", "other"), ("schemaVersion", 2), ("schemaVersion", "1"),
                             ("schemaVersion", True), ("layout", "other")]:
            markers.append(json.dumps({**self.marker, field: value}))
        for marker in markers:
            with self.subTest(marker=marker):
                (self.install / "managed-install.json").write_text(marker)
                with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation"):
                    pi_package_root()

    def test_missing_managed_metadata_raises_instead_of_skipping(self):
        self.make_managed()
        for filename in ["managed-install.json", "current-version"]:
            with self.subTest(filename=filename):
                path = self.install / filename
                original = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation.*" + filename):
                    pi_package_root()
                path.write_bytes(original)

    def test_invalid_selectors_raise_instead_of_skipping(self):
        self.make_managed()
        selectors = ["", "\n", ".\n", "..\n", "../../bad\n", "1.0.3/../../bad\n", "/tmp/release\n",
                     " 1.0.3\n", "1.0.3 \n", "1.0.3\n2.0.0\n", "1.0.3\r\n", "1.0.3", "\xff\n"]
        for selector in selectors:
            with self.subTest(selector=selector):
                (self.install / "current-version").write_bytes(selector.encode("latin-1"))
                with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation"):
                    pi_package_root()

    def test_missing_selected_release_does_not_fall_back_to_another(self):
        self.make_managed()
        self.make_release("2.0.0")
        shutil.rmtree(self.install / "releases" / self.version)
        with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation.*1.0.3"):
            pi_package_root()

    def test_invalid_selected_package_manifest_raises(self):
        package = self.make_managed()
        manifest = package / "package.json"
        for content in [None, "not json", "null", "[]", "{}", '{"name": "other"}']:
            with self.subTest(content=content):
                manifest.unlink(missing_ok=True)
                if content is not None:
                    manifest.write_text(content)
                with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation"):
                    pi_package_root()

    def test_selected_package_cannot_escape_to_another_release_or_directory(self):
        package = self.make_managed()
        targets = [self.make_release("2.0.0"), self.make_package(self.home / "external-package")]
        shutil.rmtree(package)
        for target in targets:
            with self.subTest(target=target):
                package.symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(AssertionError, "selected package resolves outside its managed release"):
                    pi_package_root()
                package.unlink()

    def test_package_symlink_within_selected_release_is_resolved(self):
        package = self.make_managed()
        target = package.with_name("package-content")
        package.rename(target)
        package.symlink_to(target.name, target_is_directory=True)
        self.assertEqual(pi_package_root(), target)

    def test_selected_release_cannot_escape_managed_releases(self):
        self.make_managed()
        release = self.install / "releases" / self.version
        external = self.home / "external-release"
        self.make_package(external / "node_modules" / PACKAGE_NAME)
        shutil.rmtree(release)
        release.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(AssertionError, "selected release resolves outside the managed releases directory"):
            pi_package_root()

    def test_releases_directory_cannot_escape_managed_root(self):
        self.make_managed()
        releases = self.install / "releases"
        external = self.home / "external-releases"
        releases.rename(external)
        releases.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(AssertionError, "selected release resolves outside the managed releases directory"):
            pi_package_root()

    def test_invalid_managed_root_type_raises(self):
        self.make_managed()
        shutil.rmtree(self.install)
        self.install.write_text("not a directory")
        with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation"):
            pi_package_root()
        self.install.unlink()
        self.install.symlink_to(self.home / "missing-install", target_is_directory=True)
        with self.assertRaisesRegex(AssertionError, "Invalid managed Pi installation"):
            pi_package_root()

    def test_explicit_root_overrides_corrupt_managed_install_without_path_lookup(self):
        self.make_managed()
        (self.install / "managed-install.json").write_text("not json")
        explicit = self.make_package(self.home / "explicit")
        os.environ["PI_TEST_PACKAGE_ROOT"] = "~/explicit"
        with mock.patch("test_pi_compaction_lifecycle.shutil.which", side_effect=AssertionError("PATH consulted")):
            self.assertEqual(pi_package_root(), explicit)

    def test_invalid_explicit_root_does_not_fall_back(self):
        self.make_managed()
        explicit = self.home / "explicit"
        os.environ["PI_TEST_PACKAGE_ROOT"] = str(explicit)
        with self.assertRaisesRegex(AssertionError, "PI_TEST_PACKAGE_ROOT must point"):
            pi_package_root()
        explicit.mkdir()
        for manifest in ["not json", "null", "[]", "{}", '{"name": "other"}']:
            with self.subTest(manifest=manifest):
                (explicit / "package.json").write_text(manifest)
                with self.assertRaisesRegex(AssertionError, "PI_TEST_PACKAGE_ROOT must point"):
                    pi_package_root()

    def test_ordinary_package_ancestor_discovery_is_preserved(self):
        package = self.make_ordinary()
        for manifest in ["not json", "null", "[]", "{}", '{"name": "other"}']:
            with self.subTest(manifest=manifest):
                (package / "dist" / "package.json").write_text(manifest)
                self.assertEqual(pi_package_root(), package)

    def test_inherited_managed_root_does_not_override_path(self):
        managed = self.make_managed()
        ordinary = self.make_ordinary()
        os.environ["PI_MANAGED_INSTALL_ROOT"] = str(self.install)
        self.assertEqual(pi_package_root(), ordinary)
        os.environ["PI_MANAGED_INSTALL_ROOT"] = str(self.home / "unrelated-install")
        self.link_entrypoint(self.launcher)
        self.assertEqual(pi_package_root(), managed)
        self.entrypoint.unlink()
        self.assertIsNone(pi_package_root())

    def test_absent_sdk_and_unrecognized_wrapper_return_none(self):
        self.assertIsNone(pi_package_root())
        self.make_executable(self.entrypoint)
        self.assertIsNone(pi_package_root())


if __name__ == "__main__":
    unittest.main()
