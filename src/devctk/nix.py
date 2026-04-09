"""Nix integration: compute mounts and PATH for NixOS hosts."""

from __future__ import annotations

import os
from pathlib import Path


def nix_mounts(host_user: str) -> list[tuple[str, str, str]]:
    """Return (host_path, container_path, mode) tuples for nix mounts.

    Uses unresolved symlink-tree paths so they survive nixos-rebuild + GC.
    """
    mounts: list[tuple[str, str, str]] = []

    nix_store = Path("/nix/store")
    if nix_store.is_dir():
        mounts.append((str(nix_store), str(nix_store), "ro"))

    profile = Path(f"/etc/profiles/per-user/{host_user}")
    if profile.exists():
        mounts.append((str(profile), str(profile), "ro"))

    sys_sw = Path("/run/current-system")
    if sys_sw.exists():
        mounts.append((str(sys_sw), str(sys_sw), "ro"))

    return mounts


def nix_path_entries(host_user: str) -> list[str]:
    """Return PATH entries for nix binaries (unresolved symlink paths)."""
    entries: list[str] = []

    profile_bin = Path(f"/etc/profiles/per-user/{host_user}/bin")
    if profile_bin.exists():
        entries.append(str(profile_bin))

    sys_bin = Path("/run/current-system/sw/bin")
    if sys_bin.exists():
        entries.append(str(sys_bin))

    return entries


def nix_profile_script(host_user: str, include_mise: bool = False) -> str:
    """Content for /etc/profile.d/99-devctk-nix.sh (sourced by SSH login shells)."""
    entries = nix_path_entries(host_user)
    if include_mise:
        entries.extend(mise_path_entries())
    if not entries:
        return ""
    path_prepend = ":".join(entries)
    return f'export PATH="{path_prepend}:$PATH"\n'


# ---------------------------------------------------------------------------
# Mise tool forwarding
# ---------------------------------------------------------------------------

def mise_dir() -> Path:
    return Path.home() / ".local" / "share" / "mise" / "installs"


def mise_mounts() -> list[tuple[str, str, str]]:
    """Return mounts for mise tool installs (read-only)."""
    md = mise_dir()
    if not md.is_dir():
        return []
    return [(str(md), str(md), "ro")]


def mise_path_entries() -> list[str]:
    """Return PATH entries for mise-installed tools (unresolved symlink paths)."""
    md = mise_dir()
    if not md.is_dir():
        return []
    entries: list[str] = []
    for tool in sorted(md.iterdir()):
        latest = tool / "latest"
        if not latest.exists():
            continue
        bindir = latest / "bin"
        entries.append(str(bindir if bindir.is_dir() else latest))
    return entries
