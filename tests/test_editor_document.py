import json
import tempfile
import unittest
from pathlib import Path

from notes_app.editor_document import (document_to_lines, lines_to_document,
                                       image_data, make_image, make_table,
                                       repair_excess_blank_lines, table_data)
from notes_app.storage import NotesStore


class EditorDocumentTest(unittest.TestCase):
    def test_image_reference_and_size_survive_document_conversion(self):
        image = make_image("f" * 32, 420)
        body, document = lines_to_document([("image", image)])
        self.assertEqual(body, "")
        self.assertEqual(image_data(document_to_lines(document)[0][1]), ("f" * 32, 420))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "notes.db"
            store = NotesStore(database)
            attachment_id = store.save_attachment(b"\x89PNG\r\n\x1a\nfixture")
            body, document = lines_to_document([("image", make_image(attachment_id, 420))])
            note_id = store.create_note()
            store.save_note(note_id, "Фото", body, document)
            store.close()
            reopened = NotesStore(database)
            self.assertEqual(image_data(document_to_lines(reopened.note(note_id)["content_json"])[0][1]),
                             (attachment_id, 420))
            self.assertTrue(reopened.attachment_path(attachment_id).exists())
            reopened.close()

    def test_table_preserves_header_cells_values_and_widths(self):
        table = make_table([["Заголовок", "Цена"], ["Книга", "100"]], [180, 95])
        body, document = lines_to_document([("table", table)])
        self.assertIn("Книга\t100", body)
        self.assertEqual(table_data(document_to_lines(document)[0][1]),
                         ([["Заголовок", "Цена"], ["Книга", "100"]], [180, 95]))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "notes.db"
            store = NotesStore(database)
            note_id = store.create_note()
            store.save_note(note_id, "Товары", body, document)
            store.close()
            store = NotesStore(database)
            saved = store.note(note_id)
            self.assertEqual(table_data(document_to_lines(saved["content_json"])[0][1]),
                             ([["Заголовок", "Цена"], ["Книга", "100"]], [180, 95]))
            self.assertEqual([row["id"] for row in store.notes(query="КНИГА")], [note_id])
            store.close()

    def test_heading_lists_and_completed_tasks_survive_reopen(self):
        lines = [
            ("heading1", "План поездки"),
            ("heading2", "Подготовка"),
            ("heading3", "Документы"),
            ("paragraph", "Обычный текст"),
            ("bullet", "• Паспорт"),
            ("bullet", "• Билеты"),
            ("number", "1. Купить билеты"),
            ("number", "2. Собрать вещи"),
            ("todo", "✓ Забронировать жильё"),
            ("todo", "☐ Заказать такси"),
        ]
        body, document = lines_to_document(lines)
        self.assertNotIn("✓", body)
        self.assertEqual(document_to_lines(document), lines)
        nodes = json.loads(document)["content"]
        self.assertEqual([node["type"] for node in nodes[-3:]],
                         ["bulletList", "orderedList", "taskList"])
        self.assertTrue(nodes[-1]["content"][0]["attrs"]["checked"])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "notes.db"
            store = NotesStore(database)
            note_id = store.create_note()
            store.save_note(note_id, "Поездка", body, document)
            store.close()
            store = NotesStore(database)
            note = store.note(note_id)
            self.assertEqual(document_to_lines(note["content_json"]), lines)
            self.assertEqual([item["id"] for item in store.notes(query="ЖИЛЬЁ")], [note_id])
            store.close()

    def test_plain_text_document_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NotesStore(Path(directory) / "notes.db")
            note_id = store.create_note()
            store.save_note(note_id, "", "Первая\nВторая")
            note = store.note(note_id)
            self.assertEqual(document_to_lines(note["content_json"]),
                             [("paragraph", "Первая"), ("paragraph", "Вторая")])
            store.close()

    def test_repairs_only_pathological_blank_runs(self):
        prefix = {"type": "paragraph", "content": [{"type": "text", "text": "Сохранить"}]}
        broken = {"type": "paragraph", "content": [{"type": "text", "text": "\n"}]}
        raw = json.dumps({"type": "doc", "content": [prefix] + [broken] * 128 + [{"type": "paragraph"}]})
        body, repaired = repair_excess_blank_lines(raw)
        self.assertEqual(body, "Сохранить\n")
        self.assertEqual(len(json.loads(repaired)["content"]), 2)
        small = json.dumps({"type": "doc", "content": [prefix] + [broken] * 3})
        self.assertIsNone(repair_excess_blank_lines(small))


if __name__ == "__main__":
    unittest.main()
