import json
import tempfile
import unittest
from pathlib import Path

from ksh_gpu_agent import collect_runs


class CollectRunsTest(unittest.TestCase):
    def test_meta_json_enriches_index_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "demo" / "20260918T010203Z_gpu1_demo"
            run_dir.mkdir(parents=True)
            (run_dir / "README.md").write_text("# run\n")
            (run_dir / "meta.json").write_text(json.dumps({
                "run_id": run_dir.name,
                "project": "demo",
                "goal": "test the metadata bridge",
                "architecture": "Encoder -> Decoder",
                "dataset": "synthetic/v1",
                "gpu_ids": ["0", "1"],
                "status": "completed",
                "started_at": "2026-09-18T01:02:03Z",
                "updated_at": "2026-09-18T01:03:03Z",
                "ended_at": "2026-09-18T01:03:03Z",
                "exit_code": 0,
            }))
            (root / "INDEX.md").write_text(
                "# 실험 목록\n\n"
                "| 실험 ID | 목적 | 기준 실험 | 상태 | GPU | 마지막 확인 시각 | 결과 경로 |\n"
                "|---|---|---|---|---|---|---|\n"
                f"| {run_dir.name} | old \\| escaped | — | running | 0 | old | [기록](demo/{run_dir.name}/README.md) |\n"
            )

            runs = collect_runs(str(root / "INDEX.md"))

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["purpose"], "test the metadata bridge")
            self.assertEqual(runs[0]["status"], "completed")
            self.assertEqual(runs[0]["gpu_ids"], ["0", "1"])
            self.assertEqual(runs[0]["summary"]["architecture"], "Encoder -> Decoder")
            self.assertEqual(runs[0]["summary"]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
