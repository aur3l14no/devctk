from __future__ import annotations

import pathlib
import shutil
import subprocess


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"missing required binary: {name}")
    return path


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def write_text(path: pathlib.Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode is not None:
        path.chmod(mode)


def unlink_if_exists(path: pathlib.Path) -> None:
    if path.exists():
        path.unlink()
