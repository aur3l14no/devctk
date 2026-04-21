"""What a feature contributes to a container.

Mount (bind-mount specification) + Provision (monoid combining mounts,
PATH entries, and profile snippets across features) + the workspace
provisioner (tightly coupled to the Workspace sum type).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from devctk.spec import Workspace, WorkspaceOff, WorkspaceOn


@dataclass(frozen=True, slots=True)
class Mount:
    host: Path
    target: str
    mode: Literal["ro", "rw"]

    def as_arg(self) -> str:
        return f"type=bind,src={self.host},target={self.target},{self.mode}"


@dataclass(frozen=True, slots=True)
class Provision:
    mounts: tuple[Mount, ...] = ()
    path_head: tuple[str, ...] = ()  # prepended to PATH (wins over std)
    path_tail: tuple[str, ...] = ()  # appended after std paths (fallback)
    profile_snippet: str = ""

    @staticmethod
    def combine(items: Iterable[Provision]) -> Provision:
        mounts: list[Mount] = []
        head: list[str] = []
        tail: list[str] = []
        snips: list[str] = []
        for p in items:
            mounts.extend(p.mounts)
            head.extend(p.path_head)
            tail.extend(p.path_tail)
            if p.profile_snippet:
                snips.append(p.profile_snippet)
        return Provision(tuple(mounts), tuple(head), tuple(tail), "\n".join(snips))


def provision_workspace(ws: Workspace, container_home: str) -> Provision:
    if isinstance(ws, WorkspaceOff):
        return Provision()
    ws.path.mkdir(parents=True, exist_ok=True)
    target = str(ws.path) if ws.mirror else f"{container_home}/workspace"
    return Provision(mounts=(Mount(ws.path, target, "rw"),))
