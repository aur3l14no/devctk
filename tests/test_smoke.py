"""Smoke test: init a container, SSH in, run commands, tear down."""

import os
import subprocess
import tempfile
import time

import pytest

CONTAINER_NAME = "devctk-smoke-test"
PORT = 39999
IMAGE = "docker.io/library/ubuntu:24.04"


def ssh_cmd(key_path: str, cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh", "-p", str(PORT),
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


@pytest.fixture(scope="module")
def container(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("smoke")
    key = tmp / "id_ed25519"

    # Generate a throwaway SSH key
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(key), "-N", "", "-q"],
        check=True,
    )

    # Init
    subprocess.run(
        [
            "devctk", "init",
            "--image", IMAGE,
            "--port", str(PORT),
            "--container-name", CONTAINER_NAME,
            "--authorized-keys-file", str(key) + ".pub",
            "--no-workspace",
        ],
        check=True,
        timeout=120,
    )

    # Wait for sshd to accept connections
    for _ in range(30):
        r = ssh_cmd(str(key), "true")
        if r.returncode == 0:
            break
        time.sleep(2)
    else:
        pytest.fail("sshd never became ready")

    yield str(key)

    # Teardown
    subprocess.run(["devctk", "rm", CONTAINER_NAME], check=False, timeout=30)


def test_whoami(container):
    r = ssh_cmd(container, "whoami")
    assert r.returncode == 0
    assert r.stdout.strip() == os.environ["USER"]


def test_pwd(container):
    r = ssh_cmd(container, "pwd")
    assert r.returncode == 0
    assert r.stdout.strip() == f"/home/{os.environ['USER']}"


def test_sudo(container):
    r = ssh_cmd(container, "sudo id -u")
    assert r.returncode == 0
    assert r.stdout.strip() == "0"
