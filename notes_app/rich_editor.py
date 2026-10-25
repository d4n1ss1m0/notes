"""Paragraph styles, lists and checkable tasks for the GTK text editor."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gtk, Pango

from .editor_document import (NUMBER_PREFIX, document_to_lines, image_data,
                              lines_to_document, make_image, make_table, strip_prefix)
from .image_widget import ImageWidget
from .table_widget import TableWidget


class RichEditor:
    KINDS = ("paragraph", "heading1", "heading2", "heading3", "bullet", "number", "todo")

    def __init__(self, view: Gtk.TextView, changed, attachment_path):
        self.view = view
        self.buffer = view.get_buffer()
        self.changed = changed
        self.attachment_path = attachment_path
        self._loading = False
        self._pending_styles = {}
        self._task_buttons = {}
        self._table_widgets = {}
        self._image_widgets = {}
        self._last_table_width = None
        self.heading_tags = {
            "heading1": self.buffer.create_tag("heading1", scale=1.65, weight=Pango.Weight.BOLD,
                                                pixels_above_lines=5, pixels_below_lines=1),
            "heading2": self.buffer.create_tag("heading2", scale=1.35, weight=Pango.Weight.BOLD,
                                                pixels_above_lines=4, pixels_below_lines=1),
            "heading3": self.buffer.create_tag("heading3", scale=1.15, weight=Pango.Weight.SEMIBOLD,
                                                pixels_above_lines=3, pixels_below_lines=1),
        }
        self.buffer.connect("changed", self._on_changed)
        self.view.add_controller(self._key_controller())
        self.view.add_tick_callback(self._update_embedded_widths)

    def available_content_width(self):
        width = self.view.get_width()
        if width <= 0:
            return 320
        return max(1, width - self.view.get_left_margin() - self.view.get_right_margin() - 4)

    def _update_embedded_widths(self, *_args):
        width = self.available_content_width()
        if width != self._last_table_width:
            self._last_table_width = width
            for widget in self._table_widgets.values():
                widget.set_available_width(width)
            for widget in self._image_widgets.values():
                widget.set_available_width(width)
        return True

    def _key_controller(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        return controller

    def _line_bounds(self, line: int):
        start = self.buffer.get_iter_at_line(line)[1]
        if line + 1 < self.buffer.get_line_count():
            end = self.buffer.get_iter_at_line(line + 1)[1]
            end.backward_char()
        else:
            end = self.buffer.get_end_iter()
        return start, end

    def _line_text(self, line: int) -> str:
        start, end = self._line_bounds(line)
        return self.buffer.get_slice(start, end, True)

    def _task_button(self, line: int):
        anchor = self.buffer.get_iter_at_line(line)[1].get_child_anchor()
        return self._task_buttons.get(anchor) if anchor is not None else None

    def _table_widget(self, line: int):
        anchor = self.buffer.get_iter_at_line(line)[1].get_child_anchor()
        return self._table_widgets.get(anchor) if anchor is not None else None

    def _image_widget(self, line: int):
        anchor = self.buffer.get_iter_at_line(line)[1].get_child_anchor()
        return self._image_widgets.get(anchor) if anchor is not None else None

    def _has_embedded_block(self, line: int) -> bool:
        start, end = self._line_bounds(line)
        probe = start.copy()
        while probe.compare(end) < 0:
            anchor = probe.get_child_anchor()
            if anchor in self._table_widgets or anchor in self._image_widgets:
                return True
            probe.forward_char()
        return False

    def _insert_image_anchor(self, line: int, node: dict):
        anchor = self.buffer.create_child_anchor(self.buffer.get_iter_at_line(line)[1])
        attachment_id, _width = image_data(node)
        try:
            path = self.attachment_path(attachment_id)
        except ValueError:
            path = self.attachment_path("0" * 32)
        widget = ImageWidget(node, path, self.changed, lambda: self._delete_image(anchor))
        self._image_widgets[anchor] = widget
        self.view.add_child_at_anchor(widget, anchor)
        widget.set_available_width(self.available_content_width())
        widget.set_sensitive(self.view.get_editable())
        return anchor

    def _delete_image(self, anchor):
        widget = self._image_widgets.pop(anchor, None)
        if widget is None:
            return
        if widget.get_parent() is self.view:
            self.view.remove(widget)
        start = self.buffer.get_iter_at_child_anchor(anchor)
        end = start.copy()
        end.forward_char()
        self.buffer.delete(start, end)
        self.changed()

    def insert_image(self, attachment_id: str, width: int):
        if not self.view.get_editable():
            return
        self.buffer.begin_user_action()
        self._loading = True
        try:
            line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
            if self._line_text(line):
                self.buffer.insert(self._line_bounds(line)[1], "\n")
                line += 1
            last_line = line + 1 == self.buffer.get_line_count()
            self._insert_image_anchor(line, make_image(attachment_id, width))
            if last_line:
                self.buffer.insert(self._line_bounds(line)[1], "\n")
        finally:
            self._loading = False
            self.buffer.end_user_action()
        self.changed()

    def _insert_table_anchor(self, line: int, node: dict):
        anchor = self.buffer.create_child_anchor(self.buffer.get_iter_at_line(line)[1])
        widget = TableWidget(node, self.changed, lambda: self._delete_table(anchor))
        self._table_widgets[anchor] = widget
        self.view.add_child_at_anchor(widget, anchor)
        widget.set_available_width(self.available_content_width())
        widget.set_sensitive(self.view.get_editable())
        return anchor

    def _delete_table(self, anchor):
        widget = self._table_widgets.pop(anchor, None)
        if widget is None:
            return
        if widget.get_parent() is self.view:
            self.view.remove(widget)
        start = self.buffer.get_iter_at_child_anchor(anchor)
        end = start.copy()
        end.forward_char()
        self.buffer.delete(start, end)
        self.changed()

    def insert_table(self):
        if not self.view.get_editable():
            return
        self.buffer.begin_user_action()
        self._loading = True
        try:
            line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
            if self._line_text(line):
                self.buffer.insert(self._line_bounds(line)[1], "\n")
                line += 1
            last_line = line + 1 == self.buffer.get_line_count()
            self._insert_table_anchor(line, make_table([["", ""], ["", ""]], [160, 160]))
            if last_line:
                after = self._line_bounds(line)[1]
                self.buffer.insert(after, "\n")
        finally:
            self._loading = False
            self.buffer.end_user_action()
        self.changed()

    def _make_task_button(self, checked: bool):
        button = Gtk.CheckButton()
        button.add_css_class("task-check")
        button.set_active(checked)
        button.set_sensitive(self.view.get_editable())
        button.set_tooltip_text("Отметить задачу выполненной")
        button.connect("toggled", lambda _button: self.changed() if not self._loading else None)
        return button

    def _insert_task_marker(self, line: int, checked: bool):
        start = self.buffer.get_iter_at_line(line)[1]
        anchor = self.buffer.create_child_anchor(start)
        button = self._make_task_button(checked)
        self._task_buttons[anchor] = button
        self.view.add_child_at_anchor(button, anchor)
        after = self.buffer.get_iter_at_child_anchor(anchor)
        after.forward_char()
        self.buffer.insert(after, " ")
        return anchor

    def _drop_task_button(self, line: int):
        start = self.buffer.get_iter_at_line(line)[1]
        anchor = start.get_child_anchor()
        if anchor in self._task_buttons:
            self.view.remove(self._task_buttons.pop(anchor))

    def _strip_display_prefix(self, text: str) -> str:
        return text[2:] if text.startswith("\ufffc ") else strip_prefix(text)

    def _line_kind(self, line: int) -> str:
        value = self._line_text(line)
        if value.startswith("\ufffc") and self._table_widget(line) is not None:
            return "table"
        if value.startswith("\ufffc") and self._image_widget(line) is not None:
            return "image"
        if value.startswith("\ufffc ") and self._task_button(line) is not None:
            return "todo"
        if value.startswith(("● ", "• ")):
            return "bullet"
        if NUMBER_PREFIX.match(value):
            return "number"
        start, end = self._line_bounds(line)
        probe = start.copy()
        while probe.compare(end) < 0:
            for kind, tag in self.heading_tags.items():
                if probe.has_tag(tag):
                    return kind
            probe.forward_char()
        return self._pending_styles.get(line, "paragraph")

    def current_kind(self) -> str:
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return self._line_kind(cursor.get_line())

    def _selected_lines(self):
        selection = self.buffer.get_selection_bounds()
        if selection:
            first, last = selection
            end_line = last.get_line() - (last.starts_line() and last.get_line() > first.get_line())
            return range(first.get_line(), end_line + 1)
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return range(cursor.get_line(), cursor.get_line() + 1)

    def _on_changed(self, *_args):
        if self._loading:
            return
        for anchor, widget in list(self._table_widgets.items()):
            if anchor.get_deleted():
                if widget.get_parent() is self.view:
                    self.view.remove(widget)
                del self._table_widgets[anchor]
        for anchor, widget in list(self._image_widgets.items()):
            if anchor.get_deleted():
                if widget.get_parent() is self.view:
                    self.view.remove(widget)
                del self._image_widgets[anchor]
        for line in range(self.buffer.get_line_count()):
            kind = self._line_kind(line)
            if kind in self.heading_tags and self._line_text(line):
                self._apply_heading(line, kind)
        for line, kind in list(self._pending_styles.items()):
            if line >= self.buffer.get_line_count():
                del self._pending_styles[line]
            elif self._line_text(line):
                self._apply_heading(line, kind)
                del self._pending_styles[line]
        self.changed()

    def _apply_heading(self, line: int, kind: str):
        start, end = self._line_bounds(line)
        for tag in self.heading_tags.values():
            self.buffer.remove_tag(tag, start, end)
        if kind in self.heading_tags:
            if start.equal(end):
                self._pending_styles[line] = kind
            else:
                self.buffer.apply_tag(self.heading_tags[kind], start, end)
        else:
            self._pending_styles.pop(line, None)

    def set_kind(self, kind: str):
        if kind not in self.KINDS:
            return
        self.buffer.begin_user_action()
        try:
            for line in reversed(list(self._selected_lines())):
                if self._has_embedded_block(line):
                    continue
                original = self._line_text(line)
                value = self._strip_display_prefix(original)
                if kind == "bullet":
                    display = "• " + value
                elif kind == "number":
                    display = "1. " + value
                elif kind == "todo":
                    display = "\ufffc " + value
                else:
                    display = value
                if original != display:
                    start, end = self._line_bounds(line)
                    self._drop_task_button(line)
                    self.buffer.delete(start, end)
                    if kind == "todo":
                        self.buffer.insert(self.buffer.get_iter_at_line(line)[1], value)
                        self._insert_task_marker(line, False)
                    else:
                        self.buffer.insert(self.buffer.get_iter_at_line(line)[1], display)
                self._apply_heading(line, kind)
            if kind == "number":
                self._renumber_ordered_lists()
        finally:
            self.buffer.end_user_action()
        self.changed()
        self.view.grab_focus()

    def _renumber_ordered_lists(self):
        number = 0
        for line in range(self.buffer.get_line_count()):
            match = NUMBER_PREFIX.match(self._line_text(line))
            if match is None:
                number = 0
                continue
            number += 1
            desired = f"{number}. "
            if match.group(0) != desired:
                start = self.buffer.get_iter_at_line(line)[1]
                end = start.copy()
                end.forward_chars(len(match.group(0)))
                self.buffer.delete(start, end)
                self.buffer.insert(self.buffer.get_iter_at_line(line)[1], desired)

    def toggle_task(self, line: int | None = None):
        if line is None:
            line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        button = self._task_button(line)
        if button is None:
            self.set_kind("todo")
            return
        button.set_active(not button.get_active())

    def set_editable(self, editable: bool):
        for button in self._task_buttons.values():
            button.set_sensitive(editable)
        for widget in self._table_widgets.values():
            widget.set_sensitive(editable)
        for widget in self._image_widgets.values():
            widget.set_sensitive(editable)

    def _on_key_pressed(self, _controller, keyval, _keycode, modifiers):
        if not self.view.get_editable() or keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if modifiers & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK):
            return False
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line = cursor.get_line()
        kind = self._line_kind(line)
        if kind not in ("bullet", "number", "todo", "heading1", "heading2", "heading3"):
            return False
        value = self._line_text(line)
        self.buffer.begin_user_action()
        try:
            if kind in ("bullet", "number", "todo") and not self._strip_display_prefix(value):
                self.set_kind("paragraph")
                return True
            self.buffer.delete_selection(True, True)
            if kind == "bullet":
                prefix = "• "
            elif kind == "number":
                match = NUMBER_PREFIX.match(value)
                prefix = f"{int(match.group(1)) + 1}. " if match else "1. "
            elif kind == "todo":
                prefix = ""
            else:
                prefix = ""
            self.buffer.insert_at_cursor("\n" + prefix)
            if kind == "todo":
                next_line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
                anchor = self._insert_task_marker(next_line, False)
                after = self.buffer.get_iter_at_child_anchor(anchor)
                after.forward_chars(2)
                self.buffer.place_cursor(after)
            if kind.startswith("heading"):
                next_line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
                self._apply_heading(next_line, "paragraph")
        finally:
            self.buffer.end_user_action()
        return True

    def load(self, content_json: str, fallback_body: str = ""):
        lines = document_to_lines(content_json, fallback_body)
        self._loading = True
        self._pending_styles.clear()
        try:
            for button in self._task_buttons.values():
                self.view.remove(button)
            self._task_buttons.clear()
            for widget in self._table_widgets.values():
                if getattr(widget, "get_parent", lambda: self.view)() is self.view:
                    self.view.remove(widget)
            self._table_widgets.clear()
            for widget in self._image_widgets.values():
                if getattr(widget, "get_parent", lambda: self.view)() is self.view:
                    self.view.remove(widget)
            self._image_widgets.clear()
            self.buffer.set_text("\n".join("" if kind in ("table", "image") else
                                           self._strip_display_prefix(text) if kind == "todo" else text
                                           for kind, text in lines))
            for line, (kind, display) in enumerate(lines):
                if kind == "todo":
                    self._insert_task_marker(line, display.startswith("✓ "))
                if kind == "table":
                    self._insert_table_anchor(line, display)
                if kind == "image":
                    self._insert_image_anchor(line, display)
                if kind.startswith("heading"):
                    self._apply_heading(line, kind)
        finally:
            self._loading = False

    def snapshot(self) -> tuple[str, str]:
        lines = []
        for line in range(self.buffer.get_line_count()):
            start, end = self._line_bounds(line)
            probe = start.copy()
            segment = start.copy()
            embedded = False
            while probe.compare(end) < 0:
                anchor = probe.get_child_anchor()
                widget = self._table_widgets.get(anchor) or self._image_widgets.get(anchor)
                if widget is not None:
                    before = self.buffer.get_slice(segment, probe, True)
                    if before:
                        lines.append(("paragraph", before))
                    lines.append(("table" if anchor in self._table_widgets else "image",
                                  widget.to_node()))
                    probe.forward_char()
                    segment = probe.copy()
                    embedded = True
                else:
                    probe.forward_char()
            if embedded:
                after = self.buffer.get_slice(segment, end, True)
                if after:
                    lines.append(("paragraph", after))
                continue
            kind = self._line_kind(line)
            value = self._line_text(line)
            if kind == "todo":
                button = self._task_button(line)
                value = ("✓ " if button.get_active() else "☐ ") + value[2:]
            lines.append((kind, value))
        return lines_to_document(lines)
