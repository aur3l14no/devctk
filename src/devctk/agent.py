"""Agent config dir mounting for Claude Code and Codex."""

from __future__ import annotations

from pathlib import Path

HOME = Path.home()

AGENTS: dict[str, dict] = {
    "claude": {
        "dirs": [HOME / ".claude"],
        "files": [HOME / ".claude.json"],
    },
    "codex": {
        "dirs": [HOME / ".codex"],
        "files": [],
    },
}


SHARED_DIR = HOME / ".agents"


def agent_mounts(agents: list[str], container_home: str) -> list[tuple[str, str, str]]:
    """Return (host_path, container_path, mode) tuples for agent config mounts.

    Directories are created on the host if missing (so bind mounts work).
    Files are skipped if they don't exist yet (agent creates them on first run).
    If any agent is requested, the shared ``~/.agents`` dir is mounted too —
    it holds cross-agent resources (skills, etc.) that individual config dirs
    symlink into.
    """
    mounts: list[tuple[str, str, str]] = []
    for name in agents:
        spec = AGENTS.get(name)
        if not spec:
            continue
        for d in spec["dirs"]:
            d.mkdir(parents=True, exist_ok=True)
            mounts.append((str(d), f"{container_home}/{d.name}", "rw"))
        for f in spec["files"]:
            if f.is_file():
                mounts.append((str(f), f"{container_home}/{f.name}", "rw"))
    if agents:
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        mounts.append((str(SHARED_DIR), f"{container_home}/{SHARED_DIR.name}", "rw"))
    return mounts
