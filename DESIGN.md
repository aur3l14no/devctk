# devctk

One-command rootless Podman dev containers.

```
devctk init --image ubuntu:24.04
devctk init --image ubuntu:24.04 --systemd --ssh --authorized-keys-file ~/.ssh/authorized_keys
devctk init --image alpine:latest --nix --agent claude --mirror --workspace ~/projects/myapp
```

You get: a running container with your UID mapped in, workspace bind-mounted, passwordless sudo, and optionally SSH + Nix/mise tools + agent configs + systemd persistence.

## Distribution

- PyPI package, runnable via `uvx devctk`
- Pure Python, minimum 3.11

## Host Requirements

Podman (rootless). systemd optional (for `--systemd` mode).

## Commands

**`init`** (default) — create and start a dev container.

- `--image` (required)
- `--name` (default `<workspace>-<slug>` or `<user>-dev`)
- `--systemd` — manage via systemd user units (auto-start on boot)
- `--ssh` — enable SSH access (requires `--authorized-keys` or `--authorized-keys-file`)
- `--port` (default 39000, requires `--ssh`)
- `--nix` — mount Nix store + profiles, set PATH
- `--mise` — mount mise tool installs, set PATH
- `--agent claude|codex` (repeatable) — mount agent config dirs
- `--mirror` — workspace at same absolute path as host
- `--workspace PATH` (default `~/devctk/<name>`)
- `--no-workspace` — skip workspace mount
- `--mount`, `--device` (repeatable), extra podman flags after `--`

**`ls`** — list managed containers with status.

**`rm [NAME] [--all]`** — stop and remove container and state.

## Lifecycle Modes

### Inline (default)

Container is created, started, and bootstrapped directly via podman commands. No systemd units. The container stays running until stopped manually or the host reboots. Access via `podman exec -it NAME bash`.

### Systemd (`--systemd`)

Container is managed by systemd user units with auto-restart and boot persistence. Requires `loginctl enable-linger` for the user. If `--ssh` is enabled, a second unit manages sshd.

## What `init` Does

1. Create rootless Podman container (`--userns keep-id`, `--init`, `sleep infinity`)
2. Start container (inline: `podman start`; systemd: `systemctl enable --now`)
3. Bootstrap via `podman exec --user root` (ExecStartPost in systemd mode):
   - Detect package manager (apt/apk), install sudo + bash if missing
   - Create user matching host UID/GID with passwordless sudo
   - If `--nix`: write `/etc/profile.d/99-devctk-nix.sh`
   - If `--ssh`: install sshd, configure key-only auth
   - Signal readiness via `/run/devctk-ready`
4. If `--systemd --ssh`: start sshd unit (waits for bootstrap readiness)

## Features

### SSH (`--ssh`)

SSH access via `ssh user@localhost -p PORT`. Requires authorized keys. Installs sshd inside the container, binds to 127.0.0.1 only. With `--systemd`, managed by a separate unit that depends on the container unit.

Without `--ssh`, access the container via `podman exec -it NAME bash`.

### Nix (`--nix`)

Mounts `/nix/store`, `/etc/profiles/per-user/<user>`, and `/run/current-system` read-only. Uses unresolved symlink-tree paths so mounts survive `nixos-rebuild` + garbage collection.

Also mounts `~/.local/share/mise/installs` if present (mise-managed tools).

Sets PATH via `-e` at container create time (for `podman exec` sessions) and writes `/etc/profile.d/` (for SSH login shells).

### Agent configs (`--agent claude|codex`)

Mounts agent config directories into the container user's home (read-write):
- `--agent claude`: `~/.claude/` + `~/.claude.json`
- `--agent codex`: `~/.codex/`

No preprocessing — mount as-is. Container detection for scripts: check `/run/.containerenv` (podman auto-creates this).

### Mirror mode (`--mirror`)

Mounts workspace at the same absolute path in host and container. Enables agent session continuity (e.g., Claude's project history is keyed by absolute path). Refuses to mount `$HOME` itself. Default workspace in mirror mode: current directory.

### Container naming

Default name when `--workspace` is given: `<dirname>-<8char-hash>` (e.g., `myapp-a3f2b1c0`). The hash is derived from the full workspace path, so two workspaces named `foo` in different directories get different container names. Without `--workspace`, defaults to `<user>-dev`.

## File Layout

```
~/.local/state/devctk/<name>.json              # metadata (always)
~/.local/state/devctk/<name>-bootstrap.sh      # bootstrap script (always)
~/.local/state/devctk/<name>-container.sh      # container helper (systemd only)
~/.config/systemd/user/<name>.service          # container unit (systemd only)
~/.local/state/devctk/<name>-sshd.sh           # sshd helper (systemd + ssh only)
~/.config/systemd/user/<name>-sshd.service     # sshd unit (systemd + ssh only)
```

## Supported Images

Debian/Ubuntu (apt) and Alpine (apk). Other images work if sudo + bash are pre-installed.

## Constraints

- Rootless only (no root)
- SSH bound to 127.0.0.1 (when enabled)
- Container user is always the host user (same name, UID, GID)
- Bootstrap runs via `podman exec --user root` (works with `--userns keep-id`)
