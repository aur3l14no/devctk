"""Mise tool installs forwarding into containers."""

from __future__ import annotations

from pathlib import Path

from devctk.provision import Mount, Provision

_CONTAINER_MISE_DIR = "/opt/mise"

# /etc/profile.d snippet — discovers mise tools at login time so PATH
# stays in sync with whatever is on the host mount. Skips symlinks
# (latest, major aliases) to avoid duplicate entries.
_MISE_PROFILE_SNIPPET = """\
for d in /opt/mise/*/*; do
  [ -d "$d" ] && [ ! -L "$d" ] || continue
  if [ -d "$d/bin" ]; then PATH="$d/bin:$PATH"; else PATH="$d:$PATH"; fi
done
export PATH
"""


def provision_mise() -> Provision:
    host = Path.home() / ".local" / "share" / "mise" / "installs"
    if not host.is_dir():
        return Provision()
    return Provision(
        mounts=(Mount(host, _CONTAINER_MISE_DIR, "ro"),),
        profile_snippet=_MISE_PROFILE_SNIPPET,
    )
