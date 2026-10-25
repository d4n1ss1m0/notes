"""Editable hashtags with rounded backgrounds drawn beneath the original text."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Graphene, Gsk, Gtk

from .storage import TAG_PATTERN


def tag_spans(text):
    """Offsets include # and preserve the original Unicode text's positions."""
    return [match.span() for match in TAG_PATTERN.finditer(text)]


def tag_rectangles(view, start, end):
    """Combine glyph boxes by visual row, including wrapped and RTL text."""
    rows = {}
    buffer = view.get_buffer()
    for offset in range(start, end):
        box = view.get_iter_location(buffer.get_iter_at_offset(offset))
        left, right = sorted((box.x, box.x + box.width))
        key = (box.y, box.height)
        if key in rows:
            old_left, old_right = rows[key]
            rows[key] = min(left, old_left), max(right, old_right)
        else:
            rows[key] = left, right
    return [(left - 2, y, right - left + 4, height)
            for (y, height), (left, right) in rows.items()]


class TagTextView(Gtk.TextView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tag_spans = []
        self.get_buffer().connect("changed", self._update_tags)

    def _update_tags(self, buffer):
        # get_slice keeps anchor characters, so offsets match Gtk.TextIter.
        self._tag_spans = tag_spans(buffer.get_slice(*buffer.get_bounds(), True))
        self.queue_draw()

    def do_snapshot_layer(self, layer, snapshot):
        if layer != Gtk.TextViewLayer.BELOW_TEXT:
            return
        found, accent = self.get_style_context().lookup_color("accent_bg_color")
        if not found:
            accent = self.get_style_context().get_color()
        color = Gdk.RGBA()
        color.red, color.green, color.blue, color.alpha = accent.red, accent.green, accent.blue, 0.20
        visible = self.get_visible_rect()
        for start, end in self._tag_spans:
            for x, y, width, height in tag_rectangles(self, start, end):
                if y + height < visible.y or y > visible.y + visible.height:
                    continue
                bounds = Graphene.Rect().init(x, y, width, height)
                rounded = Gsk.RoundedRect()
                rounded.init_from_rect(bounds, 4)
                snapshot.push_rounded_clip(rounded)
                snapshot.append_color(color, bounds)
                snapshot.pop()
