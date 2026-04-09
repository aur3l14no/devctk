# devctk

One-command rootless Podman dev containers, managed by systemd user services.

```
devctk init --image ubuntu:24.04
devctk init --image ubuntu:24.04 --ssh --authorized-keys-file ~/.ssh/authorized_keys
devctk init --image alpine:latest --nix --agent claude --mirror --workspace ~/projects/myapp
```

You get: a running container with your UID mapped in, workspace bind-mounted, passwordless sudo, auto-start via systemd, and optionally SSH + Nix tools + agent configs.

## Distribution

- PyPI package, runnable via `uvx devctk`
- Pure Python, minimum 3.11

## Host Requirements

Podman (rootless), systemd, loginctl. Refuses to run as root.

## Commands

**`init`** (default) — create and start a dev container.

- `--image` (required)
- `--name` (default `<user>-dev`)
- `--ssh` — enable SSH access (requires `--authorized-keys` or `--authorized-keys-file`)
- `--port` (default 39000, requires `--ssh`)
- `--nix` — mount Nix store + profiles, set PATH
- `--agent claude|codex` (repeatable) — mount agent config dirs
- `--mirror` — workspace at same absolute path as host
- `--workspace PATH` (default `~/devctk/<name>`)
- `--no-workspace` — skip workspace mount
- `--mount`, `--device` (repeatable), extra podman flags after `--`

**`ls`** — list managed containers with status.

**`rm [NAME] [--all]`** — stop and remove container, units, and state.

## What `init` Does

1. Write a bootstrap script (container entrypoint) to the state dir
2. Create rootless Podman container (`--userns keep-id`, `--init`, bootstrap as entrypoint)
3. Bootstrap runs on every container start (idempotent):
   - Detect package manager (apt/apk), install sudo + bash if missing
   - Create user matching host UID/GID with passwordless sudo
   - If `--nix`: write `/etc/profile.d/99-devctk-nix.sh`
   - If `--ssh`: install sshd, configure key-only auth, write sshd config
   - Signal readiness via `/run/devctk-ready`, then exec `sleep infinity`
4. Install systemd user unit for the container
5. If `--ssh`: install a second unit for sshd (waits for bootstrap readiness)
6. Enable and start

## Features

### SSH (`--ssh`)

SSH access via `ssh user@localhost -p PORT`. Requires authorized keys. Installs sshd inside the container, binds to 127.0.0.1 only. Managed by a separate systemd unit that depends on the container unit.

Without `--ssh`, access the container via `podman exec -it NAME bash`.

### Nix (`--nix`)

Mounts `/nix/store`, `/etc/profiles/per-user/<user>`, and `/run/current-system` read-only. Uses unresolved symlink-tree paths (not `.resolve()`) so mounts survive `nixos-rebuild` + garbage collection. Writes PATH to `/etc/profile.d/` for SSH login shells.

### Agent configs (`--agent claude|codex`)

Mounts agent config directories into the container user's home (read-write):
- `--agent claude`: `~/.claude/` + `~/.claude.json`
- `--agent codex`: `~/.codex/`

No preprocessing — mount as-is. Container detection for scripts: check `/run/.containerenv` (podman auto-creates this).

### Mirror mode (`--mirror`)

Mounts workspace at the same absolute path in host and container. Enables agent session continuity (e.g., Claude's project history is keyed by absolute path). Refuses to mount `$HOME` itself. Default workspace in mirror mode: current directory.

## File Layout

```
~/.config/systemd/user/<name>.service[, <name>-sshd.service]
~/.local/state/devctk/<name>.json, <name>-container.sh, <name>-bootstrap.sh[, <name>-sshd.sh]
```

## Supported Images

Debian/Ubuntu (apt) and Alpine (apk). Other images work if sshd + sudo are pre-installed.

## Constraints

- Rootless only (no root)
- SSH bound to 127.0.0.1 (when enabled)
- Container user is always the host user (same name, UID, GID)
- One-shot CLI; systemd handles lifecycle
