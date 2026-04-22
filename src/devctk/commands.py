"""IO shell: commands (apply/ls/rm) + live snapshot + plan execution.

Pure planning lives in plan.py; this module composes the pure core with
subprocess/filesystem effects.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any, Iterable

from devctk.agent import provision_agents
from devctk.helpers import build_create_cmd, render_bootstrap
from devctk.mise import provision_mise
from devctk.nix import provision_nix
from devctk.paths import ManagedPaths, config_root, managed_paths, state_root
from devctk.plan import (
    Create,
    Destroy,
    LiveSnapshot,
    LiveStatus,
    Noop,
    PlanStep,
    Recreate,
    Start,
    Update,
    plan_all,
    step_kind,
    step_name,
)
from devctk.provision import Provision, provision_workspace
from devctk.spec import (
    AppConfig,
    AuthKeysFile,
    AuthKeysInline,
    ContainerSpec,
    SSHOn,
    SpecError,
    WorkspaceOn,
    full_fingerprint,
    full_hash,
    default_config_text,
    load_config,
    runtime_hash,
)
from devctk.state import (
    AppState,
    StateEntry,
    StateError,
    read_state,
    with_entry,
    without_entry,
    write_state,
)
from devctk.systemd import render_service_unit
from devctk.util import require_binary, run, unlink_if_exists, write_text


# ====================================================================
# Command entry points
# ====================================================================

def cmd_apply(args: argparse.Namespace) -> int:
    paths = managed_paths()
    podman = require_binary("podman")
    config = _load_config_or_exit(paths)
    state = _load_state_or_exit(paths)

    all_names = set(config.by_name()) | set(state.containers)
    live = snapshot_live(podman, all_names)
    plan = plan_all(config.by_name(), state, live, autostart_only=args.autostart_only)
    _print_plan(plan)

    changed = [s for s in plan if not isinstance(s, Noop)]
    if not changed:
        print("No changes. Infrastructure is up-to-date.")
        if not args.autostart_only:
            _sync_autostart_service(paths, config, podman)
        return 0

    _confirm_apply(changed, args.yes)
    try:
        execute_plan(plan, state, paths=paths, podman=podman)
    except SpecError as exc:
        raise SystemExit(str(exc)) from exc
    if not args.autostart_only:
        _sync_autostart_service(paths, config, podman)
    return 0


def cmd_ls() -> int:
    paths = managed_paths()
    podman = require_binary("podman")
    state = _load_state_or_exit(paths)

    config: AppConfig | None = None
    config_error: str | None = None
    if paths.config_file.exists():
        try:
            config = load_config(paths.config_file)
        except SpecError as exc:
            config_error = str(exc)
    specs = config.by_name() if config else {}
    names = sorted(set(specs) | set(state.containers))
    if not names:
        print("no devctk containers")
        return 0
    if config_error is not None:
        print(f"config=invalid({config_error})")

    live = snapshot_live(podman, names)
    pending: dict[str, str] = {}
    if config is not None:
        for step in plan_all(specs, state, live):
            if not isinstance(step, Noop):
                pending[step_name(step)] = step_kind(step)

    for name in names:
        spec = specs.get(name)
        parts = [name, f"podman={live.get(name, LiveSnapshot()).status.value}"]
        if spec is not None:
            parts.extend(_describe_spec(spec))
            if name in pending:
                parts.append(f"pending={pending[name]}")
        else:
            parts.append("state-only")
        print("  ".join(parts))
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    paths = managed_paths()
    podman = require_binary("podman")
    state = _load_state_or_exit(paths)
    config_names = _config_names(paths)

    if args.container_name and args.all:
        raise SystemExit("rm accepts either a container name or --all")
    if args.all:
        names = sorted(state.containers)
    elif args.container_name:
        names = [args.container_name]
    else:
        raise SystemExit("rm requires a container name or --all")
    names = [n for n in names if n]
    if not names:
        print("no devctk containers")
        return 0

    _confirm_rm(names, args.yes)

    current = state
    for name in names:
        _destroy_container(podman, name)
        current = without_entry(current, name)
        write_state(paths.runtime_state, current)
        print(f"removed {name}")
        if name in config_names:
            print(
                f"  note: {name} is still present in {paths.config_file}; "
                f"next apply will recreate it"
            )
    return 0


# ====================================================================
# Loaders
# ====================================================================

def _load_config_or_exit(paths: ManagedPaths) -> AppConfig:
    try:
        return load_config(paths.config_file)
    except SpecError as exc:
        sample = default_config_text().rstrip()
        raise SystemExit(
            f"{exc}\n\nCreate {paths.config_file} manually, for example:\n\n{sample}"
        ) from exc


def _load_state_or_exit(paths: ManagedPaths) -> AppState:
    try:
        return read_state(paths.runtime_state)
    except StateError as exc:
        raise SystemExit(str(exc)) from exc


def _config_names(paths: ManagedPaths) -> set[str]:
    if not paths.config_file.exists():
        return set()
    try:
        config = load_config(paths.config_file)
    except SpecError:
        return set()
    return {c.name for c in config.containers}


# ====================================================================
# Live snapshot (IO)
# ====================================================================

def snapshot_live(podman: str, names: Iterable[str]) -> dict[str, LiveSnapshot]:
    out: dict[str, LiveSnapshot] = {}
    for name in names:
        status = _container_status(podman, name)
        sshd = _sshd_running(podman, name) if status is LiveStatus.RUNNING else False
        out[name] = LiveSnapshot(status=status, sshd_running=sshd)
    return out


def _container_status(podman: str, name: str) -> LiveStatus:
    res = run([podman, "inspect", "-f", "{{.State.Status}}", name], check=False, capture=True)
    if res.returncode != 0:
        return LiveStatus.MISSING
    return LiveStatus.RUNNING if res.stdout.strip() == "running" else LiveStatus.STOPPED


def _sshd_running(podman: str, name: str) -> bool:
    res = run(
        [podman, "exec", name, "/bin/sh", "-lc", "pgrep -x sshd >/dev/null 2>&1"],
        check=False,
        capture=True,
    )
    return res.returncode == 0


# ====================================================================
# Plan display
# ====================================================================

_KINDS = ("create", "recreate", "start", "update", "destroy", "noop")


def _print_plan(plan: tuple[PlanStep, ...]) -> None:
    counts = {k: 0 for k in _KINDS}
    for s in plan:
        counts[step_kind(s)] += 1
    print("Plan: " + ", ".join(
        f"{counts[k]} to {k}" if k != "noop" else f"{counts[k]} unchanged"
        for k in _KINDS
    ))
    for step in plan:
        if isinstance(step, Noop):
            continue
        print(f"\n{step_name(step)}: {step_kind(step)}")
        for line in _step_body(step):
            print(f"  {line}")


def _step_body(step: PlanStep) -> Iterable[str]:
    match step:
        case Create(reason=r, spec=s):
            if r: yield f"reason: {r}"
            yield from _summary_lines(s)
        case Recreate(reason=r, changes=cs):
            if r: yield f"reason: {r}"
            yield from _change_lines(cs)
        case Start(reason=r):
            yield f"reason: {r}"
        case Update(changes=cs):
            yield from _change_lines(cs)
        case Destroy(reason=r):
            yield f"reason: {r}"
            yield "will be removed"


def _change_lines(changes: Iterable[Any]) -> Iterable[str]:
    for c in changes:
        yield f"{c.path}: {_fmt(c.before)} -> {_fmt(c.after)}"


def _fmt(value: Any) -> str:
    return "null" if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _summary_lines(spec: ContainerSpec) -> Iterable[str]:
    yield f"image: {spec.image}"
    if spec.systemd: yield "systemd: true"
    if isinstance(spec.workspace, WorkspaceOn):
        m = " (mirror)" if spec.workspace.mirror else ""
        yield f"workspace: {spec.workspace.path}{m}"
    if isinstance(spec.ssh, SSHOn): yield f"ssh.port: {spec.ssh.port}"
    if spec.agents: yield f"agents: {', '.join(spec.agents)}"
    if spec.nix: yield "nix: true"
    if spec.mise: yield "mise: true"
    if spec.extra_create_args:
        yield f"extra_create_args: {_fmt(list(spec.extra_create_args))}"


def _describe_spec(spec: ContainerSpec) -> Iterable[str]:
    yield f"image={spec.image}"
    if spec.systemd: yield "autostart"
    if isinstance(spec.ssh, SSHOn): yield f"port={spec.ssh.port}"
    if spec.nix: yield "nix"
    if spec.mise: yield "mise"
    if spec.agents: yield f"agents={','.join(spec.agents)}"
    if isinstance(spec.workspace, WorkspaceOn) and spec.workspace.mirror:
        yield "mirror"


# ====================================================================
# Confirmation
# ====================================================================

def _confirm_apply(changed: list[PlanStep], yes: bool) -> None:
    destructive = any(isinstance(s, (Recreate, Destroy)) for s in changed)
    if destructive:
        print(
            "\nWarning: recreated or destroyed containers lose writable-layer data; "
            "bind-mounted data is preserved.",
            file=sys.stderr,
        )
    if yes:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("apply requires --yes when stdin is not interactive")
    print("\nOnly 'yes' will be accepted to approve.")
    if input("Enter a value: ").strip() != "yes":
        raise SystemExit("aborted")


def _confirm_rm(names: list[str], yes: bool) -> None:
    if yes:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("rm requires --yes when stdin is not interactive")
    print(f"About to remove: {', '.join(names)}")
    print("Only 'yes' will be accepted to approve.")
    if input("Enter a value: ").strip() != "yes":
        raise SystemExit("aborted")


# ====================================================================
# Plan execution (IO, transactional)
# ====================================================================

def execute_plan(
    plan: tuple[PlanStep, ...],
    state: AppState,
    *,
    paths: ManagedPaths,
    podman: str,
) -> AppState:
    """Run each step and persist state after each. A mid-plan failure
    leaves a consistent prefix on disk."""
    user = os.environ.get("USER") or pathlib.Path.home().name
    uid = os.getuid()
    gid = os.getgid()
    current = state
    for step in plan:
        current = _execute_step(step, current, podman=podman, user=user, uid=uid, gid=gid)
        write_state(paths.runtime_state, current)
    return current


def _execute_step(
    step: PlanStep,
    state: AppState,
    *,
    podman: str,
    user: str,
    uid: int,
    gid: int,
) -> AppState:
    match step:
        case Noop():
            return state
        case Destroy(name=name):
            _destroy_container(podman, name)
            return without_entry(state, name)
        case Create(spec=spec) | Recreate(spec=spec):
            _realize_container(spec, podman=podman, user=user, uid=uid, gid=gid)
            return with_entry(
                state,
                spec.name,
                _state_entry_for(
                    spec, podman=podman, generation=_bump_generation(state, spec.name)
                ),
            )
        case Start(spec=spec):
            _start_container(spec, podman=podman, user=user, uid=uid, gid=gid)
            prev = state.containers.get(spec.name)
            generation = prev.generation if prev else 1
            return with_entry(
                state, spec.name, _state_entry_for(spec, podman=podman, generation=generation)
            )
        case Update(spec=spec):
            prev = state.containers.get(spec.name)
            generation = prev.generation if prev else 1
            return with_entry(
                state, spec.name, _state_entry_for(spec, podman=podman, generation=generation)
            )
    raise AssertionError(f"unreachable: {step}")


def _bump_generation(state: AppState, name: str) -> int:
    prev = state.containers.get(name)
    return (prev.generation + 1) if prev else 1


def _state_entry_for(spec: ContainerSpec, *, podman: str, generation: int) -> StateEntry:
    res = run([podman, "inspect", "-f", "{{.Id}}", spec.name], check=False, capture=True)
    container_id = res.stdout.strip() if res.returncode == 0 else ""
    return StateEntry(
        spec=full_fingerprint(spec),
        full_hash=full_hash(spec),
        runtime_hash=runtime_hash(spec),
        systemd=spec.systemd,
        generation=generation,
        container_id=container_id,
        last_applied_at=datetime.now().astimezone().isoformat(),
    )


# ====================================================================
# Container operations (IO)
# ====================================================================

def _realize_container(
    spec: ContainerSpec,
    *,
    podman: str,
    user: str,
    uid: int,
    gid: int,
) -> None:
    container_home = f"/home/{user}"
    provision = _build_provision(spec, user=user, container_home=container_home)
    env = _env_from_provision(provision)
    profile = _profile_from_provision(provision)

    port = spec.ssh.port if isinstance(spec.ssh, SSHOn) else None
    create_cmd = build_create_cmd(
        podman=podman,
        name=spec.name,
        image=spec.image,
        mounts=[m.as_arg() for m in provision.mounts],
        extra=list(spec.extra_create_args),
        env=env,
        ssh_port=port,
    )

    ak_file, ak_text = _resolve_keys(spec)
    bootstrap = render_bootstrap(
        podman=podman,
        name=spec.name,
        user=user,
        uid=uid,
        gid=gid,
        home=container_home,
        ssh=isinstance(spec.ssh, SSHOn),
        nix_profile=profile,
        authorized_keys_file=str(ak_file) if ak_file else None,
        authorized_keys_text=ak_text,
    )

    _destroy_container(podman, spec.name)
    try:
        run(create_cmd)
        run([podman, "start", spec.name])
        subprocess.run(["/bin/sh"], check=True, text=True, input=bootstrap)
        _ensure_sshd_running(spec, podman)
    except Exception:
        print(f"startup failed, cleaning up {spec.name}", file=sys.stderr)
        _destroy_container(podman, spec.name)
        raise


def _start_container(
    spec: ContainerSpec, *, podman: str, user: str, uid: int, gid: int
) -> None:
    status = _container_status(podman, spec.name)
    if status is LiveStatus.MISSING:
        _realize_container(spec, podman=podman, user=user, uid=uid, gid=gid)
        return
    if status is not LiveStatus.RUNNING:
        run([podman, "start", spec.name])
    _ensure_sshd_running(spec, podman)


def _ensure_sshd_running(spec: ContainerSpec, podman: str) -> None:
    if not isinstance(spec.ssh, SSHOn):
        return
    if _sshd_running(podman, spec.name):
        return
    run(
        [podman, "exec", "-d", "--user", "root", spec.name, "/bin/sh", "-lc",
         'exec "$(command -v sshd)" -D -e']
    )


def _destroy_container(podman: str, name: str) -> None:
    res = run([podman, "rm", "-f", "--ignore", name], check=False, capture=True)
    if res.returncode != 0 and res.stderr.strip():
        print(f"warning: podman rm failed for {name}: {res.stderr.strip()}", file=sys.stderr)


def _resolve_keys(spec: ContainerSpec) -> tuple[pathlib.Path | None, str | None]:
    if not isinstance(spec.ssh, SSHOn):
        return None, None
    keys = spec.ssh.keys
    if isinstance(keys, AuthKeysFile):
        return keys.path, None
    if isinstance(keys, AuthKeysInline):
        return None, keys.text
    raise AssertionError(f"unreachable: {keys}")


# ====================================================================
# Provision composition
# ====================================================================

def _build_provision(spec: ContainerSpec, *, user: str, container_home: str) -> Provision:
    return Provision.combine(
        [
            provision_workspace(spec.workspace, container_home),
            provision_nix(user) if spec.nix else Provision(),
            provision_mise() if spec.mise else Provision(),
            provision_agents(spec.agents, container_home),
        ]
    )


_STD_PATHS = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")


def _env_from_provision(p: Provision) -> list[str]:
    if not p.path_head and not p.path_tail:
        return []
    full = list(p.path_head) + list(_STD_PATHS) + list(p.path_tail)
    return [f"PATH={':'.join(full)}"]


def _profile_from_provision(p: Provision) -> str:
    lines = ""
    if p.path_head:
        # login-shell PATH also exports sbins
        entries = list(p.path_head) + ["/usr/local/sbin", "/usr/sbin", "/sbin"]
        lines = f'export PATH="{":".join(entries)}:$PATH"\n'
    if p.profile_snippet:
        lines += p.profile_snippet
    return lines


# ====================================================================
# Systemd autostart unit (IO)
# ====================================================================

def _sync_autostart_service(paths: ManagedPaths, config: AppConfig, podman: str) -> None:
    autostart = [s for s in config.containers if s.systemd]
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        if autostart:
            raise SystemExit("systemd autostart requested but systemctl is not available")
        return

    if not autostart:
        run([systemctl, "--user", "disable", paths.service_name], check=False, capture=True)
        unlink_if_exists(paths.service_unit)
        run([systemctl, "--user", "daemon-reload"], check=False)
        return

    unit_path = os.pathsep.join((os.path.dirname(podman), *_STD_PATHS))
    write_text(
        paths.service_unit,
        render_service_unit(
            python=sys.executable,
            path=unit_path,
            xdg_config_home=str(config_root()),
            xdg_state_home=str(state_root()),
        ),
    )
    run([systemctl, "--user", "daemon-reload"])
    run([systemctl, "--user", "enable", paths.service_name])

    loginctl = shutil.which("loginctl")
    if loginctl:
        user = os.environ.get("USER") or pathlib.Path.home().name
        res = run([loginctl, "show-user", user, "-p", "Linger"], check=False, capture=True)
        if res.returncode == 0 and res.stdout.strip().endswith("no"):
            print(f"hint: sudo loginctl enable-linger {user}", file=sys.stderr)
