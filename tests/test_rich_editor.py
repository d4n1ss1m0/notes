import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from notes_app.rich_editor import RichEditor
from notes_app.editor_document import image_data, make_image, make_table, table_data


class FakeCheckButton:
    def __init__(self, active):
        self.active = active
        self.callbacks = []

    def get_active(self):
        return self.active

    def set_active(self, active):
        if self.active != active:
            self.active = active
            for callback in self.callbacks:
                callback(self)

    def set_sensitive(self, _value):
        pass

    def connect(self, _signal, callback):
        self.callbacks.append(callback)


def editor_without_window():
    """Exercise the text buffer without creating a display-dependent widget."""
    editor = RichEditor.__new__(RichEditor)
    editor.buffer = Gtk.TextBuffer()
    editor.buffer.set_enable_undo(True)
    editor._loading = False
    editor._pending_styles = {}
    editor._task_buttons = {}
    editor._table_widgets = {}
    editor._image_widgets = {}
    editor.attachment_path = lambda ident: Path("/tmp") / f"{ident}.png"
    editor.changed = lambda: None
    editor.heading_tags = {name: editor.buffer.create_tag(name, scale=1.2)
                           for name in ("heading1", "heading2", "heading3")}
    editor.view = SimpleNamespace(grab_focus=lambda: None, get_editable=lambda: True,
                                  get_width=lambda: 520, get_left_margin=lambda: 30,
                                  get_right_margin=lambda: 30,
                                  add_child_at_anchor=lambda _button, _anchor: None,
                                  remove=lambda _button: None)
    editor._make_task_button = lambda checked: FakeCheckButton(checked)
    editor.buffer.connect("changed", editor._on_changed)
    return editor


