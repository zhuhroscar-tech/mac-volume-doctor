# mac-volume-doctor

A macOS CLI suite for diagnosing why external volumes, Time Machine disks, local snapshots, Spotlight indexes, or mounted disk images block normal eject/unmount workflows.

This package is the consolidation target for the former single-purpose `mac-*-doctor` tools. Migrated checks currently cover Time Machine destination blockers, Time Machine local snapshots, and Spotlight indexing/open-handle blockers.

## Install

Requires macOS, Python 3.8+, and Apple's system tools used by each check. The Time Machine destination check uses `lsof`, `tmutil`, and `diskutil`; the snapshot check uses `tmutil`; the Spotlight check uses `lsof`, `mdutil`, and `diskutil`.

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

Inspect local Time Machine snapshots:

```bash
mac-volume-doctor tm-snapshot
mac-volume-doctor tm-snapshot --volume / --json list
mac-volume-doctor tm-snapshot --volume / health
```

Inspect Spotlight and open-handle blockers:

```bash
mac-volume-doctor spotlight "/Volumes/External"
mac-volume-doctor spotlight --json "/Volumes/External"
mac-volume-doctor spotlight --spotlight status "/Volumes/External"
```

For compatibility during migration, installing this package also exposes:

```bash
mac-tm-doctor "/Volumes/Time Machine"
mac-tm-snapshot-doctor --volume / list
mac-spotlight-doctor "/Volumes/External"
```

## Checks

| Check | Status | What it reports |
| --- | --- | --- |
| `tm` | migrated | Open-file holders, Time Machine status, configured backup destinations, disk metadata, and next-step guidance. |
| `tm-snapshot` | migrated | Local snapshot inventory, known snapshot paths, backup-status fields, and manual cleanup guidance. |
| `spotlight` | migrated | Spotlight indexing state, open-handle context, likely holder classification, and optional indexing toggle commands. |
| `dmg` | planned | Mounted disk-image and resource-busy diagnostics. |

## Safety

The default checks are read-only and do not kill processes, force-unmount volumes, eject disks, delete snapshots, or make network requests. State-changing options are explicit: `tm --stop-backup` calls `tmutil stopbackup`, and `spotlight --spotlight off|on` calls `mdutil -i off|on` for the supplied path after a confirmation prompt unless `--no-prompt` is used.

Missing permissions, command failures, timeouts, or unrecognized system output can hide blockers. A clean report is not proof that ejecting is safe; treat the output as evidence for normal Finder/Disk Utility follow-up.

## Development

```bash
python -m pytest -q
```

[MIT license](LICENSE)
