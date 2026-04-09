"""Command implementations: init, ls, rm."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import sys

from devctk.paths import ManagedPaths, managed_paths, state_root, STATE_DIR_NAME
from devctk.helpers import render_bootstrap, render_container_helper, render_sshd_helper
from devctk.systemd import render_unit
from devctk.util import require_binary, run, write_text, unlink_if_exists


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def resolve_authorized_keys(args: argparse.Namespace) -> tuple[pathlib.Path | None, str | None]:
    """Return (file_path | None, text | None)."""
    if args.authorized_keys_file is not None:
        p = pathlib.Path(args.authorized_keys_file).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"authorized_keys file not found: {p}")
        if p.stat().st_size == 0:
            raise SystemExit(f"authorized_keys file is empty: {p}")
        return p, None
    text = args.authorized_keys_text
    if not text or not text.strip():
        raise SystemExit("authorized_keys text is empty")
    return None, text


def build_workspace_mount(
    workspace: str | None,
    mirror: bool,
    user: str,
    container_name: str,
    container_home: str,
) -> str:
    """Return a podman ``--mount`` spec string for the workspace."""
    if mirror:
        src = pathlib.Path(workspace).expanduser().resolve() if workspace else pathlib.Path.cwd().resolve()
        if src == pathlib.Path.home():
            raise SystemExit("--mirror: refusing to mount entire home directory")
        src.mkdir(parents=True, exist_ok=True)
        return f"type=bind,src={src},target={src},rw"

    if workspace:
        src = pathlib.Path(workspace).expanduser().resolve()
    else:
        src = pathlib.Path.home() / "devctk" / container_name
    src.mkdir(parents=True, exist_ok=True)
    return f"type=bind,src={src},target={container_home}/workspace,rw"


def cmd_init(args: argparse.Namespace, passthrough: list[str]) -> int:
    from devctk.cli import NAME_RE

    user = os.environ.get("USER") or pathlib.Path.home().name
    # Default name: workspace-slug if given, else $USER-dev
    if args.container_name:
        container_name = args.container_name
    elif args.workspace:
        import hashlib
        ws = str(pathlib.Path(args.workspace).expanduser().resolve())
        slug = hashlib.sha256(ws.encode()).hexdigest()[:8]
        container_name = f"{pathlib.Path(ws).name}-{slug}"
    else:
        container_name = f"{user}-dev"
    container_home = f"/home/{user}"
    uid = os.getuid()
    gid = os.getgid()

    if not NAME_RE.match(container_name):
        raise SystemExit(f"invalid container name: {container_name}")
    if args.ssh and not 1 <= args.port <= 65535:
        raise SystemExit(f"invalid port: {args.port}")

    # Authorized keys
    ak_file: pathlib.Path | None = None
    ak_text: str | None = None
    if args.ssh:
        ak_file, ak_text = resolve_authorized_keys(args)

    # Workspace
    workspace_mount: str | None = None
    if not args.no_workspace:
        workspace_mount = build_workspace_mount(
            args.workspace, args.mirror, user, container_name, container_home,
        )

    # --- Collect all container mounts ---
    container_mounts: list[str] = []

    # Workspace (first — it's the outermost bind under $HOME)
    if workspace_mount:
        container_mounts.append(workspace_mount)

    # Nix + mise
    nix_profile_content = ""
    container_env: list[str] = []
    if args.nix:
        from devctk.nix import nix_mounts, nix_path_entries, nix_profile_script
        from devctk.nix import mise_mounts, mise_path_entries
        for host, target, mode in nix_mounts(user):
            container_mounts.append(f"type=bind,src={host},target={target},{mode}")
        for host, target, mode in mise_mounts():
            container_mounts.append(f"type=bind,src={host},target={target},{mode}")
        nix_profile_content = nix_profile_script(user)
        # PATH for podman exec sessions (not just SSH login shells)
        path_parts = nix_path_entries(user) + mise_path_entries()
        path_parts += ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        container_env.append(f"PATH={':'.join(path_parts)}")

    # Agent config dirs
    if args.agent:
        from devctk.agent import agent_mounts
        for host, target, mode in agent_mounts(args.agent, container_home):
            container_mounts.append(f"type=bind,src={host},target={target},{mode}")

    # User extra mounts
    container_mounts.extend(args.mount)

    # --- Binaries ---
    podman = require_binary("podman")

    # --- Conflict checks ---
    if run([podman, "container", "exists", container_name], check=False).returncode == 0:
        raise SystemExit(f"container already exists: {container_name}")

    paths = managed_paths(container_name)
    managed_files = [paths.bootstrap_helper, paths.metadata]
    if args.systemd:
        managed_files.extend([paths.container_unit, paths.container_helper])
        if args.ssh:
            managed_files.extend([paths.sshd_unit, paths.sshd_helper])
    for p in managed_files:
        if p.exists():
            raise SystemExit(f"managed files already exist for {container_name}")

    # --- Write bootstrap script ---
    write_text(
        paths.bootstrap_helper,
        render_bootstrap(
            podman=podman,
            name=container_name,
            user=user,
            uid=uid,
            gid=gid,
            home=container_home,
            ssh=args.ssh,
            nix_profile=nix_profile_content,
            authorized_keys_file=str(ak_file) if ak_file else None,
            authorized_keys_text=ak_text,
        ),
        stat.S_IRWXU,
    )

    if args.systemd:
        _init_systemd(args, podman, container_name, container_mounts, container_env,
                       passthrough, paths, user)
    else:
        _init_inline(args, podman, container_name, container_mounts, container_env,
                      passthrough, paths, user)

    # --- Metadata ---
    write_text(paths.metadata, json.dumps({
        "container_name": container_name,
        "image": args.image,
        "ssh": args.ssh,
        "port": args.port if args.ssh else None,
        "container_home": container_home,
        "workspace_mount": workspace_mount or "",
        "mirror": args.mirror,
        "nix": args.nix,
        "agents": args.agent,
        "systemd": args.systemd,
    }, indent=2, sort_keys=True) + "\n")

    # --- Success ---
    print(f"started {container_name}")
    if args.ssh:
        print(f"  ssh {user}@localhost -p {args.port}")
    print(f"  podman exec -it {container_name} bash")

    return 0


def _init_systemd(args, podman, container_name, container_mounts, container_env,
                   passthrough, paths, user):
    """Systemd-managed mode: write helpers + units, enable and start."""
    from devctk.helpers import render_container_helper, render_sshd_helper

    systemctl = require_binary("systemctl")
    loginctl = require_binary("loginctl")

    write_text(
        paths.container_helper,
        render_container_helper(
            podman=podman, name=container_name, image=args.image,
            mounts=container_mounts, devices=args.device, extra=passthrough,
            env=container_env, ssh_port=args.port if args.ssh else None,
        ),
        stat.S_IRWXU,
    )
    write_text(
        paths.container_unit,
        render_unit("container",
            container_name=container_name,
            container_helper=str(paths.container_helper),
            bootstrap_helper=str(paths.bootstrap_helper),
        ),
    )

    if args.ssh:
        write_text(
            paths.sshd_helper,
            render_sshd_helper(podman=podman, name=container_name),
            stat.S_IRWXU,
        )
        write_text(
            paths.sshd_unit,
            render_unit("sshd",
                container_name=container_name,
                container_unit=paths.container_unit.name,
                sshd_helper=str(paths.sshd_helper),
            ),
        )

    try:
        run([systemctl, "--user", "daemon-reload"])
        run([systemctl, "--user", "enable", "--now", paths.container_unit.name])
        if args.ssh:
            run([systemctl, "--user", "enable", "--now", paths.sshd_unit.name])
    except Exception:
        print(f"startup failed, cleaning up {container_name}", file=sys.stderr)
        _cleanup(podman, systemctl, paths, container_name)
        raise

    res = run([loginctl, "show-user", user, "-p", "Linger"], check=False, capture=True)
    if res.returncode == 0 and res.stdout.strip().endswith("no"):
        print(f"  hint: sudo loginctl enable-linger {user}", file=sys.stderr)


def _init_inline(args, podman, container_name, container_mounts, container_env,
                  passthrough, paths, user):
    """Inline mode: create, start, bootstrap directly — no systemd."""
    from devctk.helpers import build_create_cmd

    create_cmd = build_create_cmd(
        podman=podman, name=container_name, image=args.image,
        mounts=container_mounts, devices=args.device, extra=passthrough,
        env=container_env, ssh_port=args.port if args.ssh else None,
    )

    try:
        run(create_cmd)
        run([podman, "start", container_name])
        run([str(paths.bootstrap_helper)])
    except Exception:
        print(f"startup failed, cleaning up {container_name}", file=sys.stderr)
        run([podman, "rm", "-f", "--ignore", container_name], check=False, capture=True)
        for p in [paths.bootstrap_helper, paths.metadata]:
            unlink_if_exists(p)
        raise


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

def cmd_ls() -> int:
    names = list_names()
    if not names:
        print("no devctk containers")
        return 0

    podman = require_binary("podman")

    for name in names:
        paths = managed_paths(name)
        meta = _read_meta(paths.metadata)
        parts = [
            name,
            f"podman={_container_status(podman, name)}",
            f"image={meta.get('image', '-')}",
        ]
        if meta.get("ssh"):
            parts.append(f"port={meta.get('port', '-')}")
        if meta.get("nix"):
            parts.append("nix")
        agents = meta.get("agents", [])
        if agents:
            parts.append(f"agents={','.join(agents)}")
        if meta.get("mirror"):
            parts.append("mirror")
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
        all_paths = [
            paths.metadata, paths.container_helper, paths.bootstrap_helper,
            paths.sshd_helper, paths.container_unit, paths.sshd_unit,
        ]
        exists = any(p.exists() for p in all_paths)
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

    for p in [paths.container_unit, paths.sshd_unit, paths.sshd_helper,
              paths.container_helper, paths.bootstrap_helper, paths.metadata]:
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
    for p in d.glob("*-bootstrap.sh"):
        names.add(p.name.removesuffix("-bootstrap.sh"))
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
