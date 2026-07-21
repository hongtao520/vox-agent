import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import music


class _AudioResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class MusicTests(unittest.TestCase):
    def test_generates_and_registers_local_bgm(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            beats = {
                "project": "qin-test",
                "topic": "秦始皇统一六国",
                "beats": [{"id": 1, "feel": "tense", "shots": [{"dur": 5}, {"dur": 5}]}],
                "music": {"provider": "ace-step", "poll_s": 1},
            }
            (project / "beats.json").write_text(json.dumps(beats), encoding="utf-8")
            responses = [
                {"code": 200, "data": {"status": "ok"}},
                {"code": 200, "data": {"task_id": "task-1"}},
                {"code": 200, "data": [{"status": 1, "result": json.dumps([{"file": "/v1/audio?path=x"}])}]},
            ]
            with patch.object(music, "_request", side_effect=responses), patch.object(
                music, "_open", return_value=_AudioResponse(b"RIFF-test-audio")
            ):
                output = music.generate(str(project))
            self.assertEqual(Path(output), (project / "audio" / "bgm.wav").resolve())
            self.assertTrue(Path(output).is_file())
            saved = json.loads((project / "beats.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["bgm_path"], output)
            self.assertEqual(saved["music"]["provider"], "ace-step")

    def test_duration_uses_all_shots_and_has_ten_second_floor(self):
        self.assertEqual(music._project_duration({"beats": [{"shots": [{"dur": 3}, {"dur": 4}]}]}), 10)
        self.assertEqual(music._project_duration({"beats": [{"shots": [{"dur": 8}, {"dur": 7}]}]}), 15)


if __name__ == "__main__":
    unittest.main()
