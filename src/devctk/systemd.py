"""Render the global devctk user service."""

from __future__ import annotations

from string import Template

SERVICE_TEMPLATE = """\
[Unit]
Description=devctk autostart reconcile

[Service]
Type=oneshot
RemainAfterExit=yes
KillMode=process
TimeoutStartSec=900
Environment=PATH=$path
Environment=XDG_CONFIG_HOME=$xdg_config_home
Environment=XDG_STATE_HOME=$xdg_state_home
ExecStart=$python -m devctk apply --yes --autostart-only

[Install]
WantedBy=default.target
"""


def render_service_unit(
    *, python: str, path: str, xdg_config_home: str, xdg_state_home: str
) -> str:
    return Template(SERVICE_TEMPLATE).substitute(
        python=python,
        path=path,
        xdg_config_home=xdg_config_home,
        xdg_state_home=xdg_state_home,
    )
