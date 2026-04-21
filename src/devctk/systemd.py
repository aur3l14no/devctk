"""Render the global devctk user service."""

from __future__ import annotations

from string import Template

SERVICE_TEMPLATE = """\
[Unit]
Description=devctk autostart reconcile

[Service]
Type=oneshot
TimeoutStartSec=900
Environment=PATH=$path
ExecStart=$python -m devctk apply --yes --autostart-only

[Install]
WantedBy=default.target
"""


def render_service_unit(*, python: str, path: str) -> str:
    return Template(SERVICE_TEMPLATE).substitute(python=python, path=path)
