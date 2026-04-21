"""Typed container spec + TOML parser.

Sum types (Workspace/SSH/AuthorizedKeys) make invalid states unrepresentable.
Each type validates its own fields; `_lift_*` bridges flat TOML into the
discriminated-union form. Hashing is a pure projection of the pydantic dump.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
AGENT_CHOICES: frozenset[str] = frozenset({"claude", "codex"})


class SpecError(ValueError):
    """Invalid devctk config."""


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _abs(v: Any, label: str) -> Path:
    if not isinstance(v, (str, Path)):
        raise ValueError(f"{label} must be a path")
    p = (v if isinstance(v, Path) else Path(v)).expanduser()
    if not p.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return p.resolve()


# --- Workspace ---------------------------------------------------------

class WorkspaceOff(_M):
    kind: Literal["off"] = "off"


class WorkspaceOn(_M):
    kind: Literal["on"] = "on"
    path: Path
    mirror: bool = False

    @field_validator("path")
    @classmethod
    def _abs_path(cls, v: Path) -> Path:
        return _abs(v, "workspace.path")

    @model_validator(mode="after")
    def _no_home_mirror(self) -> WorkspaceOn:
        if self.mirror and self.path == Path.home():
            raise ValueError("refusing to mirror the entire home directory")
        return self


Workspace = Annotated[WorkspaceOff | WorkspaceOn, Field(discriminator="kind")]


# --- SSH ---------------------------------------------------------------

class AuthKeysFile(_M):
    source: Literal["file"] = "file"
    path: Path

    @field_validator("path")
    @classmethod
    def _check(cls, v: Path) -> Path:
        p = _abs(v, "ssh.authorized_keys_file")
        if not p.is_file():
            raise ValueError(f"ssh.authorized_keys_file not found: {p}")
        if p.stat().st_size == 0:
            raise ValueError(f"ssh.authorized_keys_file is empty: {p}")
        return p


class AuthKeysInline(_M):
    source: Literal["inline"] = "inline"
    text: str

    @field_validator("text")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ssh.authorized_keys must not be empty")
        return v


AuthorizedKeys = Annotated[AuthKeysFile | AuthKeysInline, Field(discriminator="source")]


class SSHOff(_M):
    kind: Literal["off"] = "off"


class SSHOn(_M):
    kind: Literal["on"] = "on"
    port: int
    keys: AuthorizedKeys

    @field_validator("port")
    @classmethod
    def _in_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"ssh.port out of range: {v}")
        return v


SSH = Annotated[SSHOff | SSHOn, Field(discriminator="kind")]


# --- Container ---------------------------------------------------------

class ContainerSpec(_M):
    name: str
    image: str
    systemd: bool = False
    nix: bool = False
    mise: bool = False
    agents: tuple[str, ...] = ()
    extra_create_args: tuple[str, ...] = ()
    workspace: Workspace = Field(default_factory=WorkspaceOff)
    ssh: SSH = Field(default_factory=SSHOff)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError(f"invalid container name: {v!r}")
        return v

    @field_validator("image")
    @classmethod
    def _nonempty_image(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("image must not be empty")
        return v

    @field_validator("agents")
    @classmethod
    def _valid_agents(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for a in v:
            if a not in AGENT_CHOICES:
                raise ValueError(f"unsupported agent: {a}")
        return tuple(dict.fromkeys(v))

    @field_validator("workspace", mode="before")
    @classmethod
    def _lift_workspace(cls, v: Any) -> Any:
        if isinstance(v, dict) and "kind" in v:
            return v
        if v in (None, {}):
            return {"kind": "off"}
        if not isinstance(v, dict):
            raise ValueError("workspace must be a table")
        return {"kind": "on", **v}

    @field_validator("ssh", mode="before")
    @classmethod
    def _lift_ssh(cls, v: Any) -> Any:
        if isinstance(v, dict) and "kind" in v:
            return v
        if v in (None, {}):
            return {"kind": "off"}
        if not isinstance(v, dict):
            raise ValueError("ssh must be a table")
        file = v.get("authorized_keys_file")
        inline = v.get("authorized_keys")
        if (file is None) == (inline is None):
            raise ValueError(
                "ssh requires exactly one of authorized_keys_file or authorized_keys"
            )
        keys = (
            {"source": "file", "path": file} if file is not None
            else {"source": "inline", "text": inline}
        )
        return {"kind": "on", "port": v.get("port"), "keys": keys}


class AppConfig(_M):
    containers: tuple[ContainerSpec, ...]

    @model_validator(mode="after")
    def _unique_names(self) -> AppConfig:
        names = [c.name for c in self.containers]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate container names: {', '.join(dupes)}")
        return self

    def by_name(self) -> dict[str, ContainerSpec]:
        return {c.name: c for c in self.containers}


# --- Parser ------------------------------------------------------------

def parse_config(data: Any) -> AppConfig:
    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        raise SpecError(_fmt_err(e)) from e


def load_config(path: Path) -> AppConfig:
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError as e:
        raise SpecError(f"config not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise SpecError(f"invalid TOML in {path}: {e}") from e
    return parse_config(data)


def _fmt_err(exc: ValidationError) -> str:
    e = exc.errors()[0]
    msg = e.get("msg", "invalid config")
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, ") :]
    loc = ".".join(str(p) for p in e.get("loc", ()))
    return f"{loc}: {msg}" if loc else msg


# --- Hashing + diff ----------------------------------------------------

class Change(NamedTuple):
    path: str
    before: Any
    after: Any


def full_fingerprint(spec: ContainerSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")


def runtime_fingerprint(spec: ContainerSpec) -> dict[str, Any]:
    """Subset whose changes force a container rebuild.

    Excludes `systemd`, which only toggles the host-side autostart unit
    and has no effect on the running container.
    """
    return spec.model_dump(mode="json", exclude={"systemd"})


def full_hash(spec: ContainerSpec) -> str:
    return _hash(full_fingerprint(spec))


def runtime_hash(spec: ContainerSpec) -> str:
    return _hash(runtime_fingerprint(spec))


def _hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def diff_fingerprints(
    prev: dict[str, Any] | None, curr: dict[str, Any]
) -> tuple[Change, ...]:
    if prev is None:
        return (Change("container", None, curr),)
    out: list[Change] = []
    _collect(prev, curr, "", out)
    return tuple(out)


def _collect(prev: Any, curr: Any, path: str, out: list[Change]) -> None:
    if type(prev) is not type(curr):
        out.append(Change(path or "value", prev, curr))
        return
    if isinstance(prev, dict):
        for k in sorted(set(prev) | set(curr)):
            child = f"{path}.{k}" if path else k
            if k not in prev:
                out.append(Change(child, None, curr[k]))
            elif k not in curr:
                out.append(Change(child, prev[k], None))
            else:
                _collect(prev[k], curr[k], child, out)
        return
    if prev != curr:
        out.append(Change(path or "value", prev, curr))


# --- Default config ----------------------------------------------------

def default_config_text() -> str:
    user = os.environ.get("USER") or Path.home().name
    project = Path.cwd().resolve()
    return f"""[[containers]]
name = "{user}-dev"
image = "docker.io/library/ubuntu:24.04"

[containers.workspace]
path = "{project}"
mirror = true
"""
