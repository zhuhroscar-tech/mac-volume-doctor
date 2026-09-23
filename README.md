# mac-volume-doctor

A macOS CLI suite for diagnosing why external volumes, Time Machine disks, local snapshots, Spotlight indexes, or mounted disk images block normal eject/unmount workflows.

This package is the consolidation target for the former single-purpose `mac-*-doctor` tools. The first migrated check is the Time Machine destination diagnostic from `mac-tm-doctor`.

## Install

Requires macOS, Python 3.8+, and Apple's system tools used by each check. The Time Machine check uses `lsof`, `tmutil`, and `diskutil`.

```bash
git clone https://github.com/zhuhroscar-tech/mac-volume-doctor.git
cd mac-volume-doctor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
```

This is Python source/packaged software, not a signed or notarized Mac application.

## Usage

Run a Time Machine destination report:

```bash
mac-volume-doctor tm "/Volumes/Time Machine"
mac-volume-doctor tm --json "/Volumes/Time Machine"
mac-volume-doctor tm --wait 30 "/Volumes/Time Machine"
```

For compatibility during migration, installing this package also exposes:

```bash
mac-tm-doctor "/Volumes/Time Machine"
```

## Checks

| Check | Status | What it reports |
| --- | --- | --- |
| `tm` | migrated | Open-file holders, Time Machine status, configured backup destinations, disk metadata, and next-step guidance. |
| `tm-snapshot` | planned | Local snapshot inventory and backup-status guidance. |
| `spotlight` | planned | Spotlight indexing state and open-handle context. |
| `dmg` | planned | Mounted disk-image and resource-busy diagnostics. |

## Safety

The default checks are read-only and do not kill processes, force-unmount volumes, eject disks, or make network requests. `tm --stop-backup` is the only migrated state-changing option; it calls `tmutil stopbackup` and affects the current Time Machine backup, not just the supplied path.

Missing permissions, command failures, timeouts, or unrecognized system output can hide blockers. A clean report is not proof that ejecting is safe; treat the output as evidence for normal Finder/Disk Utility follow-up.

## Development

```bash
python -m pytest -q
```

[MIT license](LICENSE)
