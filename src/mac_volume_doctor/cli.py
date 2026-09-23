from __future__ import annotations

import argparse
import sys
from typing import Optional

from mac_volume_doctor.checks import dmg, spotlight, tm, tm_snapshot


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

    tm_snapshot_parser = subparsers.add_parser(
        "tm-snapshot",
        help="inspect Time Machine local snapshots and backup status",
        parents=[tm_snapshot.build_parser()],
        add_help=False,
    )
    tm_snapshot_parser.set_defaults(func=tm_snapshot._run)

    spotlight_parser = subparsers.add_parser(
        "spotlight",
        help="inspect Spotlight indexing state and open-handle blockers",
        parents=[spotlight.build_parser()],
        add_help=False,
    )
    spotlight_parser.set_defaults(func=spotlight._run)

    dmg_parser = subparsers.add_parser(
        "dmg",
        help="inspect mounted DMG/sparse image and resource-busy blockers",
        parents=[dmg.build_parser()],
        add_help=False,
    )
    dmg_parser.set_defaults(func=dmg._run)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
