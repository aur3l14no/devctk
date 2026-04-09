from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

STATE_DIR_NAME = "devctk"


def state_root() -> pathlib.Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser()
    return pathlib.Path.home() / ".local" / "state"


@dataclass(frozen=True)
class ManagedPaths:
    units_dir: pathlib.Path
    helper_dir: pathlib.Path
    metadata: pathlib.Path
    container_unit: pathlib.Path
    container_helper: pathlib.Path
    bootstrap_helper: pathlib.Path
    sshd_unit: pathlib.Path
    sshd_helper: pathlib.Path


def managed_paths(name: str) -> ManagedPaths:
    home = pathlib.Path.home()
    units = home / ".config" / "systemd" / "user"
    helpers = state_root() / STATE_DIR_NAME
    return ManagedPaths(
        units_dir=units,
        helper_dir=helpers,
        metadata=helpers / f"{name}.json",
        container_unit=units / f"{name}.service",
        container_helper=helpers / f"{name}-container.sh",
        bootstrap_helper=helpers / f"{name}-bootstrap.sh",
        sshd_unit=units / f"{name}-sshd.service",
        sshd_helper=helpers / f"{name}-sshd.sh",
    )
