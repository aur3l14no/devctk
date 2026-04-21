"""Nix store and profile forwarding into containers."""

from __future__ import annotations

import sys
from pathlib import Path

from devctk.provision import Mount, Provision


_NIX_STORE = Path("/nix/store")
_SYS_CURRENT = Path("/run/current-system")
_SYS_SW_BIN = Path("/run/current-system/sw/bin")


def provision_nix(user: str) -> Provision:
    """Mount /nix/store + per-user profile + current-system, read-only.

    Uses unresolved symlink-tree paths so they survive nixos-rebuild + GC.
    """
    mounts: list[Mount] = []
    if _NIX_STORE.is_dir():
        mounts.append(Mount(_NIX_STORE, str(_NIX_STORE), "ro"))

    profile = Path(f"/etc/profiles/per-user/{user}")
    if profile.exists():
        mounts.append(Mount(profile, str(profile), "ro"))

    if _SYS_CURRENT.exists():
        mounts.append(Mount(_SYS_CURRENT, str(_SYS_CURRENT), "ro"))

    if not mounts:
        print("warning: nix enabled but no Nix installation found", file=sys.stderr)
        return Provision()

    path_entries: list[str] = []
    profile_bin = Path(f"/etc/profiles/per-user/{user}/bin")
    if profile_bin.exists():
        path_entries.append(str(profile_bin))
    if _SYS_SW_BIN.exists():
        path_entries.append(str(_SYS_SW_BIN))

    return Provision(mounts=tuple(mounts), path_entries=tuple(path_entries))
