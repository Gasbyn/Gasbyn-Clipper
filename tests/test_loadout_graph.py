import unittest

import core


class LoadoutGraphTests(unittest.TestCase):
    def test_every_view_is_normalized_before_crop(self):
        # Zdroj může v půlce VODu změnit rozlišení; crop musí vždy vidět pevnou velikost.
        lo = core.clean_loadout(core.preset_loadout("hra_webka", 1920, 1080))
        graph = core.loadout_graph(lo, 1080, 1920, 1920, 1080, 10.0, [], None)
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", graph)
        self.assertIn("pad=1920:1080", graph)
        self.assertIn("split=2[srcv0][srcv1]", graph)
        self.assertNotIn("[0:v]setpts", graph)

    def test_single_view_has_no_split(self):
        lo = core.clean_loadout(core.preset_loadout("stred", 1920, 1080))
        graph = core.loadout_graph(lo, 1080, 1920, 1920, 1080, 10.0, [], None)
        self.assertIn("[srcv0]crop=", graph)
        self.assertNotIn("split=", graph)

    def test_clean_loadout_clamps_layer_rectangles(self):
        lo = core.clean_loadout({
            "views": [{
                "crop": [-0.5, 0.2, 1.8, 0.8],
                "place": [0.9, -0.2, 0.5, 0.5],
                "anim": "not-a-real-effect",
                "anim_seconds": float("nan"),
            }],
            "photos": [{
                "path": "overlay.png",
                "place": [0.8, 0.8, 0.5, 0.5],
                "start": -10,
                "end": 5,
            }],
        })
        self.assertEqual(lo["views"][0]["crop"], [0.0, 0.2, 1.0, 0.8])
        self.assertEqual(lo["views"][0]["place"], [0.5, 0.0, 0.5, 0.5])
        self.assertEqual(lo["views"][0]["anim"], "none")
        self.assertEqual(lo["views"][0]["anim_seconds"], 0.6)
        self.assertEqual(lo["photos"][0]["place"], [0.5, 0.5, 0.5, 0.5])
        self.assertEqual(lo["photos"][0]["start"], 0.0)

    def test_loadout_graph_rejects_missing_video_layers(self):
        lo = core.clean_loadout({"views": [], "photos": []})
        with self.assertRaisesRegex(ValueError, "žádný video záběr"):
            core.loadout_graph(lo, 1080, 1920, 1920, 1080, 10.0, [], None)

    def test_presets_give_valid_crops(self):
        for key in core.LOADOUT_PRESETS:
            lo = core.preset_loadout(key, 1920, 1080)
            for v in lo["views"]:
                x, y, w, h = v["crop"]
                self.assertTrue(0 <= x and 0 <= y and x + w <= 1.0001 and y + h <= 1.0001, (key, v["crop"]))


if __name__ == "__main__":
    unittest.main()
