# devctk

One-command setup for SSH-accessible rootless Podman dev containers, managed by systemd user services.

```
uvx devctk --image ubuntu:24.04 --authorized-keys-file ~/.ssh/authorized_keys
```

You get: a running container with your UID mapped in, sshd on localhost, workspace bind-mounted, passwordless sudo, and auto-start via systemd.

## Distribution

- PyPI package, runnable via `uvx devctk`
- Pure Python, minimum 3.10

## Host Requirements

Podman (rootless), systemd, loginctl. Refuses to run as root.

## Commands

**`init`** (default) — create and start a dev container.

- `--image` (required), `--authorized-keys` or `--authorized-keys-file` (required)
- `--port` (default 39000), `--container-name` (default `<user>-dev`), `--container-user` (default host user)
- `--workspace` (default `~/dev-container`), `--no-workspace`
- `--mount`, `--device` (repeatable), extra podman flags after `--`

**`ls`** — list managed containers with status.

**`rm [NAME] [--all]`** — stop and remove container, units, and state.

## What `init` Does

1. Create rootless Podman container (`--userns keep-id`, `--init`, SSH port on 127.0.0.1)
2. Bootstrap inside container: install openssh-server + sudo (apt-get), create user matching host UID/GID, configure sshd (key-only), grant passwordless sudo
3. Install two systemd user units: container service + sshd service (depends on container)
4. Enable and start both

## File Layout

```
~/.config/systemd/user/<name>.service, <name>-sshd.service
~/.local/state/devctk/<name>.json, <name>-container.sh, <name>-sshd.sh
```

## Constraints

- Rootless only (no root)
- SSH bound to 127.0.0.1
- apt-get containers only (Debian/Ubuntu)
- One-shot CLI; systemd handles lifecycle
