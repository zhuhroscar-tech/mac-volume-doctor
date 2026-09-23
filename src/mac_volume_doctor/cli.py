from __future__ import annotations

import argparse
import sys
from typing import Optional

from mac_volume_doctor.checks import tm


PLANNED_CHECKS = {
    "tm-snapshot": "planned: Time Machine local snapshot inspection",
    "spotlight": "planned: Spotlight indexing and open-handle inspection",
    "dmg": "planned: disk image resource-busy inspection",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mac-volume-doctor",
        description="Diagnose macOS volume eject/unmount blockers.",
    )
    subparsers = parser.add_subparsers(dest="check")

    tm_parser = subparsers.add_parser(
        "tm",
        help="inspect Time Machine destination and open-handle blockers",
        parents=[tm.build_parser()],
        add_help=False,
    )
    tm_parser.set_defaults(func=tm._run)

    for name, description in PLANNED_CHECKS.items():
        planned = subparsers.add_parser(name, help=description)
        planned.set_defaults(func=_planned_check, planned_check=name)

    return parser


def _planned_check(args: argparse.Namespace) -> int:
    print(f"mac-volume-doctor {args.planned_check}: this check is planned but not migrated yet.")
    return 64


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
