# devctk

Container toolkit for spinning up rootless podman dev containers, with QoL features for SSH and agent.

## Install

```
pip install devctk
# or
uvx devctk --help
```

Requires: Linux, Podman (rootless). Python 3.11+. systemd optional (for auto-start).

## Usage

### Basic container (local dev, access via `podman exec`)

```sh
devctk init --image ubuntu:24.04
podman exec -it $USER-dev bash
```

### SSH-accessible persistent container (remote server)

```sh
devctk init --image ubuntu:24.04 \
  --systemd --ssh --authorized-keys-file ~/.ssh/authorized_keys --port 39000
ssh $USER@localhost -p 39000
```

### With Nix tools from the host

```sh
devctk init --image alpine:latest --nix --mise
```

`--nix` mounts `/nix/store` and your user profile read-only. `--mise` mounts `~/.local/share/mise/installs`. Both set PATH so tools are available inside the container without rebuilding the image. Either flag works independently.

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
  --systemd --ssh --authorized-keys-file ~/.ssh/authorized_keys \
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
- Workspace bind-mounted (default: `~/devctk/<name>` on host → `/home/$USER/workspace` in container; with `--mirror`: same absolute path on both sides)
- Debian/Ubuntu and Alpine images supported out of the box
- With `--systemd`: auto-start on boot via systemd user units (requires `loginctl enable-linger`)
- With `--nix`/`--mise`: host Nix store and/or mise tools forwarded into container, PATH set automatically
- With `--agent`: agent config dirs mounted for session continuity

## Flags

| Flag | Description |
|---|---|
| `--image IMAGE` | Base image (required) |
| `--name NAME` | Container name (default: `<workspace>-<slug>` or `<user>-dev`) |
| `--systemd` | Manage via systemd user units (auto-start on boot) |
| `--ssh` | Enable SSH access |
| `--authorized-keys[-file]` | SSH public keys (required with `--ssh`) |
| `--port PORT` | SSH port (default: 39000) |
| `--nix` | Mount Nix store + profiles, set PATH |
| `--mise` | Mount mise tool installs, set PATH |
| `--agent claude\|codex` | Mount agent config dirs (repeatable) |
| `--mirror` | Workspace at same absolute path as host |
| `--workspace PATH` | Override workspace directory |
| `--no-workspace` | Skip workspace mount |
| `--mount SPEC` | Extra bind mount (repeatable) |
| `--device DEV` | Pass through device (repeatable) |
