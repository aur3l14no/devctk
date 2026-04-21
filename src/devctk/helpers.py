"""Helpers for bootstrap rendering and podman command construction."""

from __future__ import annotations

import os
import re
import shlex
from importlib.resources import files


def _render(name: str, **vars: str) -> str:
    content = (files("devctk") / "templates" / name).read_text()
    for key, value in vars.items():
        content = content.replace(f"@@{key}@@", value)
    if "@@" in content:
        remaining = re.findall(r"@@\w+@@", content)
        raise ValueError(f"unsubstituted placeholders in {name}: {remaining}")
    return content


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
    podman_dir = os.path.dirname(podman)
    ak_path = f"/etc/ssh/authorized_keys/{user}"
    sudoers = f"/etc/sudoers.d/90-{user}"

    sections = [
        _render("bootstrap_pkg.sh"),
        _render(
            "bootstrap_user.sh",
            USER=shlex.quote(user),
            UID=str(uid),
            GID=str(gid),
            HOME=shlex.quote(home),
            SUDOERS=shlex.quote(sudoers),
        ),
    ]
    if nix_profile:
        sections.append(_render("bootstrap_nix.sh", NIX_PROFILE=nix_profile))
    if ssh:
        sections.append(_render("bootstrap_ssh.sh", USER=user))
    sections.append("# Signal readiness\ntouch /run/devctk-ready\n")

    heredoc_body = "\n".join(section.rstrip() for section in sections)

    copy_keys = ""
    if ssh:
        if authorized_keys_file is not None:
            copy_keys = (
                f'\n"$podman" exec --user root -i "$name" /bin/sh -c {shlex.quote("cat >" + ak_path)}'
                f' < {shlex.quote(authorized_keys_file)}\n'
                f'exec_root {shlex.quote(f"chmod 644 {ak_path} && chown root:root {ak_path}")}\n'
            )
        elif authorized_keys_text is not None:
            copy_keys = (
                f"\nprintf '%s\\n' {shlex.quote(authorized_keys_text)} | "
                f'"$podman" exec --user root -i "$name" /bin/sh -c {shlex.quote("cat >" + ak_path)}\n'
                f'exec_root {shlex.quote(f"chmod 644 {ak_path} && chown root:root {ak_path}")}\n'
            )

    return f"""\
#!/bin/sh
set -eu

export PATH={shlex.quote(podman_dir)}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${{PATH:-}}

podman={shlex.quote(podman)}
name={shlex.quote(name)}

exec_root() {{
    "$podman" exec --user root "$name" /bin/sh -c "$@"
}}

n=0
while ! "$podman" exec "$name" true >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -ge 60 ]; then
        echo "container $name not ready after 60s" >&2
        exit 1
    fi
    sleep 1
done

"$podman" exec --user root -i "$name" /bin/sh <<'__DEVCTK_BOOTSTRAP__'
set -eu

{heredoc_body}
__DEVCTK_BOOTSTRAP__
{copy_keys}
echo "bootstrap complete for $name"
"""


def build_create_cmd(
    podman: str,
    name: str,
    image: str,
    mounts: list[str],
    extra: list[str],
    env: list[str] | None = None,
    ssh_port: int | None = None,
) -> list[str]:
    cmd = [
        podman,
        "create",
        "--name",
        name,
        "--userns",
        "keep-id",
        "--init",
        "--stop-timeout",
        "5",
    ]
    for value in env or []:
        cmd.extend(["-e", value])
    for mount in mounts:
        cmd.extend(["--mount", mount])
    if ssh_port is not None:
        cmd.extend(["--publish", f"127.0.0.1:{ssh_port}:22"])
    cmd.extend(extra)
    cmd.extend([image, "sleep", "infinity"])
    return cmd
