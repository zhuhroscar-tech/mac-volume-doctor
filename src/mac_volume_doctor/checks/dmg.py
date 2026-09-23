from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple


def run_command(cmd: List[str], timeout: int = 3) -> Tuple[int, str, str]:
    """Run *cmd* and return ``(returncode, stdout, stderr)``."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out"
    except OSError as exc:  # pragma: no cover - environment-specific
        return 1, "", str(exc)


def parse_mounts(raw: str) -> Dict[str, str]:
    """Parse ``mount`` output and return ``{mountpoint: device}`` for /Volumes paths."""
    mounts: Dict[str, str] = {}
    for line in raw.splitlines():
        if " on " not in line or " (" not in line:
            continue
        left, right = line.split(" on ", 1)
        mount_point = right.split(" (", 1)[0]
        if mount_point.startswith("/Volumes/"):
            mounts[mount_point] = left.strip()
    return mounts


def collect_mounts() -> Dict[str, str]:
    code, out, _ = run_command(["mount"])
    if code != 0:
        return {}
    return parse_mounts(out)


def parse_lsof_processes(raw: str) -> List[Dict[str, str]]:
    """Parse minimal command/pid rows from lsof output."""
    lines = raw.splitlines()
    if len(lines) <= 1:
        return []
    rows: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        cmd, pid = fields[0], fields[1]
        key = (cmd, pid)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"command": cmd, "pid": pid})
    return rows


def open_processes(path: str) -> List[Dict[str, str]]:
    code, out, _ = run_command(["lsof", "+D", path], timeout=5)
    if code != 0:
        return []
    return parse_lsof_processes(out)


def parse_hdiutil_info(raw: str) -> List[Dict[str, str]]:
    """Extract mounted image path hints from ``hdiutil info`` text."""
    entries: List[Dict[str, str]] = []
    current: Dict[str, str] = {}

    for line in raw.splitlines():
        lower = line.lower().strip()
        if not lower:
            continue

        if lower.startswith("image") and "path" in lower and ":" in line:
            key, value = map(str.strip, line.split(":", 1))
            norm = key.lower().replace(" ", "-")
            if "image-path" in norm:
                if current and current.get("mountpoint"):
                    entries.append(current)
                    current = {}
                current["image_path"] = value
                continue

        if "mountpoint" in lower and ":" in line:
            key, value = map(str.strip, line.split(":", 1))
            norm = key.lower().replace(" ", "-")
            if "mountpoint" == norm:
                current["mountpoint"] = value
                continue

        if lower.startswith("/dev/") and "/" in line:
            token = line.split()[0].strip()
            if token.startswith("/dev/") and not token.endswith(")"):
                if token and token not in current.get("device", ""):
                    current["device"] = token

    if current and (current.get("image_path") or current.get("mountpoint") or current.get("device")):
        entries.append(current)

    return entries


def collect_hdi_images() -> Dict[str, str]:
    """Return map of mountpoint -> image path from ``hdiutil info``."""
    code, out, _ = run_command(["hdiutil", "info"])
    if code != 0:
        return {}

    result: Dict[str, str] = {}
    for item in parse_hdiutil_info(out):
        mount_point = item.get("mountpoint")
        image_path = item.get("image_path")
        if mount_point and image_path:
            result[mount_point] = image_path
    return result


def _recommendations(
    mount_point: str,
    device: str,
    image_path: Optional[str],
    holders: List[Dict[str, str]],
) -> List[str]:
    recs: List[str] = []
    if holders:
        recs.append("Close the listed processes before detaching the volume.")
        recs.append("If this is a DMG or sparsebundle, run: hdiutil detach <device-or-image-id>")
        if image_path:
            recs.append(f"Image path: {image_path}")
        recs.append(f"Re-run `mac-volume-doctor dmg inspect {mount_point}` after closing apps.")
    else:
        recs.append("No open handles detected via lsof for this mountpoint.")
        if device:
            recs.append(f"Try a standard detach: hdiutil detach {device}")
        recs.append("If a system process holds the volume, wait a few seconds and retry.")
    return recs


def inspect_target(path: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "check": "dmg",
        "mountpoint": path,
        "device": None,
        "hdi_image_path": None,
        "open_processes": [],
        "recommendations": [],
    }

    mounts = collect_mounts()
    if path in mounts:
        report["device"] = mounts[path]

    report["open_processes"] = open_processes(path)
    image_map = collect_hdi_images()
    if path in image_map:
        report["hdi_image_path"] = image_map[path]

    report["recommendations"] = _recommendations(
        mount_point=path,
        device=report["device"] or "",
        image_path=report.get("hdi_image_path"),
        holders=report["open_processes"],
    )

    return report


def scan_busy_mounts() -> Dict[str, Any]:
    mounts = collect_mounts()
    if not mounts:
        return {"check": "dmg", "mounted": 0, "busy": []}

    image_map = collect_hdi_images()
    busy: List[Dict[str, Any]] = []
    for mount_point in sorted(mounts):
        holders = open_processes(mount_point)
        if not holders:
            continue

        busy.append(
            {
                "mountpoint": mount_point,
                "device": mounts[mount_point],
                "open_processes": holders,
                "hdi_image_path": image_map.get(mount_point),
                "handle_count": len(holders),
            }
        )

    return {"check": "dmg", "mounted": len(mounts), "busy": busy}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose busy DMG/sparse image and mounted-volume handles on macOS")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    subparsers = parser.add_subparsers(dest="command")

    inspect = subparsers.add_parser("inspect", help="Inspect one mounted path")
    inspect.add_argument("path", help="Mount point or path to inspect")

    subparsers.add_parser("scan", help="Find mounted paths with active open handles")
    parser.set_defaults(command="scan")
    return parser


def _print_scan(report: Dict[str, Any]) -> None:
    print(f"Mounted volumes: {report['mounted']}")
    if not report["busy"]:
        print("No busy mount points detected")
        return

    print(f"Busy mount points: {len(report['busy'])}")
    for item in report["busy"]:
        print(item["mountpoint"])
        print(f"  device: {item['device']}")
        print(f"  open_handles: {item['handle_count']}")
        if item.get("hdi_image_path"):
            print(f"  image: {item['hdi_image_path']}")


def _print_inspect(report: Dict[str, Any]) -> None:
    print(f"Mountpoint: {report['mountpoint']}")
    if report.get("device"):
        print(f"Device: {report['device']}")
    if report.get("hdi_image_path"):
        print(f"Image: {report['hdi_image_path']}")
    print(f"Open handles: {len(report['open_processes'])}")
    for proc in report["open_processes"]:
        print(f"- {proc['command']} ({proc['pid']})")
    print("Recommendations:")
    for line in report["recommendations"]:
        print(f" - {line}")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _run(args: argparse.Namespace) -> int:
    if args.command == "inspect":
        report = inspect_target(args.path)
        if args.json:
            _print_json(report)
        else:
            _print_inspect(report)
        return 0

    if args.command == "scan":
        report = scan_busy_mounts()
        if args.json:
            _print_json(report)
        else:
            _print_scan(report)
        return 0

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