class RichEditorTest(unittest.TestCase):
    def test_image_survives_editor_round_trips(self):
        class FakeImageWidget:
            def __init__(self, node, _path, _changed, _delete):
                self.node = node

            def to_node(self):
                return self.node

            def set_sensitive(self, _value):
                pass

            def set_available_width(self, _width):
                pass

        image = make_image("a" * 32, 275)
        document = {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "До"}]},
            image,
            {"type": "paragraph", "content": [{"type": "text", "text": "После"}]},
        ]}
        editor = editor_without_window()
        with patch("notes_app.rich_editor.ImageWidget", FakeImageWidget):
            editor.load(json.dumps(document))
            body, snapshot = editor.snapshot()
            self.assertEqual(body, "До\n\nПосле")
            self.assertEqual(image_data(json.loads(snapshot)["content"][1]), ("a" * 32, 275))
            editor.load(snapshot)
            self.assertEqual(editor.snapshot(), (body, snapshot))
            editor.buffer.insert(editor.buffer.get_iter_at_line(1)[1], "Подпись ")
            nodes = json.loads(editor.snapshot()[1])["content"]
            self.assertEqual([node["type"] for node in nodes],
                             ["paragraph", "paragraph", "image", "paragraph"])
            self.assertEqual(nodes[1]["content"][0]["text"], "Подпись ")

    def test_insert_image_keeps_surrounding_text(self):
        class FakeImageWidget:
            def __init__(self, node, _path, _changed, _delete):
                self.node = node

            def to_node(self):
                return self.node

            def set_sensitive(self, _value):
                pass

            def set_available_width(self, _width):
                pass

        editor = editor_without_window()
        editor.buffer.set_text("До\nПосле")
        editor.buffer.place_cursor(editor.buffer.get_start_iter())
        with patch("notes_app.rich_editor.ImageWidget", FakeImageWidget):
            editor.insert_image("b" * 32, 280)
        nodes = json.loads(editor.snapshot()[1])["content"]
        self.assertEqual([node["type"] for node in nodes],
                         ["paragraph", "image", "paragraph"])
        self.assertEqual(image_data(nodes[1]), ("b" * 32, 280))

    def test_table_survives_editor_round_trips_with_column_widths(self):
        class FakeTableWidget:
            def __init__(self, node, _changed, _delete):
                self.node = node

            def to_node(self):
                return self.node

            def set_sensitive(self, _value):
                pass

            def set_available_width(self, _width):
                pass

        table = make_table([["Имя", "Количество"], ["Чай", "2"]], [140, 220])
        document = {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Покупки"}]},
            table,
            {"type": "paragraph", "content": [{"type": "text", "text": "Готово"}]},
        ]}
        editor = editor_without_window()
        with patch("notes_app.rich_editor.TableWidget", FakeTableWidget):
            editor.load(json.dumps(document))
            body, snapshot = editor.snapshot()
            self.assertIn("Чай\t2", body)
            self.assertEqual(table_data(json.loads(snapshot)["content"][1]),
                             ([["Имя", "Количество"], ["Чай", "2"]], [140, 220]))
            for _ in range(3):
                editor.load(snapshot)
                self.assertEqual(editor.snapshot(), (body, snapshot))

    def test_insert_table_keeps_text_before_and_after_it(self):
        class FakeTableWidget:
            def __init__(self, node, _changed, _delete):
                self.node = node

            def to_node(self):
                return self.node

            def set_sensitive(self, _value):
                pass

            def set_available_width(self, _width):
                pass

        editor = editor_without_window()
        editor.buffer.set_text("До\nПосле")
        editor.buffer.place_cursor(editor.buffer.get_start_iter())
        with patch("notes_app.rich_editor.TableWidget", FakeTableWidget):
            editor.insert_table()
        nodes = json.loads(editor.snapshot()[1])["content"]
        self.assertEqual([node["type"] for node in nodes],
                         ["paragraph", "table", "paragraph"])
        self.assertEqual(nodes[0]["content"][0]["text"], "До")
        self.assertEqual(nodes[2]["content"][0]["text"], "После")

    def test_selected_lines_become_sequential_numbered_list(self):
        editor = editor_without_window()
        editor.buffer.set_text("Первый\nВторой\nТретий")
        editor.buffer.select_range(editor.buffer.get_start_iter(), editor.buffer.get_end_iter())
        editor.set_kind("number")
        start, end = editor.buffer.get_bounds()
        self.assertEqual(editor.buffer.get_text(start, end, True),
                         "1. Первый\n2. Второй\n3. Третий")

    def test_empty_lines_do_not_absorb_or_duplicate_following_text(self):
        editor = editor_without_window()
        editor.buffer.set_text("Первый\n\nВторой\n")
        self.assertEqual([editor._line_text(line) for line in range(editor.buffer.get_line_count())],
                         ["Первый", "", "Второй", ""])
        snapshot = editor.snapshot()
        for _ in range(5):
            editor.load(snapshot[1], snapshot[0])
            self.assertEqual(editor.snapshot(), snapshot)

    def test_heading_keeps_style_when_typing_and_enter_starts_paragraph(self):
        editor = editor_without_window()
        editor.buffer.set_text("План")
        editor.set_kind("heading1")
        editor.buffer.insert(editor.buffer.get_start_iter(), "Новый ")
        self.assertEqual(json.loads(editor.snapshot()[1])["content"][0]["type"], "heading")
        editor.buffer.place_cursor(editor.buffer.get_end_iter())
        self.assertTrue(editor._on_key_pressed(None, Gdk.KEY_Return, 0, 0))
        self.assertEqual([node["type"] for node in json.loads(editor.snapshot()[1])["content"]],
                         ["heading", "paragraph"])

    def test_task_can_be_completed_and_enter_continues_then_exits_list(self):
        editor = editor_without_window()
        editor.buffer.set_text("Купить продукты")
        editor.set_kind("todo")
        editor.toggle_task()
        editor.buffer.place_cursor(editor.buffer.get_end_iter())
        self.assertTrue(editor._on_key_pressed(None, Gdk.KEY_Return, 0, 0))
        lines = json.loads(editor.snapshot()[1])["content"][0]["content"]
        self.assertEqual([item["attrs"]["checked"] for item in lines], [True, False])
        reopened = editor_without_window()
        reopened.load(editor.snapshot()[1])
        self.assertEqual([item["attrs"]["checked"] for item in
                          json.loads(reopened.snapshot()[1])["content"][0]["content"]], [True, False])
        self.assertTrue(editor._on_key_pressed(None, Gdk.KEY_Return, 0, 0))
        self.assertEqual(json.loads(editor.snapshot()[1])["content"][-1]["type"], "paragraph")


if __name__ == "__main__":
    unittest.main()
