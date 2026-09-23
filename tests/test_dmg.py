from unittest.mock import patch

from mac_volume_doctor.checks import dmg


def test_parse_mounts() -> None:
    text = """/dev/disk1s1 on / (apfs, local, read-only, noowners)
/dev/disk2s1 on /Volumes/ExampleVol (apfs, local, nodev, nosuid, read-write)
/dev/disk3s1 on /Volumes/Test Image (apfs, local, nodev, nosuid, read-write)
"""
    mounts = dmg.parse_mounts(text)
    assert len(mounts) == 2
    assert mounts["/Volumes/ExampleVol"] == "/dev/disk2s1"
    assert mounts["/Volumes/Test Image"] == "/dev/disk3s1"


def test_parse_lsof_processes() -> None:
    text = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
Finder 100 oscar cwd DIR 1,4 4096 1234 /Volumes/Example
chrome 101 oscar txt REG 1,4 1024 5678 /Applications/.."""
    rows = dmg.parse_lsof_processes(text)
    assert len(rows) == 2
    assert rows[0]["command"] == "Finder"


def test_parse_lsof_processes_deduplicates_command_pid() -> None:
    text = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
Finder 100 oscar cwd DIR 1,4 4096 1234 /Volumes/Example
Finder 100 oscar txt REG 1,4 1024 5678 /Volumes/Example/file"""
    rows = dmg.parse_lsof_processes(text)
    assert rows == [{"command": "Finder", "pid": "100"}]


def test_parse_hdiutil_info() -> None:
    text = """image-path: /Users/oscar/Documents/Test.dmg
   /dev/disk8
   mountpoint: /Volumes/TestImage
"""
    parsed = dmg.parse_hdiutil_info(text)
    assert len(parsed) == 1
    assert parsed[0]["image_path"] == "/Users/oscar/Documents/Test.dmg"
    assert parsed[0]["mountpoint"] == "/Volumes/TestImage"


@patch("mac_volume_doctor.checks.dmg.run_command")
def test_scan_busy_mounts(run_command) -> None:
    def side_effect(cmd, timeout=3):
        if cmd == ["mount"]:
            return (
                0,
                (
                    "/dev/disk2s1 on /Volumes/BusyVol (apfs, local, nodev, nosuid, read-write)\n"
                    "/dev/disk3s1 on /Volumes/FreeVol (apfs, local, nodev, nosuid, read-write)"
                ),
                "",
            )
        if cmd[0:2] == ["lsof", "+D"]:
            if cmd[2] == "/Volumes/BusyVol":
                return (
                    0,
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nFinder 123 oscar cwd DIR 1,4 0 0 /Volumes/BusyVol",
                    "",
                )
            return 1, "", ""
        if cmd == ["hdiutil", "info"]:
            return 0, "", ""
        return 1, "", "unexpected"

    run_command.side_effect = side_effect
    report = dmg.scan_busy_mounts()
    assert report["check"] == "dmg"
    assert report["mounted"] == 2
    assert len(report["busy"]) == 1
    assert report["busy"][0]["mountpoint"] == "/Volumes/BusyVol"
    assert report["busy"][0]["open_processes"][0]["command"] == "Finder"


@patch("mac_volume_doctor.checks.dmg.collect_hdi_images")
@patch("mac_volume_doctor.checks.dmg.collect_mounts")
@patch("mac_volume_doctor.checks.dmg.open_processes")
def test_inspect_target_recommendation(open_processes, collect_mounts, collect_hdi_images) -> None:
    collect_mounts.return_value = {"/Volumes/Test": "/dev/disk9"}
    open_processes.return_value = [{"command": "python", "pid": "999"}]
    collect_hdi_images.return_value = {"/Volumes/Test": "/tmp/Test.dmg"}

    report = dmg.inspect_target("/Volumes/Test")
    assert report["check"] == "dmg"
    assert report["device"] == "/dev/disk9"
    assert report["hdi_image_path"] == "/tmp/Test.dmg"
    assert len(report["open_processes"]) == 1
    assert any("hdiutil detach" in line for line in report["recommendations"])


def test_main_inspect_json(capsys) -> None:
    with patch("mac_volume_doctor.checks.dmg.inspect_target") as inspect_target:
        inspect_target.return_value = {
            "check": "dmg",
            "mountpoint": "/Volumes/Test",
            "device": "/dev/disk9",
            "hdi_image_path": "/tmp/Test.dmg",
            "open_processes": [],
            "recommendations": [],
        }
        assert dmg.main(["--json", "inspect", "/Volumes/Test"]) == 0
    out = capsys.readouterr().out
    assert '"check": "dmg"' in out
    assert '"device": "/dev/disk9"' in out
