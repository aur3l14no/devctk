"""Agent config dir mounting for Claude Code and Codex."""

from __future__ import annotations

from pathlib import Path

from devctk.provision import Mount, Provision


_HOME = Path.home()
_SHARED_DIR = _HOME / ".agents"

# For each supported agent: dirs are mkdir'd on host then bind-mounted;
# files are mounted only if already present (agent creates them on first run).
_AGENTS: dict[str, dict[str, list[Path]]] = {
    "claude": {
        "dirs": [_HOME / ".claude"],
        "files": [_HOME / ".claude.json"],
    },
    "codex": {
        "dirs": [_HOME / ".codex"],
        "files": [],
    },
}


def provision_agents(agents: tuple[str, ...], container_home: str) -> Provision:
    if not agents:
        return Provision()
    mounts: list[Mount] = []
    for name in agents:
        spec = _AGENTS.get(name)
        if not spec:
            continue
        for d in spec["dirs"]:
            d.mkdir(parents=True, exist_ok=True)
            mounts.append(Mount(d, f"{container_home}/{d.name}", "rw"))
        for f in spec["files"]:
            if f.is_file():
                mounts.append(Mount(f, f"{container_home}/{f.name}", "rw"))
    _SHARED_DIR.mkdir(parents=True, exist_ok=True)
    mounts.append(Mount(_SHARED_DIR, f"{container_home}/{_SHARED_DIR.name}", "rw"))
    return Provision(mounts=tuple(mounts))
