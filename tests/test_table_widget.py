import unittest

from notes_app.table_widget import table_viewport_width


class TableViewportTest(unittest.TestCase):
    def test_table_stays_inside_note_and_scrolls_when_needed(self):
        self.assertEqual(table_viewport_width([160, 160], 550), 322)
        self.assertEqual(table_viewport_width([160, 240, 160], 420), 420)
        self.assertEqual(table_viewport_width([160, 160], 120), 120)


if __name__ == "__main__":
    unittest.main()
