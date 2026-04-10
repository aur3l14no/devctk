"""Generate shell scripts from templates with @@VAR@@ substitution."""

from __future__ import annotations

import os
import shlex
from importlib.resources import files


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def _render(name: str, **vars: str) -> str:
    """Read a template from devctk/templates/ and substitute @@VAR@@ placeholders."""
    content = (files("devctk") / "templates" / name).read_text()
    for key, value in vars.items():
        content = content.replace(f"@@{key}@@", value)
    if "@@" in content:
        import re
        remaining = re.findall(r"@@\w+@@", content)
        raise ValueError(f"unsubstituted placeholders in {name}: {remaining}")
    return content


# ---------------------------------------------------------------------------
# Bootstrap — host-side script, uses podman exec --user root
# ---------------------------------------------------------------------------

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
    """Compose the bootstrap script from template sections."""
    podman_dir = os.path.dirname(podman)
    ak_path = f"/etc/ssh/authorized_keys/{user}"
    sudoers = f"/etc/sudoers.d/90-{user}"

    # Assemble heredoc body from template sections
    sections = [
        _render("bootstrap_pkg.sh"),
        _render("bootstrap_user.sh",
                USER=shlex.quote(user), UID=str(uid), GID=str(gid),
                HOME=shlex.quote(home), SUDOERS=shlex.quote(sudoers)),
    ]
    if nix_profile:
        sections.append(_render("bootstrap_nix.sh", NIX_PROFILE=nix_profile))
    if ssh:
        sections.append(_render("bootstrap_ssh.sh", USER=user))
    sections.append("# Signal readiness\ntouch /run/devctk-ready\n")

    heredoc_body = "\n".join(s.rstrip() for s in sections)

    # Host-side key copy (after the heredoc)
    copy_keys = ""
    if ssh:
        if authorized_keys_file is not None:
            copy_keys = (
                f'\n# Copy authorized keys from host\n'
                f'"$podman" exec --user root -i "$name" /bin/sh -c {shlex.quote("cat >" + ak_path)}'
                f' < {shlex.quote(authorized_keys_file)}\n'
                f'exec_root {shlex.quote(f"chmod 644 {ak_path} && chown root:root {ak_path}")}\n'
            )
        elif authorized_keys_text is not None:
            copy_keys = (
                f'\n# Copy authorized keys (inline)\n'
                f'printf \'%s\\n\' {shlex.quote(authorized_keys_text)} | '
                f'"$podman" exec --user root -i "$name" /bin/sh -c {shlex.quote("cat >" + ak_path)}\n'
                f'exec_root {shlex.quote(f"chmod 644 {ak_path} && chown root:root {ak_path}")}\n'
            )

    # The outer wrapper is short enough to keep inline
    return f"""\
#!/bin/sh
set -eu

# NixOS systemd user services have a minimal PATH — add podman's dir
export PATH={shlex.quote(podman_dir)}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${{PATH:-}}

podman={shlex.quote(podman)}
name={shlex.quote(name)}

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

# Run setup inside the container as root
"$podman" exec --user root -i "$name" /bin/sh <<'__DEVCTK_BOOTSTRAP__'
set -eu

{heredoc_body}
__DEVCTK_BOOTSTRAP__
{copy_keys}
echo "bootstrap complete for $name"
"""


# ---------------------------------------------------------------------------
# Container helper + SSHD helper — rendered from templates
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
    return _render("container_helper.sh",
                   PODMAN=shlex.quote(podman), NAME=shlex.quote(name),
                   CREATE_CMD=_shell_join(create_cmd))


def render_sshd_helper(podman: str, name: str) -> str:
    return _render("sshd_helper.sh", PODMAN=shlex.quote(podman), NAME=shlex.quote(name))
