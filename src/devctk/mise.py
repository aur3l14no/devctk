"""Mise tool installs forwarding into containers."""

from __future__ import annotations

from pathlib import Path

CONTAINER_MISE_DIR = "/opt/mise"

# Shell snippet for /etc/profile.d — discovers mise tools at login time
# so PATH stays in sync with whatever is on the host mount.
# Skips symlinks (latest, major aliases) to avoid duplicate entries.
MISE_PROFILE_SNIPPET = """\
for d in /opt/mise/*/*; do
  [ -d "$d" ] && [ ! -L "$d" ] || continue
  if [ -d "$d/bin" ]; then PATH="$d/bin:$PATH"; else PATH="$d:$PATH"; fi
done
export PATH
"""


def _host_mise_dir() -> Path:
    return Path.home() / ".local" / "share" / "mise" / "installs"


def mise_mounts() -> list[tuple[str, str, str]]:
    """Return (host_path, container_path, mode) tuples for mise installs (read-only)."""
    md = _host_mise_dir()
    if not md.is_dir():
        return []
    return [(str(md), CONTAINER_MISE_DIR, "ro")]
