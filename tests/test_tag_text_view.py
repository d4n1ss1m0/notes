import unittest
from types import SimpleNamespace

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from notes_app.tag_text_view import TagTextView, tag_rectangles, tag_spans


class TagTextViewTest(unittest.TestCase):
    def test_highlighting_updates_without_changing_text_or_undo(self):
        buffer = Gtk.TextBuffer()
        buffer.set_enable_undo(True)
        view = SimpleNamespace(_tag_spans=[], queue_draw=lambda: None)
        buffer.connect("changed", lambda b: TagTextView._update_tags(view, b))
        buffer.set_text("План #Работа, #дом")
        self.assertEqual(view._tag_spans, [(5, 12), (14, 18)])
        buffer.begin_user_action()
        buffer.delete(buffer.get_iter_at_offset(5), buffer.get_iter_at_offset(6))
        buffer.end_user_action()
        self.assertEqual(view._tag_spans, [(13, 17)])
        buffer.undo()
        self.assertEqual(view._tag_spans, [(5, 12), (14, 18)])
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), True), "План #Работа, #дом")

    def test_offsets_include_embedded_anchors_and_ignore_url_fragments(self):
        text = "\ufffc #работа https://example.org/#fragment # ##"
        spans = tag_spans(text)
        self.assertEqual([text[start:end] for start, end in spans], ["#работа"])
        self.assertEqual(spans[0][0], 2)

    def test_wrapped_tag_has_one_rounded_background_per_visual_row(self):
        boxes = [(20, 10, 8, 18), (28, 10, 8, 18), (0, 28, 8, 18)]
        buffer = Gtk.TextBuffer()
        buffer.set_text("#ab")
        view = SimpleNamespace(
            get_buffer=lambda: buffer,
            get_iter_location=lambda it: SimpleNamespace(
                **dict(zip(("x", "y", "width", "height"), boxes[it.get_offset()])))
        )
        self.assertEqual(tag_rectangles(view, 0, 3), [(18, 10, 20, 18), (-2, 28, 12, 18)])
        boxes[:] = [(20, 10, -8, 18), (12, 10, -8, 18), (4, 10, -4, 18)]
        self.assertEqual(tag_rectangles(view, 0, 3), [(-2, 10, 24, 18)])


if __name__ == "__main__":
    unittest.main()
