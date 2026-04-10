"""Mise tool installs forwarding into containers."""

from __future__ import annotations

from pathlib import Path


def mise_dir() -> Path:
    return Path.home() / ".local" / "share" / "mise" / "installs"


def mise_mounts() -> list[tuple[str, str, str]]:
    """Return (host_path, container_path, mode) tuples for mise installs (read-only)."""
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
