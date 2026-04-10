from __future__ import annotations

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devctk",
        description="One-command rootless Podman dev containers.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    # --- init ---
    p_init = sub.add_parser("init", help="Create and enable a dev container.")
    p_init.add_argument("--image", required=True)
    p_init.add_argument("--name", dest="container_name")

    # SSH (opt-in)
    p_init.add_argument("--ssh", action="store_true", help="Enable SSH access")
    p_init.add_argument("--port", type=int, default=39000)
    keys = p_init.add_mutually_exclusive_group()
    keys.add_argument("--authorized-keys", dest="authorized_keys_text")
    keys.add_argument("--authorized-keys-file", dest="authorized_keys_file")

    # Features
    p_init.add_argument("--nix", action="store_true", help="Mount Nix store and set PATH")
    p_init.add_argument("--mise", action="store_true", help="Mount mise tool installs and set PATH")
    p_init.add_argument("--agent", action="append", default=[], choices=["claude", "codex"],
                        help="Mount agent config dirs (repeatable)")

    # Workspace
    p_init.add_argument("--workspace")
    p_init.add_argument("--no-workspace", action="store_true")
    p_init.add_argument("--mirror", action="store_true",
                        help="Mount workspace at same absolute path as host")

    # Lifecycle
    p_init.add_argument("--systemd", action="store_true",
                        help="Manage via systemd user units (auto-start on boot)")

    # Extra podman flags (everything after --)
    p_init.add_argument("--mount", action="append", default=[])
    p_init.add_argument("--device", action="append", default=[])

    # --- ls ---
    sub.add_parser("ls", help="List managed containers.")

    # --- rm ---
    p_rm = sub.add_parser("rm", help="Remove a managed container.")
    p_rm.add_argument("container_name", nargs="?")
    p_rm.add_argument("--all", action="store_true")

    return parser


def _split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv at ``--`` into our args and podman passthrough."""
    if "--" not in argv:
        return argv, []
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1 :]


def main() -> int:
    from devctk.commands import cmd_init, cmd_ls, cmd_rm

    if os.geteuid() == 0:
        raise SystemExit("refuse to run as root")

    ours, passthrough = _split_passthrough(sys.argv[1:])
    parser = build_parser()
    args = parser.parse_args(ours)

    if args.command == "init":
        # SSH flag dependencies
        if args.ssh:
            if not args.authorized_keys_text and not args.authorized_keys_file:
                raise SystemExit("--ssh requires --authorized-keys or --authorized-keys-file")
        elif args.authorized_keys_text or args.authorized_keys_file:
            raise SystemExit("--authorized-keys requires --ssh")

        # Workspace conflicts
        if args.no_workspace and args.workspace:
            raise SystemExit("--workspace and --no-workspace conflict")
        if args.no_workspace and args.mirror:
            raise SystemExit("--mirror and --no-workspace conflict")

        return cmd_init(args, passthrough)

    if args.command == "ls":
        return cmd_ls()

    if args.command == "rm":
        return cmd_rm(args)

    raise SystemExit(f"unknown command: {args.command}")
