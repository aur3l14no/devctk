"""Pure planning: (desired, tracked, live) -> PlanStep.

No subprocess, no filesystem. Testable as a truth table.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from devctk.spec import (
    Change,
    ContainerSpec,
    SSHOn,
    diff_fingerprints,
    full_fingerprint,
    full_hash,
    runtime_hash,
)
from devctk.state import AppState, StateEntry


class LiveStatus(str, Enum):
    MISSING = "missing"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class LiveSnapshot:
    status: LiveStatus = LiveStatus.MISSING
    sshd_running: bool = False


# --- Plan step sum type --------------------------------------------------

class _Step(BaseModel):
    model_config = ConfigDict(frozen=True)


class Create(_Step):
    spec: ContainerSpec
    reason: str | None = None


class Recreate(_Step):
    spec: ContainerSpec
    changes: tuple[Change, ...] = ()
    reason: str | None = None


class Start(_Step):
    spec: ContainerSpec
    reason: str


class Update(_Step):
    spec: ContainerSpec
    changes: tuple[Change, ...]


class Destroy(_Step):
    name: str
    previous: dict[str, Any] | None = None
    reason: str = "removed from config"


class Noop(_Step):
    name: str


PlanStep = Create | Recreate | Start | Update | Destroy | Noop


def step_kind(step: PlanStep) -> str:
    return type(step).__name__.lower()


def step_name(step: PlanStep) -> str:
    if isinstance(step, (Destroy, Noop)):
        return step.name
    return step.spec.name


# --- Decision function ---------------------------------------------------

def plan_container(
    *,
    name: str,
    spec: ContainerSpec | None,
    tracked: StateEntry | None,
    live: LiveSnapshot,
    autostart_only: bool = False,
) -> PlanStep | None:
    """Decide the single-container plan step.

    Returns None when (after autostart filtering) there's nothing for us
    to care about.
    """
    if autostart_only:
        if spec is not None and not spec.systemd:
            spec = None
        if tracked is not None and not tracked.systemd:
            tracked = None

    if spec is None and tracked is None:
        return None
    if spec is None:
        assert tracked is not None
        return Destroy(name=name, previous=tracked.spec)

    if tracked is None:
        if live.status is LiveStatus.MISSING:
            return Create(spec=spec)
        return Recreate(
            spec=spec,
            changes=diff_fingerprints(None, full_fingerprint(spec)),
            reason="existing untracked container will be replaced",
        )

    current = full_fingerprint(spec)
    if runtime_hash(spec) != tracked.runtime_hash:
        return Recreate(spec=spec, changes=diff_fingerprints(tracked.spec, current))
    if live.status is LiveStatus.MISSING:
        return Create(spec=spec, reason="container is missing")
    if live.status is LiveStatus.STOPPED:
        return Start(spec=spec, reason="container is stopped")
    if isinstance(spec.ssh, SSHOn) and not live.sshd_running:
        return Start(spec=spec, reason="sshd is not running")
    if full_hash(spec) != tracked.full_hash:
        return Update(spec=spec, changes=diff_fingerprints(tracked.spec, current))
    return Noop(name=spec.name)


def plan_all(
    specs: dict[str, ContainerSpec],
    state: AppState,
    live_map: dict[str, LiveSnapshot],
    *,
    autostart_only: bool = False,
) -> tuple[PlanStep, ...]:
    names = sorted(set(specs) | set(state.containers))
    out: list[PlanStep] = []
    for name in names:
        step = plan_container(
            name=name,
            spec=specs.get(name),
            tracked=state.containers.get(name),
            live=live_map.get(name, LiveSnapshot()),
            autostart_only=autostart_only,
        )
        if step is not None:
            out.append(step)
    return tuple(out)
