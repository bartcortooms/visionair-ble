from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .commands import get_command_specs
from .config import load_env
from .controller import VMICtl


def _build_parser(commands: dict[str, object]) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vmictl",
        description="VMI control/capture CLI",
        allow_abbrev=False,
    )
    p.add_argument("command", nargs="?", default="help")
    p.add_argument("args", nargs="*")
    p.epilog = "Available commands: " + ", ".join(sorted(commands))
    return p


def _print_help(commands: dict[str, object]) -> None:
    print("vmictl commands:")
    for name in sorted(commands):
        spec = commands[name]
        help_text = getattr(spec, "help", "")
        print(f"  {name:<20} {help_text}")


def main(argv: list[str] | None = None) -> int:
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[3]
    load_env(project_root)

    command_specs = get_command_specs()
    parser = _build_parser(command_specs)
    ns, extras = parser.parse_known_args(argv)

    command = ns.command
    args = [*ns.args, *extras]

    if command in ("help", "--help", "-h"):
        _print_help(command_specs)
        return 0

    spec = command_specs.get(command)
    if spec is None:
        parser.print_help()
        print(f"\nERROR: Unknown command: {command}", file=sys.stderr)
        return 1

    ctl = VMICtl(adb_target=os.environ.get("ADB_TARGET", ""), project_root=project_root)
    try:
        ctl.maybe_warn_battery()
        rc = spec.handler(ctl, args)
        if rc == 0 and spec.modifies_vmi:
            ctl.log_vmi_action(command, args)
        return rc
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
