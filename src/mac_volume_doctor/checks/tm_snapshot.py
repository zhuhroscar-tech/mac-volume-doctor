from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

SNAPSHOT_ID_RE = re.compile(r"com\.apple\.TimeMachine\.\d{4}-\d{2}-\d{2}-\d{6}\.local")


def run_tmutil(args: List[str]) -> tuple[int, str, str]:
    """Run tmutil and return ``(returncode, stdout, stderr)``."""
    try:
        proc = subprocess.run(["tmutil", *args], capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "tmutil not found on PATH"
    except OSError as exc:  # pragma: no cover - environment-specific edge case
        return 1, "", str(exc)


def snapshot_locations(volume: str) -> List[str]:
    """Return existing local-snapshot directories relevant to *volume*."""
    candidates = [
        os.path.join(volume, ".com.apple.TimeMachine.localsnapshots"),
        os.path.join(volume, ".MobileBackups"),
        os.path.join("/Volumes", "com.apple.TimeMachine.localsnapshots"),
        os.path.join("/Volumes", ".MobileBackups"),
    ]
    return [p for p in candidates if os.path.isdir(p)]


def parse_snapshot_list(stdout: str) -> List[str]:
    """Extract local snapshot IDs from tmutil output."""
    return sorted(set(SNAPSHOT_ID_RE.findall(stdout)))


def find_tmutil_status(stdout: str) -> Dict[str, Any]:
    """Extract minimal fields from ``tmutil status`` output."""
    status: Dict[str, Any] = {"running": None, "phase": None, "bytes": None}

    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Running"):
            if re.search(r"=\s*1|=\s*true", line, re.IGNORECASE):
                status["running"] = True
            elif re.search(r"=\s*0|=\s*false", line, re.IGNORECASE):
                status["running"] = False
        elif line.startswith("Phase") and "=" in line:
            status["phase"] = line.split("=", 1)[1].strip().strip("; ")
        elif line.startswith("Bytes") and "=" in line:
            number = re.findall(r"\d+", line)
            status["bytes"] = int(number[0]) if number else None

    return status


def list_snapshots(volume: str) -> Dict[str, Any]:
    code, out, err = run_tmutil(["listlocalsnapshots", volume])
    result: Dict[str, Any] = {"volume": volume, "snapshots": [], "error": None}
    if code != 0:
        result["error"] = err or out or "tmutil failed"
        return result

    result["snapshots"] = parse_snapshot_list(out)
    return result


def health_report(volume: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "check": "tm-snapshot",
        "volume": volume,
        "snapshot_paths": snapshot_locations(volume),
        "snapshots": [],
        "snapshot_count": 0,
        "tmutil_list_error": None,
        "tmutil_status": {"running": None, "phase": None, "bytes": None},
    }

    list_result = list_snapshots(volume)
    report["snapshots"] = list_result["snapshots"]
    report["snapshot_count"] = len(list_result["snapshots"])
    report["tmutil_list_error"] = list_result["error"]

    code, status_out, status_err = run_tmutil(["status"])
    if code == 0:
        report["tmutil_status"] = find_tmutil_status(status_out)
    else:
        report["tmutil_status_error"] = status_err or status_out

    report["recommendations"] = recommendation_lines(report)
    return report


def recommendation_lines(report: Dict[str, Any]) -> List[str]:
    recommendations: List[str] = []
    if report.get("tmutil_list_error"):
        recommendations.append("tmutil is unavailable or failed. Run directly: tmutil listlocalsnapshots <volume>.")
        return recommendations

    volume = str(report.get("volume") or "/")
    count = int(report.get("snapshot_count") or 0)
    if count == 0:
        recommendations.append("No local snapshots were detected for this volume at command time.")
        return recommendations

    if report.get("tmutil_status", {}).get("running"):
        recommendations.append("Time Machine appears active. Retry after backup finishes for cleaner snapshot changes.")

    recommendations.append(f"List snapshot timestamps manually with: tmutil listlocalsnapshotdates {volume}.")
    recommendations.append("Remove one snapshot with: sudo tmutil deletelocalsnapshots <TIMESTAMP>.")
    recommendations.append("Disable local snapshots temporarily in Time Machine preferences only if safe for your workflow.")

    if count > 20:
        recommendations.append("High snapshot count may indicate hidden cache growth; review backup exclusions and free-space health.")

    return recommendations


def render_health(report: Dict[str, Any]) -> str:
    lines = [
        f"mac-volume-doctor tm-snapshot report for: {report['volume']}",
        "-" * 60,
        f"Snapshot paths visible: {', '.join(report['snapshot_paths']) or '(none)'}",
    ]
    if report["tmutil_list_error"]:
        lines.append(f"Error: {report['tmutil_list_error']}")
    else:
        lines.append(f"Snapshots: {report['snapshot_count']}")

    if report["tmutil_status"].get("running") is not None:
        lines.append(f"Backup running: {report['tmutil_status']['running']}")
        if report["tmutil_status"].get("phase"):
            lines.append(f"Phase: {report['tmutil_status']['phase']}")

    if report["recommendations"]:
        lines.append("")
        lines.append("Recommendations:")
        for item in report["recommendations"]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def render_list(result: Dict[str, Any]) -> str:
    if result["error"]:
        return f"Error: {result['error']}"

    snapshots = result["snapshots"]
    if not snapshots:
        return "No local snapshots found"

    return "\n".join(snapshots)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_report(volume: str, as_json: bool) -> int:
    report = health_report(volume)
    if as_json:
        _print_json(report)
    else:
        print(render_health(report))
    return 0 if report.get("tmutil_list_error") is None else 1


def run_list(volume: str, as_json: bool) -> int:
    result = list_snapshots(volume)
    if as_json:
        _print_json(result)
    else:
        print(render_list(result))

    return 0 if result["error"] is None else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose Time Machine local snapshots on macOS")
    parser.add_argument("--volume", default="/", help="Volume to inspect (default: /)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("health", help="Show a full snapshot health report")
    subparsers.add_parser("list", help="List snapshot identifiers")

    parser.set_defaults(command="health")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "list":
        return run_list(args.volume, args.json)
    return run_report(args.volume, args.json)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
