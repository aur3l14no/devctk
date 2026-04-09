"""Render systemd user unit files from embedded templates."""

from __future__ import annotations

from string import Template

TEMPLATES = {
    "container": """\
[Unit]
Description=devctk container $container_name

[Service]
Type=simple
TimeoutStartSec=300
TimeoutStopSec=15
Restart=on-failure
RestartSec=5
ExecStartPre=$container_helper create
ExecStart=$container_helper start
ExecStop=$container_helper stop

[Install]
WantedBy=default.target
""",
    "sshd": """\
[Unit]
Description=devctk sshd in $container_name
Requires=$container_unit
After=$container_unit
BindsTo=$container_unit
PartOf=$container_unit

[Service]
Type=simple
TimeoutStartSec=300
Restart=always
RestartSec=5
ExecStart=$sshd_helper start
ExecStop=$sshd_helper stop

[Install]
WantedBy=default.target
""",
}


def render_unit(kind: str, **values: str) -> str:
    return Template(TEMPLATES[kind]).substitute(values)
