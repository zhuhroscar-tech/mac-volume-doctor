from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast


@dataclass
class Blocker:
    command: str
    pid: int
    user: str
    fd: str
    kind: str
    node: str
    name: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "command": self.command,
            "pid": self.pid,
            "user": self.user,
            "fd": self.fd,
            "kind": self.kind,
            "node": self.node,
            "name": self.name,
            "likely_reason": infer_reason(self.command, self.name),
        }


def infer_reason(command: str, name: str) -> str:
    low_cmd = command.lower()
    low_name = name.lower()
    if "mds" in low_cmd or "spotlight" in low_name:
        return "Spotlight indexing / metadata"
    if "photo" in low_cmd or "photos" in low_name or "photolibr" in low_cmd:
        return "Photos background analysis/workflows"
    if "fsevent" in low_cmd:
        return "File system events watcher"
    if "finder" in low_cmd:
        return "Finder background file-manager hold"
    return "Open file handle in directory or file"


class CommandFailed(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess]


def default_runner(cmd: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_command(
    cmd: List[str],
    *,
    runner: Runner = default_runner,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess:
    try:
        return runner(cmd, timeout=timeout)
    except FileNotFoundError as exc:
        raise CommandFailed(f"missing command: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandFailed(f"timed out running: {' '.join(cmd)}") from exc


def parse_lsof_output(text: str) -> List[Blocker]:
    blockers: List[Blocker] = []
    for raw in text.splitlines():
        line = raw.strip("\n")
        if not line:
            continue
        if line.startswith("COMMAND") or line.startswith("------"):
            continue
        if line.lower().startswith("lsof:"):
            continue

        cols = line.split()
        if len(cols) < 8:
            continue

        # lsof columns usually: COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME...
        command = cols[0]
        try:
            pid = int(cols[1])
        except ValueError:
            continue
        user = cols[2]
        fd = cols[3]
        kind = cols[4]
        node = cols[6] if len(cols) > 6 else ""
        name = " ".join(cols[7:]) if len(cols) > 7 else ""

        blockers.append(
            Blocker(
                command=command,
                pid=pid,
                user=user,
                fd=fd,
                kind=kind,
                node=node,
                name=name,
            )
        )

    uniq: Dict[str, Blocker] = {}
    for b in blockers:
        uniq[f"{b.pid}:{b.command}:{b.name}"] = b
    return list(uniq.values())


def query_lsof(target: str, *, runner: Runner = default_runner) -> List[Blocker]:
    result = run_command(["lsof", "+D", target], runner=runner, timeout=12.0)

    output = result.stdout or ""
    if "not a file system" in (result.stderr or "") and not output.strip():
        # Fallback: query the direct target; this often works for plain directories too.
        result = run_command(["lsof", target], runner=runner, timeout=12.0)
        output = result.stdout or ""
    return parse_lsof_output(output)


def query_diskutil_info(target: str, *, runner: Runner = default_runner) -> Dict[str, Optional[str]]:
    result = run_command(["diskutil", "info", target], runner=runner, timeout=12.0)
    info: Dict[str, Optional[str]] = {"Device Identifier": None, "Volume Name": None, "Mount Point": None}
    if result.returncode != 0:
        return info

    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        if key in info:
            info[key] = value
    return info


def query_mdutil(target: str, *, action: Optional[str] = None, runner: Runner = default_runner) -> str:
    cmd = ["mdutil"]
    if action == "off":
        cmd.extend(["-i", "off", target])
    elif action == "on":
        cmd.extend(["-i", "on", target])
    else:
        cmd.extend(["-s", target])

    result = run_command(cmd, runner=runner, timeout=20.0)
    return (result.stdout + "\n" + result.stderr).strip()


def parse_spotlight_status(output: str) -> Optional[bool]:
    text = output.lower()
    if "indexing enabled" in text:
        return True
    if "indexing disabled" in text:
        return False
    if "not indexed" in text or "not currently indexing" in text:
        return False
    if "not enabled" in text and "indexing" in text:
        return False
    return None


def run_diagnostic(target: str, *, runner: Runner = default_runner) -> Dict[str, object]:
    target_path = Path(target).expanduser().resolve()
    if not target_path.exists():
        raise CommandFailed(f"target does not exist: {target}")

    blockers = query_lsof(str(target_path), runner=runner)
    spotlight_output = query_mdutil(str(target_path), runner=runner)
    spotlight_status = parse_spotlight_status(spotlight_output)
    disk_info = query_diskutil_info(str(target_path), runner=runner)

    return {
        "check": "spotlight",
        "target": str(target_path),
        "disk_info": disk_info,
        "blockers": [b.as_dict() for b in blockers],
        "spotlight_indexing": spotlight_status,
        "spotlight_raw": spotlight_output.splitlines()[:4],
    }


def render_report(report: Dict[str, object]) -> str:
    disk_info = cast(Dict[str, Any], report.get("disk_info", {}))
    blockers = cast(List[Dict[str, Any]], report.get("blockers", []))
    lines = [
        f"mac-volume-doctor spotlight report for: {report['target']}",
        "-" * 60,
        f"Device: {disk_info.get('Device Identifier', 'unknown')}",
        f"Mount point: {disk_info.get('Mount Point', 'unknown')}",
    ]

    if not blockers:
        lines.append("Status: no open handles found for this path")
    else:
        lines.append(f"Status: {len(blockers)} handle(s) found")
        for b in blockers:
            lines.extend(
                [
                    f"- {b['command']} (pid {b['pid']}, user {b['user']}, fd {b['fd']})",
                    f"  -> {b['kind']} {b['name']}",
                    f"  likely: {b['likely_reason']}",
                ]
            )

    if report.get("spotlight_indexing") is True:
        lines.append("Spotlight: indexing appears enabled on this volume")
    elif report.get("spotlight_indexing") is False:
        lines.append("Spotlight: indexing appears disabled on this volume")
    else:
        lines.append("Spotlight: unable to determine indexing state")

    if blockers:
        spotlight_like = [b for b in blockers if b["likely_reason"] == "Spotlight indexing / metadata"]
        if spotlight_like:
            lines.append("Suggestion: Spotlight appears to hold files; try `--spotlight off` temporarily if safe.")

    return "\n".join(lines)


def toggle_spotlight(
    target: str,
    desired: str,
    *,
    runner: Runner = default_runner,
    interactive: bool = True,
) -> int:
    if desired not in {"off", "on", "status"}:
        raise ValueError("desired must be 'on', 'off', or 'status'")

    if desired == "status":
        output = query_mdutil(target, action=None, runner=runner)
        print(output)
        return 0

    if interactive:
        action = "disable" if desired == "off" else "enable"
        prompt = f"Type 'yes' to {action} Spotlight indexing for '{target}': "
        ans = input(prompt).strip().lower()
        if ans not in {"yes", "y"}:
            print("Aborted by user.")
            return 0

    output = query_mdutil(target, action=desired, runner=runner)
    if not output:
        output = f"Spotlight indexing command completed for {target}."
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect Spotlight/indexing blockers on a macOS volume path.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("target", help="Mounted volume path, e.g. /Volumes/MyDrive")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON and exit")
    parser.add_argument(
        "--spotlight",
        choices=["off", "on", "status"],
        help="Temporarily disable, enable, or query Spotlight indexing for the path",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not prompt for Spotlight changes (for automation)",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    try:
        if args.spotlight:
            rc = toggle_spotlight(
                args.target,
                args.spotlight,
                interactive=not args.no_prompt,
            )
            if rc != 0:
                return rc
            if args.spotlight == "status":
                return 0

        report = run_diagnostic(args.target)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(render_report(report))
    except CommandFailed as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
