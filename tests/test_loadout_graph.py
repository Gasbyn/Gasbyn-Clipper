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

    def test_presets_give_valid_crops(self):
        for key in core.LOADOUT_PRESETS:
            lo = core.preset_loadout(key, 1920, 1080)
            for v in lo["views"]:
                x, y, w, h = v["crop"]
                self.assertTrue(0 <= x and 0 <= y and x + w <= 1.0001 and y + h <= 1.0001, (key, v["crop"]))


if __name__ == "__main__":
    unittest.main()
