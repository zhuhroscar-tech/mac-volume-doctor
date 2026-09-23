import unittest
from unittest.mock import patch

from mac_volume_doctor import cli as root_cli
from mac_volume_doctor.checks import tm_snapshot


class SnapshotDoctorTest(unittest.TestCase):
    def test_parse_snapshot_list(self) -> None:
        text = """
Snapshots for volume group containing disk /:
com.apple.TimeMachine.2024-03-12-102045.local
com.apple.TimeMachine.2024-03-11-230900.local
"""
        ids = tm_snapshot.parse_snapshot_list(text)
        self.assertEqual(len(ids), 2)
        self.assertIn("com.apple.TimeMachine.2024-03-12-102045.local", ids)
        self.assertIn("com.apple.TimeMachine.2024-03-11-230900.local", ids)

    def test_parse_snapshot_list_handles_noise(self) -> None:
        ids = tm_snapshot.parse_snapshot_list("No snapshots")
        self.assertEqual(ids, [])

    def test_find_tmutil_status_running(self) -> None:
        status = """
{
 \tRunning = 1;
 \tPhase = \"Copying\";
 \tBytes = 2048;
}
"""
        parsed = tm_snapshot.find_tmutil_status(status)
        self.assertEqual(parsed["running"], True)
        self.assertEqual(parsed["phase"], '"Copying"')
        self.assertEqual(parsed["bytes"], 2048)

    @patch("mac_volume_doctor.checks.tm_snapshot.run_tmutil")
    def test_list_snapshots_error(self, run_tmutil) -> None:
        run_tmutil.return_value = (1, "", "tmutil: command not found")
        result = tm_snapshot.list_snapshots("/")
        self.assertIn("error", result)
        self.assertEqual(result["error"], "tmutil: command not found")

    @patch("mac_volume_doctor.checks.tm_snapshot.run_tmutil")
    def test_run_list_exit_code(self, run_tmutil) -> None:
        run_tmutil.return_value = (0, "com.apple.TimeMachine.2024-03-12-102045.local", "")
        self.assertEqual(tm_snapshot.run_list("/", as_json=False), 0)

    @patch("mac_volume_doctor.checks.tm_snapshot.run_tmutil")
    def test_health_report_uses_volume_in_recommendations(self, run_tmutil) -> None:
        run_tmutil.side_effect = [
            (0, "com.apple.TimeMachine.2024-03-12-102045.local", ""),
            (0, "Running = 0;\nPhase = \"Idle\";", ""),
        ]
        report = tm_snapshot.health_report("/Volumes/Data")
        self.assertEqual(report["check"], "tm-snapshot")
        self.assertEqual(report["snapshot_count"], 1)
        self.assertIn("tmutil listlocalsnapshotdates /Volumes/Data", "\n".join(report["recommendations"]))

    def test_root_dispatches_tm_snapshot_check(self) -> None:
        with patch("mac_volume_doctor.checks.tm_snapshot._run", return_value=0) as run:
            rc = root_cli.main(["tm-snapshot", "--volume", "/", "list"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[0].command, "list")
        self.assertEqual(run.call_args.args[0].volume, "/")


if __name__ == "__main__":
    unittest.main()
