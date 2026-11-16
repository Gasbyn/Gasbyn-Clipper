import unittest
from unittest import mock

import requests

from core import Reporter, _plain_video_filter, analysis_fingerprint, ask_llm, build_chunks, final_score
from schema import default_settings


class PipelineTests(unittest.TestCase):
    def test_vertical_fallback_filter_for_1080p_source(self):
        result = _plain_video_filter("short", 1920, 1080, 1080, 1920)
        self.assertEqual(result, "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,crop=608:1080:656:0,scale=1080:1920:flags=lanczos,unsharp=5:5:0.6:5:5:0.0,setsar=1")

    def test_zero_view_potential_is_not_replaced_with_fifty(self):
        cfg = default_settings()
        candidate = {"view_potential": 0, "hook": 50, "emotion": 50, "standalone": 50,
                     "payoff": 50, "humor": 50, "pacing": 50}
        self.assertEqual(final_score(candidate, cfg), 25.0)

    def test_ai_cache_fingerprint_changes_with_category(self):
        cfg = default_settings()
        history = {"videos": [{"title": "Short A", "views": 100, "views_per_day": 10.0}]}
        original = analysis_fingerprint(cfg, history)
        changed = default_settings()
        changed["clips"]["category"] = "Podcast"
        self.assertNotEqual(original, analysis_fingerprint(changed, history))
        self.assertEqual(original, analysis_fingerprint(cfg, history))

    def test_chunks_overlap_context(self):
        segments = [{"start": float(i), "end": float(i + 1), "text": "hello"}
                    for i in range(0, 4000, 10)]
        chunks = build_chunks(segments, 1800, overlap_seconds=90)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertGreater(chunks[1][0]["start"], 1600)
        self.assertLess(chunks[1][0]["start"], 1800)

    def test_http_500_is_not_retried(self):
        cfg = default_settings()
        response = requests.Response()
        response.status_code = 500
        error = requests.HTTPError("server error", response=response)
        rep = Reporter(log=lambda _message: None)
        with mock.patch("core._call_llm", side_effect=error) as call:
            with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                ask_llm(cfg, "system", "user", rep)
        self.assertEqual(call.call_count, 1)

    def test_transient_http_503_is_retried_once(self):
        cfg = default_settings()
        response = requests.Response()
        response.status_code = 503
        error = requests.HTTPError("temporarily unavailable", response=response)
        rep = Reporter(log=lambda _message: None)
        with mock.patch("core._call_llm", side_effect=[error, '{"ok": true}']) as call, \
             mock.patch("core.time.sleep"):
            self.assertEqual(ask_llm(cfg, "system", "user", rep), '{"ok": true}')
        self.assertEqual(call.call_count, 2)

    def test_render_does_not_silently_discard_loadout_on_failure(self):
        import tempfile
        from pathlib import Path
        import core

        cfg = default_settings()
        cfg["captions"]["enabled"] = False
        cfg["output"]["write_txt"] = False
        clip = {
            "start": 0.0, "end": 5.0, "src_size": [1920, 1080],
            "format": "short", "score": 50, "title": "test",
            "loadout": core.default_loadout("short", 1920, 1080),
        }
        failed = requests.Response()
        failed.status_code = 1
        proc = mock.Mock(returncode=1, stderr="synthetic ffmpeg failure", stdout="")

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("core._available_encoders", return_value={"libx264"}), \
             mock.patch("core.subprocess.run", return_value=proc) as run:
            with self.assertRaisesRegex(RuntimeError, "zachováním všech nastavených vrstev"):
                core.render_clip(Path("source.mp4"), [], clip, Path(tmp), cfg, 1,
                                 Reporter(log=lambda _message: None))
            self.assertEqual(run.call_count, 1)
            self.assertIn("-filter_complex", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
