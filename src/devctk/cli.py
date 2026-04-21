from __future__ import annotations

import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devctk",
        description="Declarative rootless Podman dev containers.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p_apply = sub.add_parser("apply", help="Reconcile config.toml into running containers.")
    p_apply.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation",
    )
    p_apply.add_argument(
        "--autostart-only",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    sub.add_parser("ls", help="List configured or tracked containers.")

    p_rm = sub.add_parser("rm", help="Remove live containers and tracked state entries.")
    p_rm.add_argument("container_name", nargs="?")
    p_rm.add_argument(
        "--all",
        action="store_true",
        help="Remove all tracked containers",
    )
    p_rm.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation",
    )

    return parser


def main() -> int:
    from devctk.commands import cmd_apply, cmd_ls, cmd_rm

    if os.geteuid() == 0:
        raise SystemExit("refuse to run as root")

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "apply":
        return cmd_apply(args)
    if args.command == "ls":
        return cmd_ls()
    if args.command == "rm":
        return cmd_rm(args)

    raise SystemExit(f"unknown command: {args.command}")
