from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

CONFIG_DIR_NAME = "devctk"
STATE_DIR_NAME = "devctk"


def config_root() -> pathlib.Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser()
    return pathlib.Path.home() / ".config"


def state_root() -> pathlib.Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser()
    return pathlib.Path.home() / ".local" / "state"


@dataclass(frozen=True)
class ManagedPaths:
    config_dir: pathlib.Path
    config_file: pathlib.Path
    units_dir: pathlib.Path
    service_unit: pathlib.Path
    service_name: str
    state_dir: pathlib.Path
    runtime_state: pathlib.Path


def managed_paths() -> ManagedPaths:
    config_dir = config_root() / CONFIG_DIR_NAME
    state_dir = state_root() / STATE_DIR_NAME
    units_dir = config_root() / "systemd" / "user"
    return ManagedPaths(
        config_dir=config_dir,
        config_file=config_dir / "config.toml",
        units_dir=units_dir,
        service_unit=units_dir / "devctk.service",
        service_name="devctk.service",
        state_dir=state_dir,
        runtime_state=state_dir / "state.json",
    )
