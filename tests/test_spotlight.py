import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_volume_doctor import cli as root_cli
from mac_volume_doctor.checks import spotlight


class SpotlightParsingTests(unittest.TestCase):
    def test_parse_lsof_output_dedups_and_reasons(self) -> None:
        sample = """
COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
mds       111 root   txt  REG  1,1    0t0   100 /Volumes/DISK/.fseventsd
mds       111 root   txt  REG  1,1    0t0   100 /Volumes/DISK/.fseventsd
finder    222 oscar  cwd  DIR  1,1    0t0   200 /Volumes/DISK
""".strip()
        blockers = spotlight.parse_lsof_output(sample)
        self.assertEqual(len(blockers), 2)
        self.assertEqual(blockers[0].as_dict()["likely_reason"], "Spotlight indexing / metadata")
        self.assertEqual(blockers[1].as_dict()["likely_reason"], "Finder background file-manager hold")

    def test_parse_spotlight_status(self) -> None:
        self.assertTrue(spotlight.parse_spotlight_status("Indexing enabled."))
        self.assertFalse(spotlight.parse_spotlight_status("Indexing disabled."))
        self.assertIsNone(spotlight.parse_spotlight_status("Could not find"))


class SpotlightReportTests(unittest.TestCase):
    @staticmethod
    def _fake_completed(cmd, *, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    def test_render_report_no_blockers(self) -> None:
        report = {
            "check": "spotlight",
            "target": "/Volumes/Test",
            "disk_info": {"Device Identifier": "disk5s1", "Mount Point": "/Volumes/Test"},
            "blockers": [],
            "spotlight_indexing": None,
            "spotlight_raw": [],
        }
        text = spotlight.render_report(report)
        self.assertIn("no open handles", text)
        self.assertIn("mac-volume-doctor spotlight report", text)

    def test_run_diagnostic_with_stubbed_tools(self) -> None:
        target = Path("/tmp/mac-volume-doctor-spotlight-test").resolve()
        target.mkdir(exist_ok=True)

        def fake_runner(cmd, timeout=10.0, **kwargs):
            if cmd[0] == "lsof" and "+D" in cmd:
                return self._fake_completed(
                    cmd=cmd,
                    returncode=0,
                    stdout="COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nmds 111 root txt REG 1,1 0t0 1 /Volumes/Test\n",
                )
            if cmd[0] == "mdutil":
                return self._fake_completed(cmd=cmd, returncode=0, stdout="Indexing disabled.")
            if cmd[0] == "diskutil":
                return self._fake_completed(
                    cmd=cmd,
                    returncode=0,
                    stdout="Device Identifier: disk9s1\nMount Point: /Volumes/Drive",
                )
            raise AssertionError(f"Unexpected cmd: {cmd}")

        with patch("mac_volume_doctor.checks.spotlight.run_command", side_effect=fake_runner):
            report = spotlight.run_diagnostic(str(target))

        self.assertEqual(report["check"], "spotlight")
        self.assertEqual(report["target"], str(target))
        self.assertFalse(report["spotlight_indexing"])
        self.assertEqual(len(report["blockers"]), 1)
        self.assertEqual(report["blockers"][0]["command"], "mds")


class SpotlightCliSmokeTests(unittest.TestCase):
    def test_json_output_smoke(self) -> None:
        with patch("mac_volume_doctor.checks.spotlight.run_diagnostic") as run_diag:
            run_diag.return_value = {
                "check": "spotlight",
                "target": "/Volumes/Test",
                "disk_info": {"Device Identifier": "disk9s1", "Mount Point": "/Volumes/Test"},
                "blockers": [],
                "spotlight_indexing": True,
                "spotlight_raw": [],
            }
            with patch("builtins.print"):
                rc = spotlight._run(spotlight.argparse.Namespace(target="/Volumes/Test", json=True, spotlight=None, no_prompt=False))

        self.assertEqual(rc, 0)

    def test_status_smoke(self) -> None:
        with patch("mac_volume_doctor.checks.spotlight.toggle_spotlight", return_value=0) as toggle, patch("mac_volume_doctor.checks.spotlight.run_diagnostic") as run_diag:
            run_diag.return_value = {
                "check": "spotlight",
                "target": "/Volumes/Test",
                "disk_info": {"Device Identifier": "disk9s1", "Mount Point": "/Volumes/Test"},
                "blockers": [],
                "spotlight_indexing": True,
                "spotlight_raw": ["Indexing enabled."],
            }
            with patch("builtins.print"):
                rc = spotlight._run(spotlight.argparse.Namespace(target="/Volumes/Test", json=False, spotlight="status", no_prompt=False))

        self.assertEqual(toggle.call_count, 1)
        self.assertEqual(rc, 0)

    def test_root_dispatches_spotlight_check(self) -> None:
        with patch("mac_volume_doctor.checks.spotlight._run", return_value=0) as run:
            rc = root_cli.main(["spotlight", "/Volumes/Test"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[0].target, "/Volumes/Test")


if __name__ == "__main__":
    unittest.main()
