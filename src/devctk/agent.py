"""Agent config dir mounting for Claude Code and Codex."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devctk.provision import Mount, Provision


_HOME = Path.home()
_SHARED_DIR = _HOME / ".agents"


@dataclass(frozen=True, slots=True)
class _AgentSpec:
    dirs: tuple[Path, ...]
    files: tuple[tuple[Path, str], ...]  # (path, initial content if missing)


# Dirs are mkdir'd on host. Files are created with a minimal valid payload
# if missing — a pure bind-mount of a non-existent path would leave the
# agent writing into the container's ephemeral layer instead of the host,
# losing state on recreate.
_AGENTS: dict[str, _AgentSpec] = {
    "claude": _AgentSpec(
        dirs=(_HOME / ".claude",),
        files=((_HOME / ".claude.json", "{}\n"),),
    ),
    "codex": _AgentSpec(
        dirs=(_HOME / ".codex",),
        files=(),
    ),
}


def provision_agents(agents: tuple[str, ...], container_home: str) -> Provision:
    if not agents:
        return Provision()
    mounts: list[Mount] = []
    for name in agents:
        spec = _AGENTS.get(name)
        if spec is None:
            continue
        for d in spec.dirs:
            d.mkdir(parents=True, exist_ok=True)
            mounts.append(Mount(d, f"{container_home}/{d.name}", "rw"))
        for path, initial in spec.files:
            if not path.exists():
                path.write_text(initial)
            mounts.append(Mount(path, f"{container_home}/{path.name}", "rw"))
    _SHARED_DIR.mkdir(parents=True, exist_ok=True)
    mounts.append(Mount(_SHARED_DIR, f"{container_home}/{_SHARED_DIR.name}", "rw"))
    return Provision(mounts=tuple(mounts))
