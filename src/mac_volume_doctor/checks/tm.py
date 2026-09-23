from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, cast


@dataclass
class TMBlocker:
    pid: int
    user: str
    command: str
    fd: str
    file_path: str
    reason: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "pid": self.pid,
            "user": self.user,
            "command": self.command,
            "fd": self.fd,
            "path": self.file_path,
            "reason": self.reason,
        }


class CommandError(RuntimeError):
    """Raised when a wrapped system command fails unexpectedly."""


def run_command(cmd: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def parse_lsof_output(raw: str) -> List[TMBlocker]:
    blocks: List[TMBlocker] = []
    seen = set()

    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("COMMAND") or s.startswith("lsof:"):
            continue
        parts = s.split(None, 8)
        if len(parts) < 8:
            continue
        command, pid_text, user, fd = parts[0], parts[1], parts[2], parts[3]
        if not pid_text.isdigit():
            continue
        path = parts[8] if len(parts) >= 9 else (parts[7] if len(parts) >= 8 else "")
        if not path:
            continue

        if fd.lower().startswith("cwd"):
            reason = "current working directory"
        elif fd.startswith("txt"):
            reason = "loaded executable"
        elif fd.startswith("mmap"):
            reason = "memory map"
        elif fd.lower().startswith("r"):
            reason = "read file descriptor"
        elif fd.lower().startswith("w"):
            reason = "write file descriptor"
        else:
            reason = "open handle"

        key = (pid_text, command, user, path, reason)
        if key in seen:
            continue
        seen.add(key)

        blocks.append(
            TMBlocker(
                pid=int(pid_text),
                user=user,
                command=command,
                fd=fd,
                file_path=path,
                reason=reason,
            )
        )

    return blocks


def parse_tmutil_status(raw: str) -> Dict[str, object]:
    running = False
    phase = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        if '"Running"' in line or "Running" in line:
            if "=" in line and ";" in line:
                rhs = line.split("=", 1)[1].strip().rstrip(";")
                rhs = rhs.strip('"')
                if rhs in {"1", "true", "TRUE", "YES"}:
                    running = True
                elif rhs in {"0", "false", "FALSE", "NO"}:
                    running = False

        if '"CurrentPhase"' in line or "CurrentPhase" in line:
            if "=" in line and ";" in line:
                rhs = line.split("=", 1)[1].strip().rstrip(";")
                phase = rhs.strip().strip('"')

    return {"running": running, "currentPhase": phase}


def parse_tmutil_destinationinfo(raw: str) -> List[str]:
    mounts: List[str] = []
    for line in raw.splitlines():
        if "Mount Point:" not in line:
            continue
        _, value = line.split(":", 1)
        mount = value.strip()
        if mount:
            mounts.append(mount)
    return mounts


def parse_diskutil_info(raw: str) -> Dict[str, str]:
    info: Dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info


def is_tm_target(mount_point: str, tm_mounts: List[str]) -> bool:
    if not tm_mounts:
        return False
    for m in tm_mounts:
        if mount_point == m or mount_point.startswith(m + "/"):
            return True
    return False


def run_diagnostic(target: str, command_runner=run_command) -> Dict[str, object]:
    mount_point = Path(target).resolve()
    report: Dict[str, object] = {
        "check": "tm",
        "target": str(mount_point),
    }

    lsof_cmd = ["lsof", "+D", str(mount_point)]
    lsof_raw = command_runner(lsof_cmd).stdout
    blockers = parse_lsof_output(lsof_raw)

    tm_status_raw = command_runner(["tmutil", "status"]).stdout
    tm_status = parse_tmutil_status(tm_status_raw)

    tm_dest_raw = command_runner(["tmutil", "destinationinfo"]).stdout
    tm_mounts = parse_tmutil_destinationinfo(tm_dest_raw)

    diskutil_raw = command_runner(["diskutil", "info", str(mount_point)]).stdout
    diskutil_info = parse_diskutil_info(diskutil_raw)

    target_is_tm = is_tm_target(str(mount_point), tm_mounts)

    report.update(
        {
            "mountPoint": str(mount_point),
            "blockers": [b.as_dict() for b in blockers],
            "timeMachine": {
                "status": tm_status,
                "isConfiguredTarget": target_is_tm,
                "destinationMounts": tm_mounts,
            },
            "diskInfo": diskutil_info,
        }
    )

    suggestions: List[str] = []
    if blockers:
        pids = {blocker.pid for blocker in blockers}
        top = sorted(pids)[:5]
        suggestions.append(f"Open Activity Monitor and inspect PIDs: {', '.join(map(str, top))}")

    if tm_status.get("running"):
        suggestions.append("Stop/finish the current Time Machine cycle before ejecting (tmutil stopbackup).")

    if target_is_tm and not tm_status.get("running") and blockers:
        suggestions.append("The volume is a Time Machine destination; a backup daemon may be re-scanning metadata. Retry a few seconds later.")

    if not tm_status.get("running") and not blockers:
        suggestions.append("No active Time Machine or open-handle blockers detected.")

    report["suggestions"] = suggestions
    return report


def render_report(report: Dict[str, object]) -> str:
    target = str(report["target"])
    blockers = cast(List[Dict[str, Any]], report.get("blockers", []))
    tm_info = cast(Dict[str, Any], report.get("timeMachine", {}))
    suggestions = cast(List[str], report.get("suggestions", []))

    lines: List[str] = []
    lines.append(f"mac-volume-doctor tm report for: {target}")
    lines.append("-" * 60)
    lines.append(f"Time Machine running: {bool(tm_info.get('status', {}).get('running') if isinstance(tm_info, dict) else False)}")
    lines.append(f"Current TM phase: {tm_info.get('status', {}).get('currentPhase') if isinstance(tm_info, dict) else None}")
    lines.append(f"Target is Time Machine destination: {bool(tm_info.get('isConfiguredTarget', False) if isinstance(tm_info, dict) else False)}")

    if blockers:
        lines.append(f"{len(blockers)} blocker(s) detected:")
        for b in blockers:
            lines.append(f"  - {b['command']} (pid {b['pid']}, user {b['user']}): {b['reason']} [{b['fd']}]")
            lines.append(f"    path: {b['path']}")
    else:
        lines.append("No open handle blockers via lsof.")

    if suggestions:
        lines.append("")
        lines.append("Suggested next steps:")
        for item in suggestions:
            lines.append(f"- {item}")

    return "\n".join(lines)


def _stop_tm_backup(runner=run_command) -> int:
    proc = runner(["tmutil", "stopbackup"])
    if proc.returncode != 0:
        print(proc.stderr.strip() or "Could not stop Time Machine backup.")
    else:
        print("Requested Time Machine stop.")
    return proc.returncode


def _run(args: argparse.Namespace) -> int:
    if args.stop_backup:
        code = _stop_tm_backup()
        if code != 0:
            return code

    deadline = time.time() + float(args.wait)
    while True:
        report = run_diagnostic(args.target)
        if args.json:
            import json

            print(json.dumps(report, indent=2))
        else:
            print(render_report(report))

        tm_status = cast(Dict[str, Any], cast(Dict[str, Any], report["timeMachine"])["status"])
        if not report["blockers"] and not tm_status.get("running"):
            return 0

        if args.wait == 0:
            return 2

        if time.time() >= deadline:
            print("Timed out waiting for blockers to clear.")
            return 3

        time.sleep(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Time Machine and open-handle blockers for a mounted volume.")
    parser.add_argument("target", help="Mounted volume path, e.g. /Volumes/MyTimeMachine")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON and exit")
    parser.add_argument("--stop-backup", action="store_true", help="Request tmutil stopbackup before diagnostic")
    parser.add_argument("--wait", type=int, default=0, help="Wait up to N seconds for blockers to clear")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
