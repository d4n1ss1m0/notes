"""SQLite persistence for folders and plain-text notes."""

from __future__ import annotations

import sqlite3
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def plain_text_document(body: str) -> str:
    paragraphs = []
    for line in body.split("\n"):
        paragraph = {"type": "paragraph"}
        if line:
            paragraph["content"] = [{"type": "text", "text": line}]
        paragraphs.append(paragraph)
    return json.dumps({"type": "doc", "content": paragraphs}, ensure_ascii=False)


TAG_PATTERN = re.compile(r"(?<![\w/#])#([^\W_][\w-]*)")


def extract_tags(text: str) -> set[str]:
    """Recognize standalone Unicode hashtags; ignore URL fragments and bare #."""
    text = unicodedata.normalize("NFC", text)
    return {match.group(1).casefold() for match in TAG_PATTERN.finditer(text)}


class NotesStore:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.database)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self):
        self.db.close()

    def save_attachment(self, png_data: bytes) -> str:
        """Write a decoded image's PNG bytes outside the SQLite database."""
        if not png_data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Неверный формат изображения")
        attachments = self.database.parent / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        attachment_id = uuid4().hex
        target = attachments / f"{attachment_id}.png"
        temporary = attachments / f".{attachment_id}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(png_data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return attachment_id

    def attachment_path(self, attachment_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", attachment_id):
            raise ValueError("Неверный идентификатор вложения")
        return self.database.parent / "attachments" / f"{attachment_id}.png"

    def _migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 3:
            raise RuntimeError(f"Эта версия Notes не поддерживает базу версии {version}")
        if version == 0:
            with self.db:
                self.db.executescript("""
                    CREATE TABLE folders (
                        id TEXT PRIMARY KEY,
                        parent_id TEXT REFERENCES folders(id),
                        name TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        is_default INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE notes (
                        id TEXT PRIMARY KEY,
                        folder_id TEXT NOT NULL REFERENCES folders(id),
                        title TEXT NOT NULL DEFAULT '',
                        body TEXT NOT NULL DEFAULT '',
                        content_json TEXT NOT NULL DEFAULT '{"type":"doc","content":[{"type":"paragraph"}]}',
                        document_version INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        pinned INTEGER NOT NULL DEFAULT 0,
                        deleted_at TEXT
                    );
                    CREATE INDEX notes_folder_idx ON notes(folder_id, deleted_at);
                    CREATE INDEX notes_updated_idx ON notes(updated_at DESC);
                    PRAGMA user_version = 2;
                """)
                self.db.execute(
                    "INSERT INTO folders(id, name, is_default, created_at) VALUES (?, ?, 1, ?)",
                    (str(uuid4()), "Заметки", now()),
                )
        elif version == 1:
            with self.db:
                self.db.execute(
                    "ALTER TABLE notes ADD COLUMN content_json TEXT NOT NULL "
                    "DEFAULT '{\"type\":\"doc\",\"content\":[{\"type\":\"paragraph\"}]}'"
                )
                for note in self.db.execute("SELECT id, body FROM notes"):
                    self.db.execute("UPDATE notes SET content_json = ? WHERE id = ?",
                                    (plain_text_document(note["body"]), note["id"]))
                self.db.execute("PRAGMA user_version = 2")

        if version < 3:
            with self.db:
                self.db.execute("BEGIN")
                self.db.execute("""
                    CREATE TABLE note_tags (
                        note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                        tag TEXT NOT NULL,
                        PRIMARY KEY (note_id, tag)
                    )
                """)
                self.db.execute("CREATE INDEX note_tags_tag_idx ON note_tags(tag)")
                for note in self.db.execute("SELECT id, title, body FROM notes"):
                    self._update_tags(note["id"], note["title"], note["body"])
                self.db.execute("PRAGMA user_version = 3")

    def _update_tags(self, note_id: str, title: str, body: str):
        self.db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        self.db.executemany("INSERT INTO note_tags(note_id, tag) VALUES (?, ?)",
                            [(note_id, tag) for tag in extract_tags(title + "\n" + body)])

    def tags(self):
        return self.db.execute(
            "SELECT t.tag, COUNT(*) AS note_count FROM note_tags t "
            "JOIN notes n ON n.id = t.note_id WHERE n.deleted_at IS NULL "
            "GROUP BY t.tag ORDER BY t.tag"
        ).fetchall()

    @property
    def default_folder_id(self) -> str:
        row = self.db.execute("SELECT id FROM folders WHERE is_default = 1").fetchone()
        if row is None:
            raise RuntimeError("Не найдена основная папка заметок")
        return row["id"]

    def folders(self):
        return self.db.execute(
            "SELECT f.*, COUNT(n.id) AS note_count FROM folders f "
            "LEFT JOIN notes n ON n.folder_id = f.id AND n.deleted_at IS NULL "
            "GROUP BY f.id ORDER BY f.is_default DESC, f.position, f.name COLLATE NOCASE"
        ).fetchall()

    def folder(self, folder_id: str):
        return self.db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()

    def create_folder(self, name: str, parent_id: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Введите название папки")
        if parent_id is not None and self.folder(parent_id) is None:
            raise ValueError("Родительская папка не найдена")
        folder_id = str(uuid4())
        with self.db:
            self.db.execute(
                "INSERT INTO folders(id, parent_id, name, created_at) VALUES (?, ?, ?, ?)",
                (folder_id, parent_id, name, now()),
            )
        return folder_id

    def rename_folder(self, folder_id: str, name: str):
        name = name.strip()
        if not name:
            raise ValueError("Введите название папки")
        with self.db:
            self.db.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id))

    def delete_folder(self, folder_id: str):
        folder = self.folder(folder_id)
        if folder is None or folder["is_default"]:
            raise ValueError("Эту папку нельзя удалить")
        all_folders = self.folders()
        children = {}
        for item in all_folders:
            children.setdefault(item["parent_id"], []).append(item["id"])
        subtree = []

        def visit(current):
            for child in children.get(current, []):
                visit(child)
            subtree.append(current)

        visit(folder_id)
        with self.db:
            for item in subtree:
                self.db.execute(
                    "UPDATE notes SET folder_id = ? WHERE folder_id = ?",
                    (self.default_folder_id, item),
                )
                self.db.execute("DELETE FROM folders WHERE id = ?", (item,))

    def notes(self, folder_id: str | None = None, *, trash=False, query="", tag=None):
        sql = "SELECT * FROM notes WHERE deleted_at IS " + ("NOT NULL" if trash else "NULL")
        params = []
        if folder_id is not None and not trash:
            sql += " AND folder_id = ?"
            params.append(folder_id)
        if tag is not None:
            sql += " AND id IN (SELECT note_id FROM note_tags WHERE tag = ?)"
            params.append(unicodedata.normalize("NFC", tag).casefold())
        rows = self.db.execute(sql + " ORDER BY pinned DESC, updated_at DESC", params).fetchall()
        if query.strip():
            needle = query.strip().casefold()
            rows = [row for row in rows if needle in row["title"].casefold() or needle in row["body"].casefold()]
        return rows

    def note(self, note_id: str):
        return self.db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()

    def create_note(self, folder_id: str | None = None) -> str:
        folder_id = folder_id or self.default_folder_id
        if self.folder(folder_id) is None:
            raise ValueError("Папка не найдена")
        note_id = str(uuid4())
        timestamp = now()
        with self.db:
            self.db.execute(
                "INSERT INTO notes(id, folder_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (note_id, folder_id, timestamp, timestamp),
            )
        return note_id

    def save_note(self, note_id: str, title: str, body: str, content_json: str | None = None):
        if content_json is None:
            content_json = plain_text_document(body)
        with self.db:
            self.db.execute(
                "UPDATE notes SET title = ?, body = ?, content_json = ?, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NULL",
                (title, body, content_json, now(), note_id),
            )

            note = self.note(note_id)
            if note is not None and note["deleted_at"] is None:
                self._update_tags(note_id, title, body)

    def move_note(self, note_id: str, folder_id: str):
        if self.folder(folder_id) is None:
            raise ValueError("Папка не найдена")
        with self.db:
            self.db.execute(
                "UPDATE notes SET folder_id = ?, updated_at = ? WHERE id = ?",
                (folder_id, now(), note_id),
            )

    def set_pinned(self, note_id: str, pinned: bool):
        with self.db:
            self.db.execute("UPDATE notes SET pinned = ? WHERE id = ?", (int(pinned), note_id))

    def trash_note(self, note_id: str):
        with self.db:
            self.db.execute("UPDATE notes SET deleted_at = ? WHERE id = ?", (now(), note_id))

    def restore_note(self, note_id: str):
        with self.db:
            self.db.execute("UPDATE notes SET deleted_at = NULL, updated_at = ? WHERE id = ?", (now(), note_id))

    def delete_note_forever(self, note_id: str):
        with self.db:
            self.db.execute("DELETE FROM notes WHERE id = ? AND deleted_at IS NOT NULL", (note_id,))

    def counts(self):
        active = self.db.execute("SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL").fetchone()[0]
        trash = self.db.execute("SELECT COUNT(*) FROM notes WHERE deleted_at IS NOT NULL").fetchone()[0]
        return active, trash
