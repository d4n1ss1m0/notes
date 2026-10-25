#!/usr/bin/env python3
"""Repair blank paragraphs duplicated by older Notes editor versions."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from notes_app.editor_document import repair_excess_blank_lines


def main():
    data_root = Path(os.environ.get("NOTES_DATA_DIR", os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")))
    database = data_root / "notes" / "notes.db"
    if not database.exists():
        raise SystemExit(f"База не найдена: {database}")

    connection = sqlite3.connect(database)
    repairs = []
    for note_id, document in connection.execute("SELECT id, content_json FROM notes"):
        result = repair_excess_blank_lines(document)
        if result is not None:
            repairs.append((result[0], result[1], note_id))
    if not repairs:
        print("Повреждённых длинных серий пустых строк нет.")
        connection.close()
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database.with_name(f"notes.db.before-blank-line-repair-{stamp}")
    backup = sqlite3.connect(backup_path)
    connection.backup(backup)
    backup.close()
    with connection:
        connection.executemany(
            "UPDATE notes SET body = ?, content_json = ? WHERE id = ?", repairs
        )
    connection.execute("VACUUM")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    print(f"Исправлено заметок: {len(repairs)}. Резервная копия: {backup_path}")


if __name__ == "__main__":
    main()
