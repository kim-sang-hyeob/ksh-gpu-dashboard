import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("ksh_run.py")


class KshRunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env["KSH_RUNS_ROOT"] = str(self.root / "runs")
        self.env["KSH_SMOKE_ROOT"] = str(self.root / "smoke")
        self.env["KSH_SERVER_NAME"] = "gpu-test"

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def one_run(self):
        paths = list((self.root / "runs" / "demo").iterdir())
        self.assertEqual(len(paths), 1)
        return paths[0]

    def test_formal_success_creates_and_finishes_record(self):
        result = self.invoke(
            "--project", "demo",
            "--gpu", "0,1",
            "--goal", "verify launcher",
            "--architecture", "Encoder -> DiT -> Decoder",
            "--dataset", "synthetic/v1",
            "--wait",
            "--",
            sys.executable,
            "-c",
            "print('hello-run')",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.one_run()
        meta = json.loads((run_dir / "meta.json").read_text())
        self.assertEqual(meta["status"], "completed")
        self.assertEqual(meta["exit_code"], 0)
        self.assertEqual(meta["gpu_ids"], ["0", "1"])
        self.assertIn("hello-run", (run_dir / "logs" / "stdout.log").read_text())
        index = (self.root / "runs" / "INDEX.md").read_text()
        self.assertIn("verify launcher", index)
        self.assertIn("completed", index)
        self.assertLessEqual((run_dir / "meta.json").stat().st_size, 4096)

    def test_formal_failure_is_recorded_and_returned(self):
        result = self.invoke(
            "--project", "demo",
            "--gpu", "cpu",
            "--goal", "expected failure",
            "--wait",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(3)",
        )
        self.assertEqual(result.returncode, 3)
        meta = json.loads((self.one_run() / "meta.json").read_text())
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["exit_code"], 3)

    def test_smoke_directory_is_always_removed(self):
        result = self.invoke(
            "--project", "demo",
            "--gpu", "cpu",
            "--goal", "disposable check",
            "--smoke",
            "--",
            sys.executable,
            "-c",
            "from pathlib import Path; Path('temporary.bin').write_bytes(b'x')",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "smoke").is_dir())
        self.assertEqual(list((self.root / "smoke").iterdir()), [])
        self.assertFalse((self.root / "runs").exists())

    def test_rejects_unsafe_project_name(self):
        result = self.invoke(
            "--project", "../escape",
            "--goal", "bad path",
            "--",
            sys.executable,
            "-c",
            "pass",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("project must match", result.stderr)


if __name__ == "__main__":
    unittest.main()
