"""Generate shell scripts: bootstrap (container entrypoint), container helper, sshd helper."""

from __future__ import annotations

import shlex


def _sq(s: str) -> str:
    return shlex.quote(s)


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


# ---------------------------------------------------------------------------
# Bootstrap — runs as container entrypoint, execs sleep infinity at the end
# ---------------------------------------------------------------------------

def render_bootstrap(
    user: str,
    uid: int,
    gid: int,
    home: str,
    ssh: bool,
    nix_profile: str,
    authorized_keys_file: str | None,
    authorized_keys_text: str | None,
) -> str:
    """Render the bootstrap script that runs as the container's entrypoint.

    This script is idempotent and runs on every container start.  It sets up
    the user, sudo, optionally installs sshd, writes nix profile.d, copies
    authorized keys, then execs ``sleep infinity``.
    """
    ak_path = f"/etc/ssh/authorized_keys/{user}"
    sudoers = f"/etc/sudoers.d/90-{user}"

    # Build the copy-keys snippet (only used if ssh=True).
    copy_keys = ""
    if ssh:
        if authorized_keys_file is not None:
            copy_keys = f"cat {_sq(authorized_keys_file)} >{_sq(ak_path)}"
        elif authorized_keys_text is not None:
            copy_keys = f"printf '%s\\n' {_sq(authorized_keys_text)} >{_sq(ak_path)}"

    # Build the nix profile.d block.
    nix_block = ""
    if nix_profile:
        # Escape the profile content for embedding in a heredoc.
        nix_block = f"""\
# Nix PATH for interactive shells
mkdir -p /etc/profile.d
cat >/etc/profile.d/99-devctk-nix.sh <<'__DEVCTK_NIX__'
{nix_profile}__DEVCTK_NIX__
"""

    # SSH setup block.
    ssh_block = ""
    if ssh:
        ssh_block = f"""\
# --- SSH ---
need_sshd=false
test -x /usr/sbin/sshd || need_sshd=true

if $need_sshd; then
    case "$pm" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq && apt-get install -y --no-install-recommends openssh-server
            ;;
        apk)
            apk add --no-cache openssh
            ;;
        *)
            echo "sshd missing and no supported package manager" >&2
            exit 1
            ;;
    esac
fi

mkdir -p /run/sshd /etc/ssh/authorized_keys /etc/ssh/sshd_config.d
chmod 755 /etc/ssh/authorized_keys
ssh-keygen -A 2>/dev/null

# Authorized keys
{copy_keys}
chmod 644 {_sq(ak_path)}
chown root:root {_sq(ak_path)}

# sshd config
cat >/etc/ssh/sshd_config.d/10-rootless-dev.conf <<'__DEVCTK_SSHD__'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
AllowUsers {user}
PidFile /run/sshd.pid
__DEVCTK_SSHD__

/usr/sbin/sshd -t
"""

    return f"""\
#!/bin/sh
set -eu

# --- Detect package manager ---
pm=none
command -v apt-get >/dev/null 2>&1 && pm=apt
if [ "$pm" = "none" ]; then
    command -v apk >/dev/null 2>&1 && pm=apk
fi

# --- Install sudo if missing ---
if ! command -v sudo >/dev/null 2>&1; then
    case "$pm" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq && apt-get install -y --no-install-recommends sudo
            ;;
        apk)
            apk add --no-cache sudo shadow
            ;;
        *)
            echo "sudo missing and no supported package manager" >&2
            exit 1
            ;;
    esac
fi

# Install bash if missing (for user shell)
if ! command -v bash >/dev/null 2>&1; then
    case "$pm" in
        apk) apk add --no-cache bash ;;
        *) : ;;
    esac
fi

# --- User setup ---
container_user={_sq(user)}
container_uid={uid}
container_gid={gid}
container_home={_sq(home)}

shell=/bin/bash
command -v bash >/dev/null 2>&1 || shell=/bin/sh

# Handle GID
existing_group=$(getent group "$container_gid" 2>/dev/null | cut -d: -f1 || true)
if [ -n "$existing_group" ]; then
    group_name="$existing_group"
elif getent group "$container_user" >/dev/null 2>&1; then
    groupmod -g "$container_gid" "$(getent group "$container_user" | cut -d: -f1)"
    group_name="$container_user"
else
    groupadd -g "$container_gid" "$container_user"
    group_name="$container_user"
fi

# Handle UID
uid_owner=$(getent passwd "$container_uid" 2>/dev/null | cut -d: -f1 || true)
if [ -n "$uid_owner" ] && [ "$uid_owner" != "$container_user" ]; then
    usermod -l "$container_user" -d "$container_home" -m -g "$container_gid" -s "$shell" "$uid_owner"
elif id -u "$container_user" >/dev/null 2>&1; then
    usermod -u "$container_uid" -d "$container_home" -g "$container_gid" -s "$shell" "$container_user"
else
    useradd -M -d "$container_home" -s "$shell" -u "$container_uid" -g "$container_gid" "$container_user"
fi

mkdir -p "$container_home" /etc/sudoers.d
chown "$container_uid:$container_gid" "$container_home" 2>/dev/null || true

# Passwordless sudo
printf '%s ALL=(ALL) NOPASSWD:ALL\\n' "$container_user" >{sudoers}
chmod 440 {sudoers}

{nix_block}{ssh_block}# Ready
touch /run/devctk-ready
exec sleep infinity
"""


