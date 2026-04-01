"""Command implementations: init, ls, rm."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import sys

from devctk.paths import ManagedPaths, managed_paths, state_root, STATE_DIR_NAME
from devctk.helpers import render_container_helper, render_sshd_helper
from devctk.systemd import render_unit
from devctk.util import require_binary, run, write_text, unlink_if_exists


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def resolve_authorized_keys(args: argparse.Namespace) -> tuple[pathlib.Path | None, str | None, str]:
    """Return (file_path | None, text | None, source_tag)."""
    if args.authorized_keys_file is not None:
        p = pathlib.Path(args.authorized_keys_file).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"authorized_keys file not found: {p}")
        if p.stat().st_size == 0:
            raise SystemExit(f"authorized_keys file is empty: {p}")
        return p, None, "file"
    text = args.authorized_keys_text
    if not text or not text.strip():
        raise SystemExit("authorized_keys text is empty")
    return None, text, "inline"


def build_workspace_mount(workspace: str | None, no_workspace: bool, container_user: str) -> tuple[str | None, str]:
    home = f"/home/{container_user}"
    if no_workspace:
        return None, home
    if workspace is None:
        d = pathlib.Path.home() / "dev-container"
        d.mkdir(parents=True, exist_ok=True)
        return f"type=bind,src={d},target={home},rw", home

    # Check if it's a full mount spec
    fields = {k: v for k, _, v in (p.partition("=") for p in workspace.split(",")) if v}
    if {"type", "src", "source", "target", "destination", "dst"} & fields.keys():
        target = fields.get("target") or fields.get("destination") or fields.get("dst")
        if not target:
            raise SystemExit("--workspace mount spec must include target=...")
        return workspace, target

    d = pathlib.Path(workspace).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    return f"type=bind,src={d},target={home},rw", home


def cmd_init(args: argparse.Namespace, passthrough: list[str]) -> int:
    from devctk.cli import NAME_RE

    user = os.environ.get("USER") or pathlib.Path.home().name
    container_user = args.container_user or user
    container_name = args.container_name or f"{user}-dev"

    if not NAME_RE.match(container_user):
        raise SystemExit(f"invalid container user: {container_user}")
    if not NAME_RE.match(container_name):
        raise SystemExit(f"invalid container name: {container_name}")
    if not 1 <= args.port <= 65535:
        raise SystemExit(f"invalid port: {args.port}")
    if args.no_workspace and args.workspace:
        raise SystemExit("--workspace and --no-workspace conflict")

    ak_file, ak_text, ak_source = resolve_authorized_keys(args)
    workspace_mount, container_home = build_workspace_mount(args.workspace, args.no_workspace, container_user)

    mounts = list(args.mount)
    if workspace_mount:
        mounts.insert(0, workspace_mount)

    podman = require_binary("podman")
    systemctl = require_binary("systemctl")
    loginctl = require_binary("loginctl")

    # Conflict checks
    if run([podman, "container", "exists", container_name], check=False).returncode == 0:
        raise SystemExit(f"container already exists: {container_name}")

    paths = managed_paths(container_name)
    for p in [paths.container_unit, paths.sshd_unit, paths.container_helper, paths.sshd_helper, paths.metadata]:
        if p.exists():
            raise SystemExit(f"managed files already exist for {container_name}")

    # Write helpers + units
    write_text(
        paths.container_helper,
        render_container_helper(podman, container_name, args.image, args.port, mounts, args.device, passthrough),
        stat.S_IRWXU,
    )
    write_text(
        paths.sshd_helper,
        render_sshd_helper(podman, container_name, container_user, os.getuid(), os.getgid(), container_home, ak_file, ak_text),
        stat.S_IRWXU,
    )
    write_text(paths.container_unit, render_unit("container", container_name=container_name, container_helper=str(paths.container_helper)))
    write_text(paths.sshd_unit, render_unit("sshd", container_name=container_name, container_unit=paths.container_unit.name, sshd_helper=str(paths.sshd_helper)))

    # Metadata
    write_text(paths.metadata, json.dumps({
        "container_name": container_name,
        "container_user": container_user,
        "image": args.image,
        "port": args.port,
        "container_home": container_home,
        "workspace_mount": workspace_mount or "",
        "authorized_keys_source": ak_source,
    }, indent=2, sort_keys=True) + "\n")

    # Enable — rollback on failure
    try:
        run([systemctl, "--user", "daemon-reload"])
        run([systemctl, "--user", "enable", "--now", paths.container_unit.name])
        run([systemctl, "--user", "enable", "--now", paths.sshd_unit.name])
    except Exception:
        print(f"startup failed, cleaning up {container_name}", file=sys.stderr)
        _cleanup(podman, systemctl, paths, container_name)
        raise

    print(f"started {container_name}")
    print(f"  ssh {container_user}@localhost -p {args.port}")

    # Linger check
    res = run([loginctl, "show-user", user, "-p", "Linger"], check=False, capture=True)
    if res.returncode == 0 and res.stdout.strip().endswith("no"):
        print(f"  hint: sudo loginctl enable-linger {user}", file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

def cmd_ls() -> int:
    names = list_names()
    if not names:
        print("no devctk containers")
        return 0

    podman = require_binary("podman")
    systemctl = require_binary("systemctl")

    for name in names:
        paths = managed_paths(name)
        meta = _read_meta(paths.metadata)
        parts = [
            name,
            f"user={meta.get('container_user', '-')}",
            f"podman={_container_status(podman, name)}",
            f"port={meta.get('port', '-')}",
            f"image={meta.get('image', '-')}",
        ]
        print("  ".join(parts))
    return 0


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------

def cmd_rm(args: argparse.Namespace) -> int:
    user = os.environ.get("USER") or pathlib.Path.home().name

    if args.all and args.container_name:
        raise SystemExit("rm accepts either a name or --all, not both")

    if args.all:
        names = list_names()
        if not names:
            print("no devctk containers")
            return 0
    else:
        names = [args.container_name or f"{user}-dev"]

    podman = require_binary("podman")
    systemctl = require_binary("systemctl")

    for name in names:
        paths = managed_paths(name)
        exists = any(p.exists() for p in [paths.metadata, paths.container_helper, paths.sshd_helper, paths.container_unit, paths.sshd_unit])
        exists = exists or run([podman, "container", "exists", name], check=False).returncode == 0

        if not exists:
            if args.all:
                continue
            raise SystemExit(f"not found: {name}")

        _cleanup(podman, systemctl, paths, name)
        print(f"removed {name}")

    return 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _cleanup(podman: str, systemctl: str, paths: ManagedPaths, name: str) -> None:
    """Stop services, remove container, delete managed files."""
    run([systemctl, "--user", "disable", "--now", paths.sshd_unit.name], check=False, capture=True)
    run([systemctl, "--user", "disable", "--now", paths.container_unit.name], check=False, capture=True)
    res = run([podman, "rm", "-f", "--ignore", name], check=False, capture=True)
    if res.returncode != 0:
        print(f"warning: podman rm failed for {name}: {res.stderr.strip()}", file=sys.stderr)

    for p in [paths.container_unit, paths.sshd_unit, paths.container_helper, paths.sshd_helper, paths.metadata]:
        unlink_if_exists(p)

    if paths.helper_dir.exists() and not any(paths.helper_dir.iterdir()):
        paths.helper_dir.rmdir()

    run([systemctl, "--user", "daemon-reload"], check=False)


def list_names() -> list[str]:
    d = state_root() / STATE_DIR_NAME
    if not d.exists():
        return []
    names: set[str] = set()
    for p in d.glob("*.json"):
        names.add(p.stem)
    for p in d.glob("*-container.sh"):
        names.add(p.name.removesuffix("-container.sh"))
    return sorted(names)


def _read_meta(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _container_status(podman: str, name: str) -> str:
    res = run([podman, "inspect", "-f", "{{.State.Status}}", name], check=False, capture=True)
    return res.stdout.strip() if res.returncode == 0 else "missing"
