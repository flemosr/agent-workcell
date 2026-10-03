"""Disposable shell inputs and lossless fake-Docker invocation recording."""

import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def temporary_script_repo(test_case) -> Path:
    temporary = tempfile.TemporaryDirectory(prefix="shell-test-")
    test_case.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    for name in (
        "cli.sh",
        "scripts/run_sandbox.sh",
        "scripts/workcell_env.py",
        "scripts/start-flutter-bridge.sh",
    ):
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, destination)
    return root


def fake_docker_env(
    workspace: Path,
    image_inspect_missing: bool = False,
    extra_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], Path]:
    fake_bin = workspace / "bin"
    fake_bin.mkdir(exist_ok=True)
    docker_log = workspace / "docker-args.bin"
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/bin/bash\n'
        '{\n'
        '  printf \'%s\\0\' "$#"\n'
        '  if [ "$#" -gt 0 ]; then printf \'%s\\0\' "$@"; fi\n'
        '} >> "$DOCKER_LOG"\n'
        'if [ "${1:-}" = image ] && [ "${2:-}" = inspect ] '
        '&& [ "${IMAGE_INSPECT_MISSING:-0}" = 1 ]; then exit 1; fi\n'
        'exit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    for name in ("touch", "sleep"):
        tool = fake_bin / name
        tool.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)

    env = os.environ.copy()
    for name in list(env):
        if name in {"IMAGE_INSPECT_MISSING", "WORKCELL_CONTEXT_REPO", "WORKCELL_PI_NOTIFICATIONS"} or name.startswith("CMUX_"):
            env.pop(name)
    # Keep the fake first even when cli.sh fills in standard Docker directories.
    path = os.pathsep.join([
        str(fake_bin), env["PATH"], "/usr/local/bin", "/opt/homebrew/bin",
        f"{env.get('HOME', '')}/.docker/bin",
    ])
    env.update(
        DOCKER_LOG=str(docker_log),
        PATH=path,
        WORKCELL_TEST_SKIP_WATCHDOG="1",
        IMAGE_INSPECT_MISSING="1" if image_inspect_missing else "0",
    )
    if extra_env:
        env.update(extra_env)
    return env, docker_log


def read_docker_invocations(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    data = path.read_bytes()
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise ValueError("Docker invocation log has an unterminated field")
    fields = data[:-1].split(b"\0")
    invocations = []
    index = 0
    while index < len(fields):
        count_field = fields[index]
        if not count_field.isdigit():
            raise ValueError(f"Invalid Docker argument count: {count_field!r}")
        count = int(count_field)
        index += 1
        if count > len(fields) - index:
            raise ValueError("Docker invocation log has a truncated argument vector")
        invocations.append([field.decode("utf-8") for field in fields[index:index + count]])
        index += count
    return invocations
