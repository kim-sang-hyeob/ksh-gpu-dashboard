import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from vessl_autostart import parse_workspace_ids, process, request_start


class AutostartTests(unittest.TestCase):
    def test_parse_numeric_ids_and_deduplicate(self):
        self.assertEqual(parse_workspace_ids("123, 456,123"), ["123", "456"])

    def test_rejects_non_numeric_selectors(self):
        with self.assertRaises(ValueError):
            parse_workspace_ids("owner/name")

    def test_only_stopped_workspaces_start(self):
        starter, configurator = Mock(), Mock()
        stopped, failures = process(
            {"1": "running", "2": "stopped", "3": "pending"},
            starter,
            configurator,
        )
        self.assertEqual((stopped, failures), (1, 0))
        configurator.assert_called_once_with("2")
        starter.assert_called_once_with("2")

    def test_dry_run_never_starts(self):
        starter, configurator = Mock(), Mock()
        self.assertEqual(process({"1": "stopped"}, starter, configurator, dry_run=True), (1, 0))
        configurator.assert_not_called()
        starter.assert_not_called()

    def test_one_failure_does_not_block_another_start(self):
        calls = []

        def configure(workspace_id):
            calls.append(("configure", workspace_id))
            if workspace_id == "1":
                raise RuntimeError("private response")

        def start(workspace_id):
            calls.append(("start", workspace_id))

        self.assertEqual(process({"1": "stopped", "2": "stopped"}, start, configure), (2, 1))
        self.assertEqual(calls, [("configure", "1"), ("configure", "2"), ("start", "2")])

    @patch("vessl_autostart.subprocess.run")
    def test_start_hides_cli_output(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "private", "private")
        with patch.dict(os.environ, {"TOKEN": "secret"}):
            request_start("123")
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.args[0], ["vessl", "workspace", "start", "123"])


if __name__ == "__main__":
    unittest.main()
