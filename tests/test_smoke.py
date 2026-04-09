"""Smoke tests: init containers, verify access, tear down."""

import os
import subprocess
import tempfile
import time

import pytest

PORT = 39999
IMAGE = "docker.io/library/ubuntu:24.04"


def devctk(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["devctk", *args],
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def ssh_cmd(key_path: str, port: int, cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh", "-p", str(port),
            "-i", key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            f"{os.environ['USER']}@127.0.0.1",
            cmd,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# No-SSH smoke test (basic container with podman exec)
# ---------------------------------------------------------------------------

NOSSH_NAME = "devctk-smoke-nossh"


@pytest.fixture(scope="module")
def nossh_container():
    """Create a basic container without SSH."""
    subprocess.run(
        [
            "devctk", "init",
            "--image", IMAGE,
            "--name", NOSSH_NAME,
            "--no-workspace",
        ],
        check=True,
        timeout=120,
    )

    # Wait for bootstrap readiness
    for _ in range(60):
        r = subprocess.run(
            ["podman", "exec", NOSSH_NAME, "test", "-f", "/run/devctk-ready"],
            capture_output=True,
            timeout=10,
        )
        if r.returncode == 0:
            break
        time.sleep(2)
    else:
        pytest.fail("bootstrap never signalled ready")

    yield

    subprocess.run(["devctk", "rm", NOSSH_NAME], check=False, timeout=30)


def test_nossh_exec_whoami(nossh_container):
    r = subprocess.run(
        ["podman", "exec", NOSSH_NAME, "whoami"],
        text=True, capture_output=True, timeout=10,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == os.environ["USER"]


def test_nossh_exec_sudo(nossh_container):
    r = subprocess.run(
        ["podman", "exec", NOSSH_NAME, "sudo", "id", "-u"],
        text=True, capture_output=True, timeout=10,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "0"


# ---------------------------------------------------------------------------
# SSH smoke test
# ---------------------------------------------------------------------------

SSH_NAME = "devctk-smoke-ssh"


@pytest.fixture(scope="module")
def ssh_container(tmp_path_factory):
    """Create a container with SSH enabled."""
    tmp = tmp_path_factory.mktemp("smoke")
    key = tmp / "id_ed25519"

    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(key), "-N", "", "-q"],
        check=True,
    )

    subprocess.run(
        [
            "devctk", "init",
            "--image", IMAGE,
            "--ssh",
            "--port", str(PORT),
            "--name", SSH_NAME,
            "--authorized-keys-file", str(key) + ".pub",
            "--no-workspace",
        ],
        check=True,
        timeout=120,
    )

    # Wait for sshd to accept connections
    for _ in range(30):
        r = ssh_cmd(str(key), PORT, "true")
        if r.returncode == 0:
            break
        time.sleep(2)
    else:
        pytest.fail("sshd never became ready")

    yield str(key)

    subprocess.run(["devctk", "rm", SSH_NAME], check=False, timeout=30)


def test_ssh_whoami(ssh_container):
    r = ssh_cmd(ssh_container, PORT, "whoami")
    assert r.returncode == 0
    assert r.stdout.strip() == os.environ["USER"]


def test_ssh_pwd(ssh_container):
    r = ssh_cmd(ssh_container, PORT, "pwd")
    assert r.returncode == 0
    assert r.stdout.strip() == f"/home/{os.environ['USER']}"


def test_ssh_sudo(ssh_container):
    r = ssh_cmd(ssh_container, PORT, "sudo id -u")
    assert r.returncode == 0
    assert r.stdout.strip() == "0"


# ---------------------------------------------------------------------------
# ls / rm
# ---------------------------------------------------------------------------

def test_ls_shows_containers(nossh_container, ssh_container):
    r = devctk("ls", timeout=10)
    assert r.returncode == 0
    assert NOSSH_NAME in r.stdout
    assert SSH_NAME in r.stdout
