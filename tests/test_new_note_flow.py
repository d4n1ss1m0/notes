import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

from notes_app.storage import NotesStore
from notes_app.ui import NotesWindow, TRASH


class SearchStub:
    def __init__(self, text):
        self.text = text

    def get_text(self):
        return self.text

    def set_text(self, value):
        self.text = value


class NewNoteFlowTest(unittest.TestCase):
    def test_tag_selection_flushes_previous_note_before_changing_filter(self):
        calls = []
        window = SimpleNamespace(
            _refreshing=False, tag=None, folder_id="folder", note_id="note",
            _flush_save=lambda **_kwargs: calls.append(("save", window.folder_id)),
            _refresh_folders=lambda: calls.append(("navigation", window.tag)),
            _refresh_notes=lambda: calls.append(("notes", window.tag)),
        )
        NotesWindow._on_tag_selected(window, None, SimpleNamespace(tag="работа"))
        self.assertEqual(calls, [("save", "folder"), ("navigation", "работа"), ("notes", "работа")])
        self.assertIsNone(window.folder_id)
        self.assertIsNone(window.note_id)
        NotesWindow._on_folder_selected(window, None, SimpleNamespace(folder_id="folder"))
        self.assertIsNone(window.tag)
        self.assertEqual(window.folder_id, "folder")

    def test_ctrl_v_uses_image_clipboard_without_intercepting_text_paste(self):
        calls = []
        formats = SimpleNamespace(
            contain_gtype=lambda _kind: False,
            get_mime_types=lambda: ["image/png"],
        )
        clipboard = SimpleNamespace(
            get_formats=lambda: formats,
            read_texture_async=lambda _cancel, callback: calls.append(callback),
        )
        window = SimpleNamespace(
            note_id="selected",
            text_view=SimpleNamespace(get_editable=lambda: True, has_focus=lambda: True),
            get_display=lambda: SimpleNamespace(get_clipboard=lambda: clipboard),
            _image_pasted=lambda *_args: None,
        )
        self.assertTrue(NotesWindow._on_editor_paste(
            window, None, Gdk.KEY_v, 0, Gdk.ModifierType.CONTROL_MASK
        ))
        self.assertEqual(len(calls), 1)
        formats.get_mime_types = lambda: ["text/plain"]
        self.assertFalse(NotesWindow._on_editor_paste(
            window, None, Gdk.KEY_v, 0, Gdk.ModifierType.CONTROL_MASK
        ))

    def test_switch_without_edits_does_not_save_or_normalize_document(self):
        calls = []
        window = SimpleNamespace(
            _save_source=None,
            _loading=False,
            _dirty=False,
            note_id="first",
            store=SimpleNamespace(note=lambda _id: calls.append("read")),
        )
        self.assertFalse(NotesWindow._flush_save(window))
        self.assertEqual(calls, [])

    def test_note_switch_refreshes_list_only_after_saving_previous_note(self):
        calls = []
        window = SimpleNamespace(
            _refreshing=False,
            _show_note=lambda note_id: calls.append(("show", note_id)) or False,
            _refresh_notes=lambda **kwargs: calls.append(("refresh", kwargs["preferred"])),
            _refresh_folders=lambda: calls.append(("folders",)),
        )
        NotesWindow._on_note_selected(window, None, SimpleNamespace(note_id="second"))
        self.assertEqual(calls, [("show", "second")])
        window._show_note = lambda note_id: calls.append(("show", note_id)) or True
        NotesWindow._on_note_selected(window, None, SimpleNamespace(note_id="first"))
        self.assertEqual(calls[-3:], [("show", "first"), ("refresh", "first"), ("folders",)])

    def test_new_note_is_selected_even_from_trash_with_search(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NotesStore(Path(directory) / "notes.db")
            selected = []
            search = SearchStub("старый запрос")
            window = SimpleNamespace(
                folder_id=TRASH,
                tag="работа",
                store=store,
                search=search,
                note_id=None,
                title_entry=SimpleNamespace(grab_focus=lambda: None),
                _flush_save=lambda **_kwargs: None,
                _refresh_folders=lambda: None,
                _refresh_notes=lambda **kwargs: selected.append(kwargs["preferred"]),
            )
            NotesWindow._new_note(window)
            self.assertIsNone(window.tag)
            self.assertIsNone(window.folder_id)
            self.assertEqual(search.get_text(), "")
            self.assertEqual(len(selected), 1)
            self.assertIsNotNone(store.note(selected[0]))
            self.assertEqual(store.note(selected[0])["folder_id"], store.default_folder_id)
            store.close()


if __name__ == "__main__":
    unittest.main()
