"""Generate the container and sshd helper shell scripts."""

from __future__ import annotations

import pathlib
import shlex


def _sq(s: str) -> str:
    return shlex.quote(s)


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def render_container_helper(
    podman: str,
    name: str,
    image: str,
    port: int,
    mounts: list[str],
    devices: list[str],
    extra: list[str],
) -> str:
    create_cmd = [podman, "create", "--name", name, "--userns", "keep-id", "--init", "--stop-timeout", "5"]
    for d in devices:
        create_cmd.extend(["--device", d])
    for m in mounts:
        create_cmd.extend(["--mount", m])
    create_cmd.extend(["--publish", f"127.0.0.1:{port}:22"])
    create_cmd.extend(extra)
    create_cmd.extend([image, "sleep", "infinity"])

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


def render_sshd_helper(
    podman: str,
    name: str,
    container_user: str,
    uid: int,
    gid: int,
    container_home: str,
    authorized_keys_file: pathlib.Path | None,
    authorized_keys_text: str | None,
) -> str:
    ak_path = f"/etc/ssh/authorized_keys/{container_user}"
    sudoers = f"/etc/sudoers.d/90-{container_user}"

    # Build the copy-keys command.
    # Use shell builtins only (no cat/cp) — systemd user services on NixOS
    # have a minimal PATH that excludes coreutils.
    if authorized_keys_file is not None:
        copy_keys = (
            f'"$podman" exec --user root -i "$name" /bin/sh -c \'cat >{ak_path}\''
            f' < {_sq(str(authorized_keys_file))}'
        )
    else:
        copy_keys = (
            f'printf \'%s\\n\' {_sq(authorized_keys_text or "")} | '
            f'"$podman" exec --user root -i "$name" /bin/sh -c \'cat >{ak_path}\''
        )

    # The bootstrap script runs entirely inside the container via heredoc.
    # All variables are hardcoded literals — no host-side expansion.
    return f"""\
#!/bin/sh
set -eu
# pipefail: catch failures in pipe left-hand side (e.g. missing binary)
( set -o pipefail 2>/dev/null ) && set -o pipefail

podman={_sq(podman)}
name={_sq(name)}

exec_root() {{
    "$podman" exec --user root "$name" /bin/sh -lc "$@"
}}

stop_sshd() {{
    exec_root 'if [ -f /run/sshd.pid ]; then kill "$(cat /run/sshd.pid)"; fi' >/dev/null 2>&1 || true
}}

bootstrap() {{
    # Wait for container to be ready
    n=0
    while ! "$podman" exec "$name" true >/dev/null 2>&1; do
        n=$((n + 1))
        if [ "$n" -ge 30 ]; then
            echo "container $name not ready after 30s" >&2; exit 1
        fi
        sleep 1
    done

    # Check apt-get
    exec_root 'command -v apt-get >/dev/null 2>&1' >/dev/null 2>&1 || {{
        echo "apt-get is required inside $name" >&2; exit 1
    }}

    # Install packages if needed
    packages=""
    exec_root 'test -x /usr/sbin/sshd' || packages="$packages openssh-server"
    exec_root 'command -v sudo >/dev/null 2>&1' || packages="$packages sudo"
    if [ -n "$packages" ]; then
        "$podman" exec --user root "$name" /bin/sh -lc \\
            "export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y --no-install-recommends $packages"
    fi

    # Create user and configure sshd — all values are literals, no host expansion
    "$podman" exec --user root -i "$name" /bin/sh <<'BOOTSTRAP'
set -eu
container_user={container_user}
container_uid={uid}
container_gid={gid}
container_home={_sq(container_home)}

# Handle GID — reuse or create
existing_group=$(getent group "$container_gid" 2>/dev/null | cut -d: -f1 || true)
if [ -n "$existing_group" ]; then
    group_name="$existing_group"
elif getent group "$container_user" >/dev/null 2>&1; then
    # Group name exists with different GID — rename it
    groupmod -g "$container_gid" "$(getent group "$container_user" | cut -d: -f1)"
    group_name="$container_user"
else
    groupadd -g "$container_gid" "$container_user"
    group_name="$container_user"
fi

# Handle UID — reuse, rename, or create
uid_owner=$(getent passwd "$container_uid" 2>/dev/null | cut -d: -f1 || true)
if [ -n "$uid_owner" ] && [ "$uid_owner" != "$container_user" ]; then
    # UID taken by another user (e.g. 'ubuntu') — rename it
    usermod -l "$container_user" -d "$container_home" -m -g "$container_gid" -s /bin/bash "$uid_owner"
elif id -u "$container_user" >/dev/null 2>&1; then
    usermod -u "$container_uid" -d "$container_home" -g "$container_gid" -s /bin/bash "$container_user"
else
    useradd -M -d "$container_home" -s /bin/bash -u "$container_uid" -g "$container_gid" "$container_user"
fi

mkdir -p "$container_home" /run/sshd /etc/ssh/authorized_keys /etc/ssh/sshd_config.d /etc/sudoers.d
chown "$container_uid:$container_gid" "$container_home" >/dev/null 2>&1 || true

# Sudoers
printf '%s ALL=(ALL) NOPASSWD:ALL\\n' "$container_user" >{sudoers}
chmod 440 {sudoers}

# SSH authorized keys dir
chmod 755 /etc/ssh/authorized_keys
ssh-keygen -A
BOOTSTRAP

    # Copy authorized keys from host
    {copy_keys}
    exec_root 'chmod 644 {ak_path} && chown root:root {ak_path}'

    # sshd config
    "$podman" exec --user root -i "$name" /bin/sh -c 'cat >/etc/ssh/sshd_config.d/10-rootless-dev.conf' <<'SSHDCONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
AllowUsers {container_user}
PidFile /run/sshd.pid
SSHDCONF

    exec_root '/usr/sbin/sshd -t'
}}

start() {{
    stop_sshd
    exec "$podman" exec --user root "$name" /usr/sbin/sshd -D -e -o PidFile=/run/sshd.pid
}}

stop() {{
    stop_sshd
}}

case "${{1:-}}" in
    bootstrap) bootstrap ;; start) start ;; stop) stop ;;
    *) echo "usage: $0 {{bootstrap|start|stop}}" >&2; exit 2 ;;
esac
"""
