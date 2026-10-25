"""A small editable table embedded in a Gtk.TextView child anchor."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from .editor_document import make_table, table_data


def table_viewport_width(widths: list[int], available_width: int) -> int:
    """Keep the table viewport inside the note, scrolling when cells are wider."""
    return min(max(1, available_width), sum(widths) + 2)


class TableWidget(Gtk.Box):
    def __init__(self, node: dict, changed, delete):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.add_css_class("note-table")
        self.rows, self.widths = table_data(node)
        self.changed = changed
        self.delete = delete
        self._entries = []
        self._column_cells = []
        self._available_width = 320
        self._hovered = False
        self._resizing = False

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_propagate_natural_width(False)
        self.grid = Gtk.Grid(column_spacing=0, row_spacing=0)
        self.grid.add_css_class("note-table-grid")
        self.scroll.set_child(self.grid)
        self.overlay = Gtk.Overlay()
        self.overlay.set_child(self.scroll)
        self.append(self.overlay)

        self.actions = Gtk.MenuButton()
        self.actions.set_icon_name("view-more-symbolic")
        self.actions.set_tooltip_text("Действия с таблицей")
        self.actions.add_css_class("flat")
        self.actions.add_css_class("table-actions")
        self.actions.set_halign(Gtk.Align.END)
        self.actions.set_valign(Gtk.Align.START)
        self.actions.set_margin_top(3)
        self.actions.set_margin_end(10)
        menu = Gtk.Popover()
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        controls.add_css_class("table-controls")
        for caption, tip, callback in (
            ("Добавить строку", "Добавить строку", self.add_row),
            ("Добавить столбец", "Добавить столбец", self.add_column),
            ("Удалить строку", "Удалить последнюю строку", self.remove_row),
            ("Удалить столбец", "Удалить последний столбец", self.remove_column),
            ("Удалить таблицу", "Удалить таблицу", lambda *_: self.delete()),
        ):
            button = Gtk.Button(label=caption)
            button.add_css_class("flat")
            button.set_tooltip_text(tip)
            button.connect("clicked", lambda _button, action=callback: (action(), menu.popdown()))
            controls.append(button)
        menu.set_child(controls)
        menu.connect("closed", lambda *_: self._update_actions_visibility())
        self.actions.set_popover(menu)
        self.actions.set_visible(False)
        self.overlay.add_overlay(self.actions)
        self.overlay.set_measure_overlay(self.actions, False)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._pointer_enter)
        motion.connect("leave", self._pointer_leave)
        self.add_controller(motion)
        self._focus = Gtk.EventControllerFocus()
        self._focus.connect("enter", lambda *_: self._update_actions_visibility())
        self._focus.connect("leave", lambda *_: self._update_actions_visibility())
        self.add_controller(self._focus)
        self._rebuild()

    def _pointer_enter(self, *_args):
        self._hovered = True
        self._update_actions_visibility()

    def _pointer_leave(self, *_args):
        self._hovered = False
        self._update_actions_visibility()

    def _update_actions_visibility(self):
        self.actions.set_visible(
            self._hovered or self._focus.contains_focus() or self.actions.get_active()
        )

    def set_available_width(self, width: int):
        width = max(1, width)
        if width == self._available_width:
            return
        self._available_width = width
        if not self._resizing:
            self._update_scroll_width()

    def _update_scroll_width(self):
        viewport = table_viewport_width(self.widths, self._available_width)
        self.scroll.set_max_content_width(viewport)
        self.scroll.set_size_request(viewport, -1)

    def to_node(self) -> dict:
        return make_table(self.rows, self.widths)

    def _rebuild(self):
        while child := self.grid.get_first_child():
            self.grid.remove(child)
        self._entries = []
        self._column_cells = [[] for _ in self.widths]
        for row_index, row in enumerate(self.rows):
            entry_row = []
            for column, value in enumerate(row):
                entry = Gtk.Entry(text=value)
                entry.add_css_class("table-header-cell" if row_index == 0 else "table-cell")
                entry.set_width_chars(1)
                entry.set_hexpand(True)
                entry.connect("changed", self._cell_changed, row_index, column)
                entry.connect("activate", self._cell_activated, row_index, column)
                entry_row.append(entry)
                cell = Gtk.Overlay()
                cell.set_size_request(self.widths[column], -1)
                self._column_cells[column].append(cell)
                cell.set_child(entry)
                if row_index == 0:
                    handle = Gtk.Box()
                    handle.add_css_class("table-resize-handle")
                    handle.set_size_request(8, -1)
                    handle.set_halign(Gtk.Align.END)
                    handle.set_valign(Gtk.Align.FILL)
                    handle.set_cursor_from_name("col-resize")
                    handle.set_tooltip_text("Перетащите, чтобы изменить ширину столбца")
                    gesture = Gtk.GestureDrag()
                    gesture.set_button(1)
                    gesture.set_exclusive(True)
                    gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
                    gesture.connect("begin", lambda current, _sequence:
                                    current.set_state(Gtk.EventSequenceState.CLAIMED))
                    gesture.connect("drag-begin", self._resize_begin, column)
                    gesture.connect("drag-update", self._resize_update, column)
                    gesture.connect("drag-end", self._resize_end)
                    gesture.connect("cancel", self._resize_end)
                    handle.add_controller(gesture)
                    cell.add_overlay(handle)
                self.grid.attach(cell, column, row_index, 1, 1)
            self._entries.append(entry_row)
        self._update_scroll_width()

    def _cell_changed(self, entry, row, column):
        self.rows[row][column] = entry.get_text()
        self.changed()

    def _cell_activated(self, _entry, row, column):
        if row + 1 == len(self.rows):
            self.add_row()
        self._entries[row + 1][column].grab_focus()

    def _resize_begin(self, _gesture, _x, _y, column):
        _gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._resizing = True
        self._starting_width = self.widths[column]

    def _resize_update(self, _gesture, offset_x, _offset_y, column):
        width = max(80, min(800, round(self._starting_width + offset_x)))
        if self.widths[column] == width:
            return
        self.widths[column] = width
        for cell in self._column_cells[column]:
            cell.set_size_request(width, -1)

    def _resize_end(self, *_args):
        self._resizing = False
        self._update_scroll_width()
        self.changed()

    def add_row(self, *_args):
        self.rows.append([""] * len(self.widths))
        self._rebuild()
        self.changed()

    def add_column(self, *_args):
        self.widths.append(160)
        for row in self.rows:
            row.append("")
        self._rebuild()
        self.changed()

    def remove_row(self, *_args):
        if len(self.rows) <= 1:
            return
        self.rows.pop()
        self._rebuild()
        self.changed()

    def remove_column(self, *_args):
        if len(self.widths) <= 1:
            return
        self.widths.pop()
        for row in self.rows:
            row.pop()
        self._rebuild()
        self.changed()
