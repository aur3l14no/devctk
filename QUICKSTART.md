# devctk quickstart

A longer walkthrough of install, config, and lifecycle. See [README.md](README.md) for the 30-second pitch.

## Install

```sh
uv tool install devctk
```

`pip install devctk` also works, but `uv tool install` is the cleaner path if you want the systemd autostart unit to pick up a stable binary path.

Requires:

- Linux
- Podman, rootless
- Python 3.11+
- systemd user services (only if you want autostart)
- A Debian / Ubuntu base image (the provisioner assumes `apt`)

## What devctk writes

Only these XDG-managed paths:

- `~/.config/devctk/config.toml` — your declarative spec
- `~/.local/state/devctk/state.json` — last-applied normalized spec per container
- `~/.config/systemd/user/devctk.service` — oneshot autostart unit (only if you opt in)

There is no daemon. The systemd unit runs `devctk apply --yes --autostart-only` at login/boot. Autostart mode only starts containers marked `systemd = true` and **never destroys anything** — destructive changes only happen during an explicit `devctk apply`.

## How apply decides what to do

`devctk` reads `config.toml`, compares it with `state.json`, and applies the minimum plan:

| Plan        | When                                                                         |
| ----------- | ---------------------------------------------------------------------------- |
| `create`    | container is new                                                             |
| `recreate`  | a runtime-affecting field changed (`image`, `workspace`, `ssh`, mounts, …)   |
| `start`     | spec matches state but the container is missing or stopped                   |
| `update`    | only metadata changed (e.g. `systemd` flipped); container keeps running      |
| `destroy`   | a container was removed from config (only in explicit `apply`, not autostart)|

Whitespace and TOML formatting do not matter — the comparison is on a normalized semantic form, not the raw file text.

## Workflow

```sh
devctk apply          # interactive: shows plan, waits for `yes`
devctk apply --yes    # non-interactive
devctk ls
devctk rm mydev
devctk rm --all
```

`rm` removes the live container and its tracked state entry. If the container is still present in `config.toml`, the next `apply` will recreate it.

## Autostart after reboot

If any container has `systemd = true`, enable linger for your user:

```sh
sudo loginctl enable-linger "$USER"
```

## Full config reference

```toml
[[containers]]
name = "cuda-dev"
image = "docker.io/nvidia/cuda:13.2.0-cudnn-devel-ubuntu24.04"
systemd = true
nix = true
mise = true
agents = ["claude", "codex"]
extra_create_args = [
  "--device", "nvidia.com/gpu=GPU-ee39c837-99ea-9171-0657-825e2273a414",
  "--shm-size=32G",
  "--mount", "type=bind,src=/mnt/data/projects/robotics-2601,target=/data,ro",
]

[containers.workspace]
path = "/home/you/Projects/myproj"
mirror = true

[containers.ssh]
port = 39004
authorized_keys_file = "/home/you/.ssh/container_authorized_keys"
```

### Container fields

All default to off / empty when omitted.

- `name` — Podman container name
- `image` — base image
- `systemd` (bool) — include in the global autostart oneshot
- `nix` (bool) — mount host `/nix/store` and profiles read-only, expose on `PATH`
- `mise` (bool) — mount host mise installs read-only, expose on `PATH`
- `agents` — any of `claude`, `codex`; bind-mounts the matching host config dir rw into the container so logins and history persist
- `extra_create_args` — raw extra `podman create` argv tokens

### Workspace

Omit `[containers.workspace]` to disable. When present:

- `workspace.path` — absolute host path (required, must already exist)
- `workspace.mirror` (bool, default `false`) — mount at the same absolute path inside the container; otherwise mounted at `$HOME/workspace`

#### Why `mirror = true` is usually the right choice

Claude Code, Codex, and similar agents key their session history (and various caches) by **working directory**. If the host sees your project at `/home/you/Projects/myproj` and the container sees it at `/root/workspace`, a session you started on the host can't be resumed inside the container — different working dir, different session id.

With `mirror = true`, host and container see the project at the same absolute path. You can start `claude` on the host, recreate the container, and resume the same session inside:

```sh
podman exec -it myproj-agent bash -lc "cd /home/you/Projects/myproj && claude --resume"
```

Same applies to anything else that bakes the abs path into a cache or lockfile (uv venvs, `direnv`, IDE workspace state).

Guardrail: `devctk` refuses `mirror = true` when `workspace.path` is your entire `$HOME` — you don't want to bind-mount your whole home as a workspace root.

### SSH

Omit `[containers.ssh]` to disable. When present:

- `ssh.port` (required)
- exactly one of:
  - `ssh.authorized_keys_file` — must exist and be non-empty at apply time
  - `ssh.authorized_keys` — inline, non-empty

SSH binds to `127.0.0.1:<port>` only.

Key file contents are copied into the container at create time; editing the host file afterwards does **not** propagate. To refresh keys:

```sh
devctk rm <name> && devctk apply
```

## Notes

- `devctk` is intentionally conservative about Podman-specific features. Most raw Podman knobs should go into `extra_create_args` (`--mount`, `--device`, `--shm-size`, …).
- If `extra_create_args` conflicts with a devctk-managed option, Podman is the one that errors at create time — devctk does not pre-validate.
