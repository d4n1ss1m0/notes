"""Bounds and saved widths for the three-pane window."""

from __future__ import annotations

import json
import os
from pathlib import Path


WIDTHS = {
    "folders": (180, 380, 228),
    "notes": (250, 520, 300),
}


def bounded_width(column: str, value) -> int:
    minimum, maximum, default = WIDTHS[column]
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))


class PaneLayout:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        self.tags_expanded = saved.get("tags_expanded", True) is not False
        self.widths = {name: bounded_width(name, saved.get(name)) for name in WIDTHS}

    def set_width(self, column: str, value: int) -> int:
        width = bounded_width(column, value)
        self.widths[column] = width
        return width

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({**self.widths, "tags_expanded": self.tags_expanded}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
