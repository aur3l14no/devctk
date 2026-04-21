"""Runtime state: tracked containers + last-applied fingerprints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StateError(RuntimeError):
    pass


class StateEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: dict[str, Any]          # full fingerprint at last-apply
    full_hash: str
    runtime_hash: str
    systemd: bool
    generation: int
    container_id: str
    last_applied_at: str


class AppState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    containers: dict[str, StateEntry] = Field(default_factory=dict)


def empty_state() -> AppState:
    return AppState()


def read_state(path: Path) -> AppState:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise StateError(
            f"{path} is corrupt: {exc}. Remove it to reset tracked state."
        ) from exc
    try:
        return AppState.model_validate(data)
    except ValidationError as exc:
        raise StateError(
            f"{path} is incompatible with this devctk version: {exc.errors()[0].get('msg', exc)}. "
            f"Remove it to reset tracked state."
        ) from exc


def write_state(path: Path, state: AppState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    tmp.replace(path)


def with_entry(state: AppState, name: str, entry: StateEntry) -> AppState:
    return state.model_copy(update={"containers": {**state.containers, name: entry}})


def without_entry(state: AppState, name: str) -> AppState:
    return state.model_copy(
        update={"containers": {k: v for k, v in state.containers.items() if k != name}}
    )
