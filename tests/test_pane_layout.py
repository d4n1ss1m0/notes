import json
import tempfile
import unittest
from pathlib import Path

from notes_app.pane_layout import PaneLayout, bounded_width


class PaneLayoutTest(unittest.TestCase):
    def test_tag_section_visibility_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.json"
            layout = PaneLayout(path)
            self.assertTrue(layout.tags_expanded)
            layout.tags_expanded = False
            layout.save()
            self.assertFalse(PaneLayout(path).tags_expanded)
            self.assertEqual(PaneLayout(path).widths, layout.widths)

    def test_columns_have_sensible_limits(self):
        self.assertEqual(bounded_width("folders", 40), 180)
        self.assertEqual(bounded_width("folders", 900), 380)
        self.assertEqual(bounded_width("notes", 100), 250)
        self.assertEqual(bounded_width("notes", 900), 520)

    def test_widths_survive_reopen_and_invalid_values_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes" / "window.json"
            layout = PaneLayout(path)
            layout.set_width("folders", 315)
            layout.set_width("notes", 410)
            layout.save()
            self.assertEqual(PaneLayout(path).widths, {"folders": 315, "notes": 410})
            path.write_text(json.dumps({"folders": -2, "notes": "wide"}), encoding="utf-8")
            self.assertEqual(PaneLayout(path).widths, {"folders": 180, "notes": 300})


if __name__ == "__main__":
    unittest.main()
