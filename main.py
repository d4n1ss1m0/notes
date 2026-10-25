#!/usr/bin/env python3
"""Run the local Notes application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gio

from notes_app.storage import NotesStore
from notes_app.ui import NotesWindow, install_css


class NotesApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.d4n1ss1m0.Notes", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        data_root = Path(os.environ.get("NOTES_DATA_DIR", GLib.get_user_data_dir()))
        self.store = NotesStore(data_root / "notes" / "notes.db")
        self.window = None
        self._add_shortcut("new-note", ["<Control>n"], lambda: self.window._new_note())
        self._add_shortcut("new-folder", ["<Control><Shift>n"], lambda: self.window._new_folder())
        self._add_shortcut("search", ["<Control>f"], lambda: self.window.search.grab_focus())

    def _add_shortcut(self, name, accelerators, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_: callback() if self.window else None)
        self.add_action(action)
        self.set_accels_for_action(f"app.{name}", accelerators)

    def do_activate(self):
        if self.window is None:
            install_css()
            self.window = NotesWindow(self, self.store)
        self.window.present()

    def do_shutdown(self):
        self.store.close()
        Adw.Application.do_shutdown(self)


if __name__ == "__main__":
    raise SystemExit(NotesApplication().run(sys.argv))
