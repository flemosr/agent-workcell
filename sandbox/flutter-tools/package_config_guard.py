#!/usr/bin/env python3
"""Repair stale Flutter package metadata before container SDK commands."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


CONTAINER_PREFIXES = (
    "/home/agent/",
    "/workspaces/",
)


def find_project_dir(start):
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pubspec.yaml").is_file():
            return candidate
    return None


def file_uri_path(root_uri, package_config_dir):
    if not isinstance(root_uri, str):
        return None
    parsed = urlparse(root_uri)
    if parsed.scheme == "file":
        return unquote(parsed.path)
    if parsed.scheme:
        return None
    path = Path(unquote(root_uri))
    if path.is_absolute():
        return str(path)
    return str((package_config_dir / path).resolve())


def package_config_has_foreign_paths(project_dir):
    package_config = project_dir / ".dart_tool" / "package_config.json"
    if not package_config.exists():
        return False
    try:
        data = json.loads(package_config.read_text())
    except (OSError, json.JSONDecodeError):
        return True

    package_config_dir = package_config.parent
    for package in data.get("packages", []):
        root = file_uri_path(package.get("rootUri"), package_config_dir)
        if not root or root.startswith(CONTAINER_PREFIXES):
            continue
        if os.path.isabs(root):
            return True
    return False


def should_skip(argv):
    if not argv:
        return False
    command = argv[0]
    if command in ("--version", "-h", "--help", "doctor", "config"):
        return True
    if command == "pub" and len(argv) > 1 and argv[1] in (
        "get",
        "upgrade",
        "downgrade",
        "outdated",
    ):
        return True
    return False


def main():
    if should_skip(sys.argv[1:]):
        return 0
    project_dir = find_project_dir(os.getcwd())
    if not project_dir:
        return 0
    if not package_config_has_foreign_paths(project_dir):
        return 0

    flutter = os.environ.get(
        "WORKCELL_REAL_FLUTTER",
        "/home/agent/persist/.flutter-sdk/bin/flutter",
    )
    result = subprocess.run(
        [flutter, "pub", "get"],
        cwd=str(project_dir),
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
