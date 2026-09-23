import unittest
from unittest import mock

from mac_volume_doctor import cli as root_cli
from mac_volume_doctor.checks import tm


class TMUtilParsingTests(unittest.TestCase):
    def test_parse_lsof_output_keeps_real_blockers_and_skips_banner(self) -> None:
        raw = """
lsof: WARNING: can't stat() lsof? output
COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
mds      111 root   txt  REG  1,1  0t0 111 /Volumes/TM/.Spotlight-V100
finder   222 oscar  cwd  DIR  1,1  0t0 222 /Volumes/TM
systemmigrationd 333 root  txt  REG  1,1 0t0 333 /System/Library/systemmigrationd
""".strip()
        blockers = tm.parse_lsof_output(raw)
        self.assertEqual(len(blockers), 3)
        self.assertEqual(blockers[0].command, "mds")
        self.assertEqual(blockers[1].reason, "current working directory")

    def test_parse_tmutil_status(self) -> None:
        sample = '{\n    "Running" = 1;\n    "CurrentPhase" = "BackupWorking";\n}'
        parsed = tm.parse_tmutil_status(sample)
        self.assertTrue(parsed["running"])
        self.assertEqual(parsed["currentPhase"], "BackupWorking")

    def test_parse_tmutil_destination_mounts(self) -> None:
        raw = """
Destination ID: 1111
Kind: Local
Mount Point: /Volumes/TimeMachine
Mount Point: /Volumes/Other
""".strip()
        mounts = tm.parse_tmutil_destinationinfo(raw)
        self.assertEqual(mounts, ["/Volumes/TimeMachine", "/Volumes/Other"])


class TMReportTests(unittest.TestCase):
    @staticmethod
    def _complete(cmd, *, stdout="", stderr="", returncode=0):
        return tm.subprocess.CompletedProcess(cmd, returncode=returncode, stdout=stdout, stderr=stderr)

    def test_run_diagnostic_smoke(self) -> None:
        target = "/Volumes/TimeMachine"

        def fake_runner(cmd):
            if cmd[:2] == ["lsof", "+D"]:
                return self._complete(cmd, stdout="COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nmds 111 root txt REG 1,1 0t0 1 /Volumes/TimeMachine/.Spotlight-V100\n")
            if cmd == ["tmutil", "status"]:
                return self._complete(cmd, stdout="\"Running\" = 1;\n\"CurrentPhase\" = \"Running\";")
            if cmd == ["tmutil", "destinationinfo"]:
                return self._complete(cmd, stdout="Mount Point: /Volumes/TimeMachine\n")
            if cmd[:2] == ["diskutil", "info"]:
                return self._complete(cmd, stdout="Volume Name: TimeMachine\nMount Point: /Volumes/TimeMachine\n")
            raise AssertionError(f"unexpected command {cmd}")

        report = tm.run_diagnostic(target, command_runner=fake_runner)
        self.assertEqual(report["check"], "tm")
        self.assertEqual(report["target"], target)
        self.assertTrue(report["timeMachine"]["isConfiguredTarget"])  # type: ignore[index]
        self.assertEqual(len(report["blockers"]), 1)  # type: ignore[index]
        self.assertTrue(report["timeMachine"]["status"]["running"])  # type: ignore[index]

    def test_json_render(self) -> None:
        target = "/Volumes/Test"
        report = {
            "check": "tm",
            "target": target,
            "mountPoint": target,
            "blockers": [],
            "timeMachine": {
                "status": {"running": False, "currentPhase": "BackupNotRunning"},
                "isConfiguredTarget": False,
                "destinationMounts": [],
            },
            "diskInfo": {"Volume Name": "Test", "Mount Point": target},
            "suggestions": ["No active Time Machine or open-handle blockers detected."],
        }
        namespace = tm.argparse.Namespace(target=target, json=True, stop_backup=False, wait=0)
        with mock.patch("mac_volume_doctor.checks.tm.run_diagnostic", return_value=report), mock.patch("builtins.print"):
            rc = tm._run(namespace)
        self.assertEqual(rc, 0)


class RootCLITests(unittest.TestCase):
    def test_root_dispatches_tm_check(self) -> None:
        with mock.patch("mac_volume_doctor.checks.tm._run", return_value=0) as run:
            rc = root_cli.main(["tm", "/Volumes/Test"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[0].target, "/Volumes/Test")

    def test_planned_check_reports_not_migrated(self) -> None:
        with mock.patch("builtins.print") as printed:
            rc = root_cli.main(["dmg"])
        self.assertEqual(rc, 64)
        self.assertIn("not migrated yet", printed.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
