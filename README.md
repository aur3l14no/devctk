# devctk

Container toolkit for spinning up rootless podman dev containers, with QoL features for SSH and agent.

## Install

```
pip install devctk
# or
uvx devctk --help
```

Requires: Linux, Podman (rootless), systemd. Python 3.11+.

## Usage

### Basic container (local dev, access via `podman exec`)

```sh
devctk init --image ubuntu:24.04
podman exec -it $USER-dev bash
```

### SSH-accessible container (remote server)

```sh
devctk init --image ubuntu:24.04 \
  --ssh --authorized-keys-file ~/.ssh/authorized_keys --port 39000
ssh $USER@localhost -p 39000
```

### With Nix tools from the host

```sh
devctk init --image alpine:latest --nix
```

Mounts `/nix/store` and your user profile read-only. All your Nix-installed tools are available inside the container without rebuilding the image.

### With AI agent configs

```sh
devctk init --image ubuntu:24.04 --agent claude --agent codex
```

Mounts `~/.claude/`, `~/.claude.json`, `~/.codex/` into the container so agents authenticate and pick up your settings.

### Mirror mode (same paths as host)

```sh
devctk init --image ubuntu:24.04 --agent claude --mirror --workspace ~/projects/myapp
```

Workspace is mounted at the same absolute path inside the container. Agent session history (keyed by path) is shared between host and container.

### All together

```sh
devctk init --image ubuntu:24.04 \
  --ssh --authorized-keys-file ~/.ssh/authorized_keys \
  --nix --agent claude --mirror --workspace ~/projects/myapp
```

### Management

```sh
devctk ls          # list containers
devctk rm mydev    # remove a container
devctk rm --all    # remove all
```

## What you get

- Rootless Podman container with `--userns keep-id` (your UID inside = your UID outside)
- Passwordless sudo
- Auto-start on boot via systemd user units (with `loginctl enable-linger`)
- Workspace bind-mounted (default `~/devctk/<name>` on host, `/home/<you>/workspace` in container)
- Debian/Ubuntu and Alpine images supported out of the box

## Flags

| Flag | Description |
|---|---|
| `--image IMAGE` | Base image (required) |
| `--name NAME` | Container name (default: `<user>-dev`) |
| `--ssh` | Enable SSH access |
| `--authorized-keys[-file]` | SSH public keys (required with `--ssh`) |
| `--port PORT` | SSH port (default: 39000) |
| `--nix` | Mount Nix store + profiles, set PATH |
| `--agent claude\|codex` | Mount agent config dirs (repeatable) |
| `--mirror` | Workspace at same absolute path as host |
| `--workspace PATH` | Override workspace directory |
| `--no-workspace` | Skip workspace mount |
| `--mount SPEC` | Extra bind mount (repeatable) |
| `--device DEV` | Pass through device (repeatable) |
