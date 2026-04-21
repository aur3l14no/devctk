"""Smoke tests: apply config, verify access, tear down."""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

PORT = 39999
IMAGE = "docker.io/library/ubuntu:24.04"
NOSSH_NAME = "devctk-smoke-nossh"
SSH_NAME = "devctk-smoke-ssh"


def _podman_ready() -> bool:
    try:
        result = subprocess.run(
            ["podman", "info"],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _podman_ready(),
    reason="podman is unavailable in this environment",
)


def devctk(*args: str, env: dict[str, str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["devctk", *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


def ssh_cmd(key_path: str, port: int, cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-p",
            str(port),
            "-i",
            key_path,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            f"{os.environ['USER']}@127.0.0.1",
            cmd,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture(scope="module")
def devctk_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("xdg")
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp / "config")
    env["XDG_STATE_HOME"] = str(tmp / "state")
    return env


@pytest.fixture(scope="module")
def applied_containers(tmp_path_factory, devctk_env):
    tmp = tmp_path_factory.mktemp("smoke")
    key = tmp / "id_ed25519"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(key), "-N", "", "-q"],
        check=True,
    )

    config_dir = Path(devctk_env["XDG_CONFIG_HOME"]) / "devctk"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    workspace = tmp / "workspace"
    workspace.mkdir()

    config_path.write_text(
        textwrap.dedent(
            f"""\
            [[containers]]
            name = "{NOSSH_NAME}"
            image = "{IMAGE}"

            [[containers]]
            name = "{SSH_NAME}"
            image = "{IMAGE}"

            [containers.workspace]
            path = "{workspace}"

            [containers.ssh]
            port = {PORT}
            authorized_keys_file = "{key}.pub"
            """
        )
    )

    result = devctk("apply", "--yes", env=devctk_env, timeout=180)
    assert result.returncode == 0, result.stderr

    for _ in range(60):
        ready = subprocess.run(
            ["podman", "exec", NOSSH_NAME, "test", "-f", "/run/devctk-ready"],
            capture_output=True,
            timeout=10,
        )
        if ready.returncode == 0:
            break
        time.sleep(2)
    else:
        pytest.fail("bootstrap never signalled ready")

    for _ in range(30):
        result = ssh_cmd(str(key), PORT, "true")
        if result.returncode == 0:
            break
        time.sleep(2)
    else:
        pytest.fail("sshd never became ready")

    yield str(key)

    subprocess.run(["devctk", "rm", "--all", "--yes"], check=False, timeout=30, env=devctk_env)


def test_nossh_exec_whoami(applied_containers):
    result = subprocess.run(
        ["podman", "exec", NOSSH_NAME, "whoami"],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == os.environ["USER"]


def test_nossh_exec_sudo(applied_containers):
    result = subprocess.run(
        ["podman", "exec", NOSSH_NAME, "sudo", "id", "-u"],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


def test_ssh_whoami(applied_containers):
    result = ssh_cmd(applied_containers, PORT, "whoami")
    assert result.returncode == 0
    assert result.stdout.strip() == os.environ["USER"]


def test_ssh_pwd(applied_containers):
    result = ssh_cmd(applied_containers, PORT, "pwd")
    assert result.returncode == 0
    assert result.stdout.strip() == f"/home/{os.environ['USER']}"


def test_ssh_sudo(applied_containers):
    result = ssh_cmd(applied_containers, PORT, "sudo id -u")
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


def test_ls_shows_containers(applied_containers, devctk_env):
    result = devctk("ls", env=devctk_env, timeout=10)
    assert result.returncode == 0
    assert NOSSH_NAME in result.stdout
    assert SSH_NAME in result.stdout
