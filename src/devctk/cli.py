from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
COMMANDS = {"init", "ls", "rm"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devctk",
        description="One-command SSH-accessible rootless Podman dev containers.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    # --- init ---
    p_init = sub.add_parser("init", help="Create and enable a dev container.")
    p_init.add_argument("--image", required=True)
    p_init.add_argument("--port", type=int, default=39000)
    keys = p_init.add_mutually_exclusive_group(required=True)
    keys.add_argument("--authorized-keys", dest="authorized_keys_text")
    keys.add_argument("--authorized-keys-file", dest="authorized_keys_file")
    p_init.add_argument("--container-name")
    p_init.add_argument("--container-user")
    p_init.add_argument("--workspace")
    p_init.add_argument("--no-workspace", action="store_true")
    p_init.add_argument("--mount", action="append", default=[])
    p_init.add_argument("--device", action="append", default=[])

    # --- ls ---
    sub.add_parser("ls", help="List managed containers.")

    # --- rm ---
    p_rm = sub.add_parser("rm", help="Remove a managed container.")
    p_rm.add_argument("container_name", nargs="?")
    p_rm.add_argument("--all", action="store_true")

    return parser


def normalize_argv(argv: list[str]) -> list[str]:
    """Treat bare args (no subcommand) as `init`."""
    if not argv:
        return argv
    if argv[0] in COMMANDS or argv[0] in {"-h", "--help"}:
        return argv
    return ["init", *argv]


def split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1 :]


BANNED_PASSTHROUGH = {
    "--mount", "--volume", "--publish", "--name", "--device", "--user",
    "--userns", "--restart", "--rm", "--replace", "--entrypoint",
    "--init", "--stop-timeout",
}


def validate_passthrough(args: list[str]) -> None:
    for tok in args:
        if tok in BANNED_PASSTHROUGH or any(tok.startswith(f + "=") for f in BANNED_PASSTHROUGH):
            raise SystemExit(f"unsupported passthrough flag: {tok}")
        if tok.startswith(("-p", "-v", "-u")):
            raise SystemExit(f"unsupported passthrough flag: {tok}")


def main() -> int:
    from devctk.commands import cmd_init, cmd_ls, cmd_rm

    if os.geteuid() == 0:
        raise SystemExit("refuse to run as root")

    argv = normalize_argv(sys.argv[1:])
    ours, passthrough = split_passthrough(argv)
    parser = build_parser()
    args = parser.parse_args(ours)

    if args.command == "init":
        validate_passthrough(passthrough)
        return cmd_init(args, passthrough)
    if args.command == "ls":
        return cmd_ls()
    if args.command == "rm":
        return cmd_rm(args)

    raise SystemExit(f"unknown command: {args.command}")
