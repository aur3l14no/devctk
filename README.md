# devctk

Declarative rootless Podman dev containers with SSH, Nix, mise, and agent mounts.

`devctk` reads one config file, compares it with its recorded state, and applies the minimum needed plan:

- `create` when a container is new
- `recreate` when the canonical config changed
- `start` when the config matches but the container is missing or stopped
- `destroy` when a container was removed from config

Whitespace and TOML formatting do not matter. The comparison is done on a normalized semantic form, not the raw file text.

## Install

```sh
uv tool install devctk
```

`pip install devctk` also works, but `uv tool install` is the cleaner path if you want systemd autostart.

Requires:

- Linux
- Podman rootless
- Python 3.11+
- systemd user services if you want autostart

## Files

`devctk` writes only these XDG-managed files:

- `~/.config/devctk/config.toml`
- `~/.local/state/devctk/state.json`
- `~/.config/systemd/user/devctk.service`

There is no daemon. The systemd unit is a oneshot user service that runs `devctk apply --yes --autostart-only` at login/boot.

## Workflow

1. Write `~/.config/devctk/config.toml`
2. Run `devctk apply`
3. Review the plan and type `yes`

For non-interactive runs:

```sh
devctk apply --yes
```

Useful commands:

```sh
devctk apply
devctk ls
devctk rm mydev
devctk rm --all
```

`rm` removes the live container and tracked state entry. If the container is still present in `config.toml`, the next `apply` will recreate it.

## Config

Example:

```toml
[[containers]]
name = "cuda-dev"
image = "docker.io/nvidia/cuda:13.2.0-cudnn-devel-ubuntu24.04"
systemd = true
agents = ["codex"]
extra_create_args = [
  "--device",
  "nvidia.com/gpu=GPU-ee39c837-99ea-9171-0657-825e2273a414",
  "--shm-size=32G",
  "--mount",
  "type=bind,src=/mnt/data/projects/robotics-2601,target=/data,ro",
]

[containers.workspace]
path = "/home/y/Projects/myproj"
mirror = true

[containers.ssh]
port = 39004
authorized_keys_file = "/home/y/.ssh/container_authorized_keys"
```

### Container fields

All default to off / empty when omitted.

- `name`: Podman container name
- `image`: base image
- `systemd` (bool): include this container in the global autostart service
- `nix` (bool): mount host Nix store and profiles read-only, then expose them on `PATH`
- `mise` (bool): mount host mise installs read-only, then expose them on `PATH`
- `agents`: any of `claude`, `codex`
- `extra_create_args`: raw extra `podman create` argv tokens

### Workspace

Omit the `[containers.workspace]` table to disable. When present:

- `workspace.path`: absolute host path (required)
- `workspace.mirror` (bool, default `false`): mount at the same absolute path inside the container; otherwise mounted at `$HOME/workspace`

When `mirror = true`, `devctk` refuses to mount your entire home directory as the workspace root.

### SSH

Omit the `[containers.ssh]` table to disable. When present:

- `ssh.port` (required)
- exactly one of:
  - `ssh.authorized_keys_file` (must exist and be non-empty at apply time)
  - `ssh.authorized_keys` (inline, non-empty)

SSH binds to `127.0.0.1:<port>` only.

## Notes

- `devctk` is intentionally conservative about Podman-specific features. Most raw Podman knobs should go into `extra_create_args`.
- `extra_create_args` may include things like `--mount`, `--device`, and `--shm-size`.
- Conflicts between `extra_create_args` and devctk-managed options are left to Podman to reject.
- If any container has `systemd = true`, enable linger for the user if you want autostart after reboot:

```sh
sudo loginctl enable-linger "$USER"
```
