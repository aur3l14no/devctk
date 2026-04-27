from __future__ import annotations

from devctk.systemd import render_service_unit


def test_service_unit_does_not_kill_started_containers() -> None:
    unit = render_service_unit(
        python="/usr/bin/python",
        path="/usr/bin:/bin",
        xdg_config_home="/home/u/.config",
        xdg_state_home="/home/u/.local/state",
    )

    assert "Type=oneshot\n" in unit
    assert "RemainAfterExit=yes\n" in unit
    assert "KillMode=process\n" in unit
    assert "ExecStart=/usr/bin/python -m devctk apply --yes --autostart-only\n" in unit