# ---------------------------------------------------------------------------
# Container helper — create / start / stop
# ---------------------------------------------------------------------------

def render_container_helper(
    podman: str,
    name: str,
    image: str,
    mounts: list[str],
    devices: list[str],
    extra: list[str],
    ssh_port: int | None = None,
) -> str:
    """Render the container helper script (create/start/stop).

    The container's entrypoint is /devctk-bootstrap.sh (bind-mounted from
    the host state dir).  The bootstrap script execs ``sleep infinity``
    after setup.
    """
    create_cmd = [
        podman, "create",
        "--name", name,
        "--userns", "keep-id",
        "--init",
        "--stop-timeout", "5",
    ]
    for d in devices:
        create_cmd.extend(["--device", d])
    for m in mounts:
        create_cmd.extend(["--mount", m])
    if ssh_port is not None:
        create_cmd.extend(["--publish", f"127.0.0.1:{ssh_port}:22"])
    create_cmd.extend(extra)
    create_cmd.extend([image, "/devctk-bootstrap.sh"])

    return f"""\
#!/bin/sh
set -eu

podman={_sq(podman)}
name={_sq(name)}

create() {{
    if "$podman" container exists "$name"; then exit 0; fi
    exec {_shell_join(create_cmd)}
}}

start() {{
    running=$("$podman" inspect -f '{{{{.State.Running}}}}' "$name" 2>/dev/null || printf 'false\\n')
    if [ "$running" = "true" ]; then exec "$podman" attach "$name"; fi
    exec "$podman" start --attach "$name"
}}

stop() {{
    exec "$podman" stop --ignore -t 10 "$name"
}}

case "${{1:-}}" in
    create) create ;; start) start ;; stop) stop ;;
    *) echo "usage: $0 {{create|start|stop}}" >&2; exit 2 ;;
esac
"""


# ---------------------------------------------------------------------------
# SSHD helper — start / stop only (bootstrap is handled by container entrypoint)
# ---------------------------------------------------------------------------

def render_sshd_helper(podman: str, name: str) -> str:
    """Render the sshd helper script (start/stop).

    Waits for the bootstrap to signal readiness via /run/devctk-ready
    before starting sshd.
    """
    return f"""\
#!/bin/sh
set -eu

podman={_sq(podman)}
name={_sq(name)}

stop_sshd() {{
    "$podman" exec --user root "$name" /bin/sh -c \\
        'if [ -f /run/sshd.pid ]; then kill "$(cat /run/sshd.pid)" 2>/dev/null; fi' || true
}}

start() {{
    # Wait for bootstrap to finish
    n=0
    while ! "$podman" exec "$name" test -f /run/devctk-ready 2>/dev/null; do
        n=$((n + 1))
        if [ "$n" -ge 120 ]; then
            echo "container $name bootstrap not ready after 120s" >&2
            exit 1
        fi
        sleep 1
    done

    stop_sshd
    exec "$podman" exec --user root "$name" /usr/sbin/sshd -D -e -o PidFile=/run/sshd.pid
}}

stop() {{
    stop_sshd
}}

case "${{1:-}}" in
    start) start ;; stop) stop ;;
    *) echo "usage: $0 {{start|stop}}" >&2; exit 2 ;;
esac
"""
