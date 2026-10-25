import tempfile
import unittest
import json
import sqlite3
from pathlib import Path

from notes_app.storage import NotesStore, extract_tags


class NotesStoreTest(unittest.TestCase):
    def test_unicode_hashtags_and_boundaries(self):
        self.assertEqual(extract_tags(
            "#Работа #работа #план-2026 #мой_тег (#English), #123 "
            "# ## заголовок https://example.org/#fragment word#inside"
        ), {"работа", "план-2026", "мой_тег", "english", "123"})

    def test_tags_survive_reopen_and_follow_edits_trash_and_deletion(self):
        first = self.store.create_note()
        second = self.store.create_note(self.store.create_folder("Другая"))
        self.store.save_note(first, "#Работа", "#работа #дом")
        self.store.save_note(second, "План", "#РАБОТА")
        self.store.close()
        self.store = NotesStore(self.database)
        self.assertEqual({r["tag"]: r["note_count"] for r in self.store.tags()},
                         {"работа": 2, "дом": 1})
        self.assertEqual({r["id"] for r in self.store.notes(tag="РАБОТА")}, {first, second})
        self.assertEqual([r["id"] for r in self.store.notes(tag="работа", query="план")], [second])
        self.store.save_note(first, "План", "#дом")
        self.assertEqual([r["id"] for r in self.store.notes(tag="работа")], [second])
        self.store.trash_note(second)
        self.assertEqual([r["tag"] for r in self.store.tags()], ["дом"])
        self.store.restore_note(second)
        self.assertEqual([r["id"] for r in self.store.notes(tag="работа")], [second])
        self.store.trash_note(second)
        self.store.delete_note_forever(second)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM note_tags WHERE note_id = ?", (second,)
        ).fetchone()[0], 0)

    def test_migration_indexes_existing_tags_without_modifying_notes(self):
        note = self.store.create_note()
        self.store.save_note(note, "#Старый", "Текст #тег")
        original = dict(self.store.note(note))
        self.store.db.execute("DROP TABLE note_tags")
        self.store.db.execute("PRAGMA user_version = 2")
        self.store.db.commit()
        self.store.close()
        self.store = NotesStore(self.database)
        self.assertEqual(dict(self.store.note(note)), original)
        self.assertEqual({r["tag"] for r in self.store.tags()}, {"старый", "тег"})

    def test_attachment_is_stored_outside_database_with_safe_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NotesStore(Path(directory) / "notes.db")
            png = b"\x89PNG\r\n\x1a\nexample"
            attachment_id = store.save_attachment(png)
            self.assertEqual(store.attachment_path(attachment_id).read_bytes(), png)
            with self.assertRaises(ValueError):
                store.attachment_path("../notes.db")
            store.close()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "notes.db"
        self.store = NotesStore(self.database)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_text_survives_reopen_and_russian_search(self):
        folder = self.store.create_folder("Работа")
        note = self.store.create_note(folder)
        self.store.save_note(note, "Планы", "Встреча в среду")
        self.store.close()
        self.store = NotesStore(self.database)
        self.assertEqual(self.store.note(note)["body"], "Встреча в среду")
        self.assertEqual(json.loads(self.store.note(note)["content_json"])["content"][0]["type"], "paragraph")
        self.assertEqual([item["id"] for item in self.store.notes(query="ВСТРЕЧА")], [note])
        self.assertEqual([item["id"] for item in self.store.notes(folder)], [note])

    def test_move_pin_trash_restore(self):
        first = self.store.create_folder("Первая")
        second = self.store.create_folder("Вторая")
        note = self.store.create_note(first)
        self.store.move_note(note, second)
        self.store.set_pinned(note, True)
        self.assertEqual(self.store.note(note)["folder_id"], second)
        self.assertEqual(self.store.note(note)["pinned"], 1)
        self.store.trash_note(note)
        self.assertEqual(len(self.store.notes()), 0)
        self.assertEqual([item["id"] for item in self.store.notes(trash=True)], [note])
        self.store.restore_note(note)
        self.assertEqual([item["id"] for item in self.store.notes(second)], [note])

    def test_deleting_nested_folder_preserves_notes(self):
        parent = self.store.create_folder("Родитель")
        child = self.store.create_folder("Вложенная", parent)
        note = self.store.create_note(child)
        self.store.save_note(note, "Важно", "Сохранить")
        self.store.delete_folder(parent)
        self.assertIsNone(self.store.folder(parent))
        self.assertIsNone(self.store.folder(child))
        self.assertEqual(self.store.note(note)["folder_id"], self.store.default_folder_id)
        self.assertEqual(self.store.note(note)["body"], "Сохранить")

    def test_migrating_plain_text_database_preserves_content(self):
        self.store.close()
        self.database.unlink()
        old = sqlite3.connect(self.database)
        old.executescript("""
            CREATE TABLE folders (id TEXT PRIMARY KEY, parent_id TEXT, name TEXT, position INTEGER,
                                  is_default INTEGER, created_at TEXT);
            CREATE TABLE notes (id TEXT PRIMARY KEY, folder_id TEXT, title TEXT, body TEXT,
                                document_version INTEGER, created_at TEXT, updated_at TEXT,
                                pinned INTEGER, deleted_at TEXT);
            INSERT INTO folders VALUES ('root', NULL, 'Заметки', 0, 1, '2026-01-01');
            INSERT INTO notes VALUES ('note', 'root', 'Привет', 'Строка 1\nСтрока 2', 1,
                                      '2026-01-01', '2026-01-01', 0, NULL);
            PRAGMA user_version = 1;
        """)
        old.close()
        self.store = NotesStore(self.database)
        note = self.store.note("note")
        self.assertEqual(note["body"], "Строка 1\nСтрока 2")
        self.assertEqual(len(json.loads(note["content_json"])["content"]), 2)


if __name__ == "__main__":
    unittest.main()
