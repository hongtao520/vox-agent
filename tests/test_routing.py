from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fish_audio
import codex_parallel
import keyframe_fallback
import keyframes
import runtime
from credentials import REQUIRED_CREDENTIALS


class RuntimeRoutingTests(unittest.TestCase):
    def test_auto_uses_codex_inside_codex(self):
        with mock.patch.dict(os.environ, {"VOX_AGENT_RUNTIME": "codex"}, clear=False):
            self.assertEqual(runtime.resolve_image_provider("auto"), "codex")

    def test_auto_uses_liblib_outside_codex(self):
        with mock.patch.dict(os.environ, {"VOX_AGENT_RUNTIME": "external"}, clear=False):
            self.assertEqual(runtime.resolve_image_provider("auto"), "liblib")

    def test_default_voice_is_selected_history_voice(self):
        self.assertEqual(fish_audio.DEFAULT_MODEL, "s2.1-pro-free")
        self.assertEqual(fish_audio.DEFAULT_VOICE_NAME, "历史故事·清晰")
        self.assertEqual(fish_audio.DEFAULT_REFERENCE_ID, "6fc59d2b56cf402eb572934114c8d8aa")

    def test_first_use_requires_exactly_three_credentials(self):
        self.assertEqual(
            [item[0] for item in REQUIRED_CREDENTIALS],
            ["LIBLIB_ACCESS_KEY", "LIBLIB_SECRET_KEY", "FISH_API_KEY"],
        )

    def test_parallel_contract_requests_one_agent_per_image(self):
        contract = codex_parallel.execution_contract(7)
        self.assertEqual(contract["strategy"], "one_subagent_per_image")
        self.assertEqual(contract["requested_subagents"], 7)
        self.assertEqual(contract["max_images_per_subagent"], 1)


class ProjectFallbackTests(unittest.TestCase):
    @staticmethod
    def _project_doc():
        return {
            "aspect": "16:9",
            "style": "collage",
            "image_provider": "auto",
            "image_fallback_provider": "liblib",
            "beats": [
                {"id": 1, "title_cn": "一", "title_en": "ONE", "scene": "scene one"},
                {"id": 2, "title_cn": "二", "title_en": "TWO", "scene": "scene two"},
            ],
        }

    def test_non_codex_generates_the_whole_batch_with_liblib(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "beats.json").write_text(
                json.dumps(self._project_doc()), encoding="utf-8"
            )

            class FakeProvider:
                def download(self, _url, destination):
                    Path(destination).write_bytes(b"liblib")

            with mock.patch.object(keyframes, "require_setup"), \
                 mock.patch.object(keyframes, "resolve_image_provider", return_value="liblib"), \
                 mock.patch.object(keyframes, "get_provider", return_value=FakeProvider()), \
                 mock.patch.object(keyframes, "normalize_aspect"), \
                 mock.patch.object(keyframes, "run_jobs",
                                   return_value={"1": "https://example/1", "2": "https://example/2"}):
                keyframes.run(str(project))

            result = json.loads((project / "beats.json").read_text(encoding="utf-8"))
            self.assertEqual(result["resolved_image_provider"], "liblib")
            self.assertEqual(result["keyframe_batch_provider"], "liblib")
            self.assertTrue(all(
                beat["keyframe_source"]["provider"] == "liblib"
                for beat in result["beats"]
            ))

    def test_codex_manifest_scales_subagents_to_image_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "beats.json").write_text(
                json.dumps(self._project_doc()), encoding="utf-8"
            )
            with mock.patch.object(keyframes, "require_setup"), \
                 mock.patch.object(keyframes, "resolve_image_provider", return_value="codex"):
                keyframes.run(str(project))

            manifest = json.loads(
                (project / "keyframes" / "gpt-image-2-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["items"]), 2)
            self.assertEqual(manifest["execution"]["requested_subagents"], 2)
            self.assertEqual(manifest["execution"]["max_images_per_subagent"], 1)
            self.assertIn("one subagent per image", manifest["instruction"])

    def test_all_replaces_every_codex_keyframe_with_liblib(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            codex_a = project / "codex-a.png"
            codex_b = project / "codex-b.png"
            codex_a.write_bytes(b"codex-a")
            codex_b.write_bytes(b"codex-b")
            doc = self._project_doc()
            doc["beats"][0].update(
                keyframe_path=str(codex_a), keyframe_source={"provider": "codex"}
            )
            doc["beats"][1].update(
                keyframe_path=str(codex_b), keyframe_source={"provider": "codex"}
            )
            (project / "beats.json").write_text(json.dumps(doc), encoding="utf-8")

            class FakeProvider:
                def download(self, _url, destination):
                    Path(destination).write_bytes(b"liblib")

            with mock.patch.object(keyframe_fallback, "require_setup"), \
                 mock.patch.object(keyframe_fallback, "get_provider", return_value=FakeProvider()), \
                 mock.patch.object(keyframe_fallback, "normalize_aspect"), \
                 mock.patch.object(keyframe_fallback, "run_jobs",
                                   return_value={"1": "https://example/1", "2": "https://example/2"}):
                keyframe_fallback.run(str(project), replace_all=True)

            result = json.loads((project / "beats.json").read_text(encoding="utf-8"))
            self.assertEqual(result["keyframe_batch_provider"], "liblib")
            self.assertTrue(result["codex_batch_failed"])
            for beat in result["beats"]:
                self.assertEqual(beat["keyframe_source"]["provider"], "liblib")
                self.assertEqual(beat["keyframe_source"]["reason"], "codex_batch_failed")
                self.assertTrue(beat["keyframe_path"].endswith("_liblib.png"))


if __name__ == "__main__":
    unittest.main()
