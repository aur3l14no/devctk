"""Generate shell scripts: bootstrap (host-side ExecStartPost), container helper, sshd helper."""

from __future__ import annotations

import os
import shlex


def _sq(s: str) -> str:
    return shlex.quote(s)


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


# ---------------------------------------------------------------------------
# Bootstrap — runs on the HOST as ExecStartPost, uses podman exec --user root
# ---------------------------------------------------------------------------

def _bootstrap_pkg_install(user: str) -> str:
    """Shell fragment: detect package manager, install sudo + bash if missing."""
    return f"""\
# Detect package manager
pm=none
command -v apt-get >/dev/null 2>&1 && pm=apt
if [ "$pm" = "none" ]; then
    command -v apk >/dev/null 2>&1 && pm=apk
fi

# Install sudo if missing
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

# Install bash if missing
if ! command -v bash >/dev/null 2>&1; then
    case "$pm" in
        apk) apk add --no-cache bash ;;
        *) : ;;
    esac
fi
"""


def _bootstrap_user_setup(user: str, uid: int, gid: int, home: str) -> str:
    """Shell fragment: create user matching host UID/GID, configure sudo."""
    sudoers = f"/etc/sudoers.d/90-{user}"
    return f"""\
# User setup
container_user={_sq(user)}
container_uid={uid}
container_gid={gid}
container_home={_sq(home)}

shell=$(command -v bash 2>/dev/null || echo /bin/sh)

# Ensure log files exist (shadow tools fail without them in rootless containers)
mkdir -p /var/log
touch /var/log/faillog /var/log/lastlog 2>/dev/null || true

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
printf '%s ALL=(ALL) NOPASSWD:ALL\\n' "$container_user" >{_sq(sudoers)}
chmod 440 {_sq(sudoers)}
"""


def _bootstrap_nix_profile(nix_profile: str) -> str:
    """Shell fragment: write /etc/profile.d for nix/mise PATH."""
    if not nix_profile:
        return ""
    return f"""\
# Nix/mise PATH for interactive shells
mkdir -p /etc/profile.d
cat >/etc/profile.d/99-devctk-nix.sh <<'__NIX__'
{nix_profile}__NIX__
"""


def _bootstrap_ssh_setup(user: str) -> str:
    """Shell fragment: install and configure sshd."""
    return f"""\
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

cat >/etc/ssh/sshd_config.d/10-rootless-dev.conf <<'__SSHD__'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
AllowUsers {user}
PidFile /run/sshd.pid
__SSHD__

/usr/sbin/sshd -t
"""


def _bootstrap_copy_keys(
    user: str,
    authorized_keys_file: str | None,
    authorized_keys_text: str | None,
) -> str:
    """Shell lines that run on the HOST (outside heredoc) to copy SSH keys."""
    ak_path = f"/etc/ssh/authorized_keys/{user}"
    if authorized_keys_file is not None:
        return (
            f'\n# Copy authorized keys from host\n'
            f'"$podman" exec --user root -i "$name" /bin/sh -c {_sq("cat >" + ak_path)}'
            f' < {_sq(authorized_keys_file)}\n'
            f'exec_root {_sq(f"chmod 644 {ak_path} && chown root:root {ak_path}")}\n'
        )
    if authorized_keys_text is not None:
        return (
            f'\n# Copy authorized keys (inline)\n'
            f'printf \'%s\\n\' {_sq(authorized_keys_text)} | '
            f'"$podman" exec --user root -i "$name" /bin/sh -c {_sq("cat >" + ak_path)}\n'
            f'exec_root {_sq(f"chmod 644 {ak_path} && chown root:root {ak_path}")}\n'
        )
    return ""


def render_bootstrap(
    podman: str,
    name: str,
    user: str,
    uid: int,
    gid: int,
    home: str,
    ssh: bool,
    nix_profile: str,
    authorized_keys_file: str | None,
    authorized_keys_text: str | None,
) -> str:
    """Render the bootstrap script (runs on the host via ExecStartPost).

    Uses ``podman exec --user root`` so it has root inside the container
    regardless of ``--userns keep-id``.  Idempotent.
    """
    podman_dir = os.path.dirname(podman)

    # Assemble heredoc body from sections
    heredoc_parts = [
        _bootstrap_pkg_install(user),
        _bootstrap_user_setup(user, uid, gid, home),
        _bootstrap_nix_profile(nix_profile),
    ]
    if ssh:
        heredoc_parts.append(_bootstrap_ssh_setup(user))
    heredoc_parts.append("# Signal readiness\ntouch /run/devctk-ready\n")
    heredoc_body = "\n".join(p.rstrip() for p in heredoc_parts if p)

    # Host-side key copy (runs after the heredoc)
    copy_keys = _bootstrap_copy_keys(user, authorized_keys_file, authorized_keys_text) if ssh else ""

    return f"""\
#!/bin/sh
set -eu

# NixOS systemd user services have a minimal PATH — add podman's dir
export PATH={_sq(podman_dir)}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${{PATH:-}}

podman={_sq(podman)}
name={_sq(name)}

exec_root() {{
    "$podman" exec --user root "$name" /bin/sh -c "$@"
}}

# Wait for container to be ready
n=0
while ! "$podman" exec "$name" true >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -ge 60 ]; then
        echo "container $name not ready after 60s" >&2
        exit 1
    fi
    sleep 1
done

# Run setup inside the container as root via heredoc
"$podman" exec --user root -i "$name" /bin/sh <<'__DEVCTK_BOOTSTRAP__'
set -eu

{heredoc_body}
__DEVCTK_BOOTSTRAP__
{copy_keys}
echo "bootstrap complete for $name"
"""


# ---------------------------------------------------------------------------
# Container helper — create / start / stop (entrypoint is sleep infinity)
# ---------------------------------------------------------------------------

def build_create_cmd(
    podman: str,
    name: str,
    image: str,
    mounts: list[str],
    devices: list[str],
    extra: list[str],
    env: list[str] | None = None,
    ssh_port: int | None = None,
) -> list[str]:
    """Build the podman create command list."""
    cmd = [
        podman, "create",
        "--name", name,
        "--userns", "keep-id",
        "--init",
        "--stop-timeout", "5",
    ]
    for e in env or []:
        cmd.extend(["-e", e])
    for d in devices:
        cmd.extend(["--device", d])
    for m in mounts:
        cmd.extend(["--mount", m])
    if ssh_port is not None:
        cmd.extend(["--publish", f"127.0.0.1:{ssh_port}:22"])
    cmd.extend(extra)
    cmd.extend([image, "sleep", "infinity"])
    return cmd


def render_container_helper(
    podman: str,
    name: str,
    image: str,
    mounts: list[str],
    devices: list[str],
    extra: list[str],
    env: list[str] | None = None,
    ssh_port: int | None = None,
) -> str:
    create_cmd = build_create_cmd(podman, name, image, mounts, devices, extra, env, ssh_port)

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
# SSHD helper — start / stop only
# ---------------------------------------------------------------------------

def render_sshd_helper(podman: str, name: str) -> str:
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
