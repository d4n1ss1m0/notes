"""Resizable attachment displayed inside a Gtk.TextView child anchor."""

from __future__ import annotations

from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from .editor_document import image_data, make_image


class ImageWidget(Gtk.Overlay):
    def __init__(self, node: dict, path: Path, changed, delete):
        super().__init__()
        self.add_css_class("note-image")
        self.attachment_id, self.width = image_data(node)
        self.changed = changed
        self._available_width = 360
        self._dragging = False
        self._hovered = False
        try:
            self.surface = cairo.ImageSurface.create_from_png(str(path))
        except (cairo.Error, OSError):
            self.surface = None
        self.natural_width = self.surface.get_width() if self.surface else 320
        self.natural_height = self.surface.get_height() if self.surface else 180
        if self.surface is None:
            self.picture = Gtk.Label(label="Изображение недоступно")
            self.picture.add_css_class("image-missing")
        else:
            self.picture = Gtk.DrawingArea()
            self.picture.set_draw_func(self._draw_image)
        self.set_child(self.picture)

        self.handle = Gtk.Box()
        self.handle.add_css_class("image-resize-handle")
        self.handle.set_size_request(18, 18)
        self.handle.set_halign(Gtk.Align.END)
        self.handle.set_valign(Gtk.Align.END)
        self.handle.set_cursor_from_name("nwse-resize")
        self.handle.set_tooltip_text("Перетащите, чтобы изменить размер изображения")
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.set_exclusive(True)
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag.connect("begin", lambda gesture, _sequence:
                     gesture.set_state(Gtk.EventSequenceState.CLAIMED))
        drag.connect("drag-begin", self._resize_begin)
        drag.connect("drag-update", self._resize_update)
        drag.connect("drag-end", self._resize_end)
        drag.connect("cancel", self._resize_end)
        self.handle.add_controller(drag)
        self.add_overlay(self.handle)
        self.set_measure_overlay(self.handle, False)

        self.delete_button = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
        self.delete_button.add_css_class("flat")
        self.delete_button.add_css_class("image-delete-button")
        self.delete_button.set_tooltip_text("Удалить изображение из заметки")
        self.delete_button.set_halign(Gtk.Align.END)
        self.delete_button.set_valign(Gtk.Align.START)
        self.delete_button.connect("clicked", lambda *_: delete())
        self.add_overlay(self.delete_button)
        self.set_measure_overlay(self.delete_button, False)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_hovered(True))
        motion.connect("leave", lambda *_: self._set_hovered(False))
        self.add_controller(motion)
        self._update_size()
        self._update_controls()

    def to_node(self) -> dict:
        return make_image(self.attachment_id, self.width)

    def set_available_width(self, width: int):
        width = max(1, width)
        if width != self._available_width:
            self._available_width = width
            self._update_size()

    def _update_size(self):
        display_width = min(self.width, self._available_width)
        height = max(1, round(display_width * self.natural_height / self.natural_width))
        if self.surface is not None:
            self.picture.set_content_width(display_width)
            self.picture.set_content_height(height)
            self.picture.queue_draw()
        self.picture.set_size_request(display_width, height)

    def _draw_image(self, _area, cr, width, height):
        cr.save()
        cr.scale(width / self.natural_width, height / self.natural_height)
        cr.set_source_surface(self.surface, 0, 0)
        cr.paint()
        cr.restore()

    def _set_hovered(self, hovered: bool):
        self._hovered = hovered
        self._update_controls()

    def _update_controls(self):
        visible = self._hovered or self._dragging
        self.handle.set_visible(visible)
        self.delete_button.set_visible(visible)

    def _resize_begin(self, gesture, _x, _y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._dragging = True
        self._starting_width = self.width
        self._update_controls()

    def _resize_update(self, _gesture, offset_x, _offset_y):
        width = max(80, min(1600, round(self._starting_width + offset_x)))
        width = min(width, self._available_width)
        if width != self.width:
            self.width = width
            self._update_size()

    def _resize_end(self, *_args):
        self._dragging = False
        self._update_controls()
        self.changed()
