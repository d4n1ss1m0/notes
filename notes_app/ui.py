"""GTK window for Notes."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .storage import NotesStore
from .pane_layout import PaneLayout
from .rich_editor import RichEditor
from .tag_text_view import TagTextView


TRASH = "__trash__"


def icon_button(name: str, tooltip: str, callback) -> Gtk.Button:
    button = Gtk.Button.new_from_icon_name(name)
    button.set_tooltip_text(tooltip)
    button.add_css_class("flat")
    button.connect("clicked", callback)
    return button


def format_glyph(kind: str) -> Gtk.DrawingArea:
    """Draw the compact list/table symbols in the current text color."""
    area = Gtk.DrawingArea()
    area.set_content_width(18)
    area.set_content_height(18)

    def draw(widget, cr, width, height):
        color = widget.get_style_context().get_color()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(1.35)
        cr.set_line_cap(1)
        cr.translate((width - 18) / 2, (height - 18) / 2)
        if kind == "list":
            for y in (5, 13):
                cr.arc(3.5, y, 1.6, 0, 6.283185307179586)
                cr.stroke()
                cr.move_to(8, y)
                cr.line_to(16, y)
                cr.stroke()
        elif kind == "table":
            cr.rectangle(1.5, 2.5, 15, 13)
            cr.move_to(1.5, 6.8)
            cr.line_to(16.5, 6.8)
            cr.move_to(1.5, 11.2)
            cr.line_to(16.5, 11.2)
            for x in (6.5, 11.5):
                cr.move_to(x, 2.5)
                cr.line_to(x, 15.5)
            cr.stroke()
        else:
            cr.rectangle(1.5, 2.5, 15, 13)
            cr.stroke()
            cr.arc(6, 6.5, 1.2, 0, 6.283185307179586)
            cr.stroke()
            cr.move_to(2, 14)
            cr.line_to(7, 9)
            cr.line_to(10, 12)
            cr.line_to(12, 10)
            cr.line_to(16, 14)
            cr.stroke()

    area.set_draw_func(draw)
    return area


def label(text: str, css_class: str | None = None) -> Gtk.Label:
    item = Gtk.Label(label=text, xalign=0)
    if css_class:
        item.add_css_class(css_class)
    return item


def clear_list(box: Gtk.ListBox):
    while child := box.get_first_child():
        box.remove(child)


def date_caption(value: str) -> str:
    when = datetime.fromisoformat(value).astimezone()
    if when.date() == datetime.now().date():
        return when.strftime("%H:%M")
    return when.strftime("%d.%m.%Y")


class NotesWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: NotesStore):
        super().__init__(application=app, title="Notes", default_width=1150, default_height=720)
        self.store = store
        self.folder_id = None
        self.tag = None
        self.note_id = None
        self._loading = False
        self._dirty = False
        self._refreshing = False
        self._syncing_style = False
        self._save_source = None
        config_root = Path(os.environ.get("NOTES_CONFIG_DIR", GLib.get_user_config_dir()))
        self._pane_layout = PaneLayout(config_root / "notes" / "window.json")
        self._layout_save_source = None
        self.set_size_request(800, 500)
        self._build_ui()
        self._refresh_folders()
        self._refresh_notes()
        self.connect("close-request", self._on_close)

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay = Adw.ToastOverlay()
        self.overlay.set_child(root)
        self.set_content(self.overlay)

        self.folders_header = Adw.HeaderBar()
        self.folders_header.add_css_class("folders-header")
        self.folders_header.set_show_end_title_buttons(False)
        self.folders_header.set_title_widget(label("Notes", "app-title"))
        self.folders_header.pack_start(icon_button("system-search-symbolic", "Поиск (Ctrl+F)",
                                                   lambda *_: self.search.grab_focus()))
        folder_menu = Gtk.MenuButton(icon_name="open-menu-symbolic")
        folder_menu.add_css_class("flat")
        folder_menu.set_tooltip_text("Меню")
        menu_popover = Gtk.Popover()
        menu_actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu_actions.add_css_class("header-menu")
        for title, callback in (("Новая заметка", self._new_note), ("Новая папка", self._new_folder)):
            action = Gtk.Button(label=title)
            action.add_css_class("flat")
            action.connect("clicked", lambda _button, handler=callback: (menu_popover.popdown(), handler()))
            menu_actions.append(action)
        menu_popover.set_child(menu_actions)
        folder_menu.set_popover(menu_popover)
        self.folders_header.pack_end(folder_menu)

        self.notes_header = Adw.HeaderBar()
        self.notes_header.add_css_class("list-header")
        self.notes_header.set_show_start_title_buttons(False)
        self.notes_header.set_show_end_title_buttons(False)
        self.header_folder_label = label("Все заметки", "header-section-title")
        self.header_folder_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.header_folder_label.set_max_width_chars(22)
        self.notes_header.set_title_widget(self.header_folder_label)
        self.new_note_button = icon_button("list-add-symbolic", "Новая заметка (Ctrl+N)", self._new_note)
        self.notes_header.pack_end(self.new_note_button)

        self.editor_header = Adw.HeaderBar()
        self.editor_header.add_css_class("content-header")
        self.editor_header.set_hexpand(True)
        self.editor_header.set_show_start_title_buttons(False)
        self.editor_header.set_show_title(False)
        header_heights = Gtk.SizeGroup.new(Gtk.SizeGroupMode.VERTICAL)
        for section in (self.folders_header, self.notes_header, self.editor_header):
            header_heights.add_widget(section)

        self.folders_pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, vexpand=True)
        self.folders_pane.add_css_class("folders-divider")
        self.folders_pane.set_wide_handle(False)
        self.folders_pane.set_resize_start_child(False)
        self.folders_pane.set_shrink_start_child(False)
        self.folders_pane.set_shrink_end_child(False)
        root.append(self.folders_pane)

        self.notes_pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, vexpand=True)
        self.notes_pane.add_css_class("notes-divider")
        self.notes_pane.set_wide_handle(False)
        self.notes_pane.set_resize_start_child(False)
        self.notes_pane.set_shrink_start_child(False)
        self.notes_pane.set_shrink_end_child(False)
        self.folders_pane.set_end_child(self.notes_pane)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.set_size_request(180, -1)
        sidebar.add_css_class("folders-panel")
        self.folders_pane.set_start_child(sidebar)
        sidebar.append(self.folders_header)
        sidebar.append(label("ПАПКИ", "section-title"))
        folder_scroll = Gtk.ScrolledWindow(vexpand=True)
        folder_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar.append(folder_scroll)
        self.folder_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.folder_list.add_css_class("navigation-list")
        self.folder_list.connect("row-selected", self._on_folder_selected)
        navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        folder_scroll.set_child(navigation)
        navigation.append(self.folder_list)
        self.tags_section = Gtk.Expander(label="Теги")
        self.tags_section.add_css_class("tags-section")
        self.tags_section.set_expanded(self._pane_layout.tags_expanded)
        self.tags_section.connect("notify::expanded", self._on_tags_expanded)
        navigation.append(self.tags_section)
        self.tag_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.tag_list.add_css_class("navigation-list")
        self.tag_list.connect("row-selected", self._on_tag_selected)
        self.tags_section.set_child(self.tag_list)
        folder_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        folder_actions.add_css_class("folder-actions")
        sidebar.append(folder_actions)
        self.add_folder_button = icon_button("list-add-symbolic", "Создать папку", self._new_folder)
        self.rename_folder_button = icon_button("document-edit-symbolic", "Переименовать папку", self._rename_folder)
        self.delete_folder_button = icon_button("edit-delete-symbolic", "Удалить папку", self._delete_folder)
        folder_actions.append(self.add_folder_button)
        folder_actions.append(label("Новая папка", "action-caption"))
        spacer = Gtk.Box(hexpand=True)
        folder_actions.append(spacer)
        folder_actions.append(self.rename_folder_button)
        folder_actions.append(self.delete_folder_button)
        notes_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        notes_panel.set_size_request(250, -1)
        notes_panel.add_css_class("notes-panel")
        self.notes_pane.set_start_child(notes_panel)
        notes_panel.append(self.notes_header)
        self.search = Gtk.SearchEntry(placeholder_text="Поиск заметок")
        self.search.add_css_class("notes-search")
        self.search.connect("search-changed", self._on_search_changed)
        notes_panel.append(self.search)
        search_divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        search_divider.add_css_class("notes-subheader-divider")
        notes_panel.append(search_divider)
        notes_scroll = Gtk.ScrolledWindow(vexpand=True)
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        notes_panel.append(notes_scroll)
        self.note_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.note_list.add_css_class("notes-list")
        self.note_list.connect("row-selected", self._on_note_selected)
        notes_scroll.set_child(self.note_list)
        editor_overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        self.notes_pane.set_end_child(editor_overlay)
        editor_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        editor_column.set_size_request(360, -1)
        editor_overlay.set_child(editor_column)
        editor_boundary = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        editor_boundary.add_css_class("editor-boundary")
        editor_boundary.set_halign(Gtk.Align.START)
        editor_boundary.set_valign(Gtk.Align.FILL)
        editor_boundary.set_can_target(False)
        editor_overlay.add_overlay(editor_boundary)
        editor_column.append(self.editor_header)
        self.editor_stack = Gtk.Stack(hexpand=True, vexpand=True)
        self.editor_stack.add_css_class("editor-stack")
        editor_column.append(self.editor_stack)
        empty = Adw.StatusPage(title="Выберите заметку", description="Или создайте новую заметку с помощью кнопки сверху.",
                               icon_name="accessories-text-editor-symbolic")
        empty_new_note_button = Gtk.Button(label="Создать заметку", halign=Gtk.Align.CENTER)
        empty_new_note_button.add_css_class("suggested-action")
        empty_new_note_button.connect("clicked", self._new_note)
        empty.set_child(empty_new_note_button)
        self.editor_stack.add_named(empty, "empty")
        editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor.add_css_class("editor-panel")
        self.editor_stack.add_named(editor, "editor")

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar.add_css_class("editor-date-row")
        self.updated_label = label("", "date-label")
        self.updated_label.set_hexpand(True)
        self.updated_label.set_xalign(0.5)
        toolbar.append(self.updated_label)
        self.pin_button = icon_button("view-pin-symbolic", "Закрепить заметку", self._toggle_pin)
        self.move_button = icon_button("folder-symbolic", "Переместить в папку", self._move_note)
        self.trash_button = icon_button("user-trash-symbolic", "В корзину", self._trash_or_restore)
        self.erase_button = icon_button("edit-delete-symbolic", "Удалить навсегда", self._delete_forever)
        self.erase_button.set_visible(False)
        for button in (self.pin_button, self.move_button, self.trash_button, self.erase_button):
            button.set_sensitive(False)
            self.editor_header.pack_end(button)
        editor.append(toolbar)

        formatting = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        formatting.add_css_class("header-formatting")
        self.formatting_toolbar = formatting
        self.paragraph_style = Gtk.MenuButton()
        self.paragraph_style.set_child(Gtk.Label(label="Aa"))
        self.paragraph_style.add_css_class("flat")
        self.paragraph_style.add_css_class("format-icon-button")
        self.paragraph_style.set_tooltip_text("Стиль абзаца")
        style_popover = Gtk.Popover()
        style_items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        style_items.add_css_class("format-menu")
        for caption, kind in (
            ("Обычный текст", "paragraph"), ("Заголовок", "heading1"),
            ("Подзаголовок", "heading2"), ("Малый заголовок", "heading3"),
        ):
            item = Gtk.Button(label=caption, halign=Gtk.Align.FILL)
            item.add_css_class("flat")
            item.connect("clicked", lambda _button, value=kind: (
                self.rich_editor.set_kind(value), style_popover.popdown()))
            style_items.append(item)
        style_popover.set_child(style_items)
        self.paragraph_style.set_popover(style_popover)
        formatting.append(self.paragraph_style)
        list_button = Gtk.MenuButton()
        list_button.set_child(format_glyph("list"))
        list_button.add_css_class("flat")
        list_button.add_css_class("format-icon-button")
        list_button.set_tooltip_text("Создать список")
        list_popover = Gtk.Popover()
        list_items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        list_items.add_css_class("format-menu")
        for caption, kind in (
            ("Маркированный список", "bullet"),
            ("Нумерованный список", "number"),
            ("Список задач", "todo"),
        ):
            item = Gtk.Button(label=caption, halign=Gtk.Align.FILL)
            item.add_css_class("flat")
            item.connect("clicked", lambda _button, value=kind: (
                self.rich_editor.toggle_task() if value == "todo" else self.rich_editor.set_kind(value),
                list_popover.popdown()))
            list_items.append(item)
        list_popover.set_child(list_items)
        list_button.set_popover(list_popover)
        formatting.append(list_button)
        self.table_button = Gtk.Button()
        self.table_button.set_child(format_glyph("table"))
        self.table_button.set_tooltip_text("Вставить таблицу")
        self.table_button.add_css_class("flat")
        self.table_button.connect("clicked", self._insert_table)
        self.table_button.add_css_class("format-icon-button")
        formatting.append(self.table_button)
        self.image_button = Gtk.Button()
        self.image_button.set_child(format_glyph("image"))
        self.image_button.set_tooltip_text("Вставить изображение из файла")
        self.image_button.add_css_class("flat")
        self.image_button.add_css_class("format-icon-button")
        self.image_button.connect("clicked", self._choose_image)
        formatting.append(self.image_button)
        self.editor_header.pack_start(formatting)
        formatting.set_sensitive(False)

        self.title_entry = Gtk.Entry(placeholder_text="Название заметки")
        self.title_entry.add_css_class("note-title")
        self.title_entry.connect("changed", self._schedule_save)
        editor.append(self.title_entry)
        body_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        body_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        editor.append(body_scroll)
        self.text_view = TagTextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=4, bottom_margin=30,
                                      left_margin=30, right_margin=30, vexpand=True)
        self.text_view.add_css_class("note-body")
        self.text_buffer = self.text_view.get_buffer()
        self.text_buffer.set_enable_undo(True)
        self.rich_editor = RichEditor(self.text_view, self._schedule_save, self.store.attachment_path)
        paste_controller = Gtk.EventControllerKey()
        paste_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        paste_controller.connect("key-pressed", self._on_editor_paste)
        self.text_view.add_controller(paste_controller)
        self.text_buffer.connect("mark-set", self._sync_paragraph_style)
        body_scroll.set_child(self.text_view)
        self.editor_stack.set_visible_child_name("empty")
        self.folders_pane.set_position(self._pane_layout.widths["folders"])
        self.notes_pane.set_position(self._pane_layout.widths["notes"])
        self.folders_pane.connect("notify::position", self._on_pane_position, "folders")
        self.notes_pane.connect("notify::position", self._on_pane_position, "notes")

    def _insert_table(self, *_args):
        if self.note_id is not None:
            self.rich_editor.insert_table()

    def _choose_image(self, *_args):
        if self.note_id is None:
            return
        note_id = self.note_id
        chooser = Gtk.FileDialog(title="Вставить изображение")
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Изображения")
        for mime in ("image/png", "image/jpeg", "image/webp", "image/gif",
                     "image/bmp", "image/tiff", "image/avif"):
            image_filter.add_mime_type(mime)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        chooser.set_filters(filters)
        chooser.open(self, None, lambda dialog, result:
                     self._image_chosen(dialog, result, note_id))

    def _image_chosen(self, dialog, result, note_id):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if self.note_id != note_id:
            return
        try:
            raw, _etag = file.load_bytes(None)
            texture = Gdk.Texture.new_from_bytes(raw)
            self._insert_texture(texture, note_id)
        except (GLib.Error, OSError, ValueError) as error:
            self._toast(f"Не удалось открыть изображение: {error}")

    def _on_editor_paste(self, _controller, keyval, _keycode, modifiers):
        if self.note_id is None or not self.text_view.get_editable() or not self.text_view.has_focus():
            return False
        if keyval not in (Gdk.KEY_v, Gdk.KEY_V):
            return False
        if not modifiers & Gdk.ModifierType.CONTROL_MASK or modifiers & (
            Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK
        ):
            return False
        clipboard = self.get_display().get_clipboard()
        formats = clipboard.get_formats()
        mime_types = formats.get_mime_types() or []
        if not (formats.contain_gtype(Gdk.Texture.__gtype__) or
                any(mime.startswith("image/") for mime in mime_types)):
            return False
        note_id = self.note_id
        clipboard.read_texture_async(None, lambda source, result:
                                     self._image_pasted(source, result, note_id))
        return True

    def _image_pasted(self, clipboard, result, note_id):
        if self.note_id != note_id:
            return
        try:
            texture = clipboard.read_texture_finish(result)
            if texture is None:
                raise ValueError("Изображение не найдено в буфере")
        except (GLib.Error, OSError, ValueError):
            self.text_buffer.paste_clipboard(clipboard, None, True)
            return
        try:
            self._insert_texture(texture, note_id)
        except (GLib.Error, OSError, ValueError) as error:
            self._toast(f"Не удалось вставить изображение: {error}")

    def _insert_texture(self, texture, note_id):
        if self.note_id != note_id or not self.text_view.get_editable():
            return
        png_data = texture.save_to_png_bytes().get_data()
        attachment_id = self.store.save_attachment(png_data)
        width = min(texture.get_width(), self.rich_editor.available_content_width())
        self.rich_editor.insert_image(attachment_id, width)

    def _sync_paragraph_style(self, *_args):
        if self._loading or self.note_id is None:
            return
        kinds = ("paragraph", "heading1", "heading2", "heading3")
        kind = self.rich_editor.current_kind()
        captions = ("Обычный текст", "Заголовок", "Подзаголовок", "Малый заголовок")
        self.paragraph_style.set_tooltip_text(captions[kinds.index(kind)] if kind in kinds else "Стиль абзаца")

    def _on_pane_position(self, pane, _property, column):
        position = pane.get_position()
        if position <= 0:
            return
        bounded = self._pane_layout.set_width(column, position)
        if position != bounded:
            pane.set_position(bounded)
            return
        if self._layout_save_source is not None:
            GLib.source_remove(self._layout_save_source)
        self._layout_save_source = GLib.timeout_add(350, self._save_pane_layout)

    def _save_pane_layout(self):
        self._layout_save_source = None
        self._pane_layout.save()
        return GLib.SOURCE_REMOVE

    def _toast(self, message: str):
        self.overlay.add_toast(Adw.Toast.new(message))

    def _on_tags_expanded(self, expander, _property):
        self._pane_layout.tags_expanded = expander.get_expanded()
        self._pane_layout.save()

    def _on_tag_selected(self, _box, row):
        if self._refreshing or row is None:
            return
        selected_tag = row.tag
        self._flush_save(refresh=False)
        self.tag = selected_tag
        self.folder_id = None
        self.note_id = None
        self._refresh_folders()
        self._refresh_notes()

    def _folder_row(self, text: str, count: int, icon: str, folder_id, depth=0):
        row = Gtk.ListBoxRow()
        row.folder_id = folder_id
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        inner.add_css_class("folder-row")
        inner.set_margin_start(min(depth, 5) * 15)
        inner.append(Gtk.Image.new_from_icon_name(icon))
        title = label(text)
        title.set_hexpand(True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        inner.append(title)
        count_label = label(str(count), "count-label")
        inner.append(count_label)
        row.set_child(inner)
        self.folder_list.append(row)
        return row

    def _refresh_folders(self):
        self._refreshing = True
        clear_list(self.folder_list)
        active_count, trash_count = self.store.counts()
        rows = {None: self._folder_row("Все заметки", active_count, "view-list-symbolic", None)}
        folders = self.store.folders()
        children = {}
        for folder in folders:
            children.setdefault(folder["parent_id"], []).append(folder)

        def add_children(parent_id, depth):
            for folder in children.get(parent_id, []):
                rows[folder["id"]] = self._folder_row(
                    folder["name"], folder["note_count"], "folder-symbolic", folder["id"], depth
                )
                add_children(folder["id"], depth + 1)

        add_children(None, 0)
        rows[TRASH] = self._folder_row("Корзина", trash_count, "user-trash-symbolic", TRASH)
        if self.folder_id not in rows:
            self.folder_id = None
        self.folder_list.select_row(rows[self.folder_id] if self.tag is None else None)
        clear_list(self.tag_list)
        for tag in self.store.tags():
            row = Gtk.ListBoxRow()
            row.tag = tag["tag"]
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            inner.add_css_class("folder-row")
            title = label("#" + row.tag)
            title.set_hexpand(True)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            inner.append(title)
            inner.append(label(str(tag["note_count"]), "count-label"))
            row.set_child(inner)
            self.tag_list.append(row)
            if row.tag == self.tag:
                self.tag_list.select_row(row)
        self._refreshing = False
        folder = self.store.folder(self.folder_id) if self.folder_id not in (None, TRASH) else None
        editable = folder is not None and not folder["is_default"]
        self.rename_folder_button.set_sensitive(editable)
        self.delete_folder_button.set_sensitive(editable)
        self.header_folder_label.set_text("#" + self.tag if self.tag is not None else "Корзина" if self.folder_id == TRASH else folder["name"] if folder else "Все заметки")

    def _refresh_notes(self, *, preferred=None):
        self._refreshing = True
        current = preferred if preferred is not None else self.note_id
        clear_list(self.note_list)
        rows = {}
        for note in self.store.notes(None if self.folder_id in (None, TRASH) else self.folder_id,
                                     trash=self.folder_id == TRASH, query=self.search.get_text(), tag=self.tag):
            row = Gtk.ListBoxRow()
            row.note_id = note["id"]
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            content.add_css_class("note-row")
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
            title = label(("● " if note["pinned"] and self.folder_id != TRASH else "") +
                          (note["title"].strip() or "Новая заметка"), "note-row-title")
            title.set_hexpand(True)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            top.append(title)
            top.append(label(date_caption(note["updated_at"]), "note-row-date"))
            content.append(top)
            preview = " ".join(note["body"].split()) or "Нет дополнительного текста"
            excerpt = label(preview, "note-row-preview")
            excerpt.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(excerpt)
            row.set_child(content)
            self.note_list.append(row)
            rows[note["id"]] = row
        selected = rows.get(current) or (next(iter(rows.values())) if rows else None)
        self.note_list.select_row(selected)
        self._refreshing = False
        self._show_note(selected.note_id if selected else None)

    def _show_note(self, note_id):
        if note_id == self.note_id and note_id is not None:
            return False
        saved_previous = self._flush_save(refresh=False)
        self.note_id = note_id
        if note_id is None:
            self.editor_stack.set_visible_child_name("empty")
            self.formatting_toolbar.set_sensitive(False)
            for button in (self.pin_button, self.move_button, self.trash_button, self.erase_button):
                button.set_sensitive(False)
            return saved_previous
        note = self.store.note(note_id)
        if note is None:
            self.editor_stack.set_visible_child_name("empty")
            return saved_previous
        self._loading = True
        self.title_entry.set_text(note["title"])
        self.rich_editor.load(note["content_json"], note["body"])
        self.paragraph_style.set_tooltip_text("Стиль абзаца")
        self._loading = False
        self._dirty = False
        trashed = note["deleted_at"] is not None
        self.title_entry.set_sensitive(not trashed)
        self.text_view.set_editable(not trashed)
        self.rich_editor.set_editable(not trashed)
        self.formatting_toolbar.set_sensitive(not trashed)
        for button in (self.pin_button, self.move_button, self.trash_button, self.erase_button):
            button.set_sensitive(True)
        self.pin_button.set_visible(not trashed)
        self.move_button.set_visible(not trashed)
        self.erase_button.set_visible(trashed)
        self.trash_button.set_icon_name("edit-undo-symbolic" if trashed else "user-trash-symbolic")
        self.trash_button.set_tooltip_text("Восстановить" if trashed else "В корзину")
        self.pin_button.set_tooltip_text("Открепить" if note["pinned"] else "Закрепить")
        self.pin_button.set_icon_name("view-pin-symbolic" if note["pinned"] else "view-pin-symbolic")
        self.updated_label.set_text("Изменено " + date_caption(note["updated_at"]))
        self.editor_stack.set_visible_child_name("editor")
        return saved_previous

    def _on_folder_selected(self, _box, row):
        if self._refreshing or row is None:
            return
        selected_folder = row.folder_id
        self._flush_save(refresh=False)
        self.tag = None
        self.folder_id = selected_folder
        self.note_id = None
        self._refresh_folders()
        self._refresh_notes()

    def _on_note_selected(self, _box, row):
        if not self._refreshing:
            note_id = row.note_id if row else None
            if self._show_note(note_id):
                self._refresh_notes(preferred=note_id)
                self._refresh_folders()

    def _on_search_changed(self, _entry):
        self._flush_save(refresh=False)
        self._refresh_notes()

    def _schedule_save(self, *_args):
        if self._loading or self.note_id is None:
            return
        self._dirty = True
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(450, self._on_save_timeout)

    def _on_save_timeout(self):
        self._flush_save(from_timer=True)
        return GLib.SOURCE_REMOVE

    def _flush_save(self, *, from_timer=False, refresh=True):
        if self._save_source is not None and not from_timer:
            GLib.source_remove(self._save_source)
        self._save_source = None
        if self.note_id is None or self._loading or not self._dirty:
            return False
        note = self.store.note(self.note_id)
        if note is None or note["deleted_at"] is not None:
            self._dirty = False
            return False
        title = self.title_entry.get_text()
        body, content_json = self.rich_editor.snapshot()
        self._dirty = False
        if title != note["title"] or body != note["body"] or content_json != note["content_json"]:
            self.store.save_note(self.note_id, title, body, content_json)
            self.updated_label.set_text("Изменено " + date_caption(self.store.note(self.note_id)["updated_at"]))
            if refresh:
                self._refresh_notes(preferred=self.note_id)
                self._refresh_folders()
            return True
        return False

    def _prompt(self, title: str, initial: str, callback):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dialog.add_button("Сохранить", Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=initial, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        entry.set_activates_default(True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.get_content_area().append(entry)

        def respond(_dialog, response):
            value = entry.get_text().strip()
            dialog.destroy()
            if response == Gtk.ResponseType.OK:
                try:
                    callback(value)
                except ValueError as error:
                    self._toast(str(error))

        dialog.connect("response", respond)
        dialog.present()
        entry.grab_focus()

    def _confirm(self, title: str, body: str, callback):
        dialog = Adw.AlertDialog.new(title, body)
        dialog.add_response("cancel", "Отмена")
        dialog.add_response("confirm", "Удалить")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _dialog, response: callback() if response == "confirm" else None)
        dialog.present(self)

    def _new_folder(self, *_args):
        parent = self.folder_id if self.folder_id not in (None, TRASH) else None

        def create(name):
            self._flush_save(refresh=False)
            self.tag = None
            self.folder_id = self.store.create_folder(name, parent)
            self.note_id = None
            self._refresh_folders()
            self._refresh_notes()

        self._prompt("Новая папка", "", create)

    def _rename_folder(self, *_args):
        folder = self.store.folder(self.folder_id) if self.folder_id not in (None, TRASH) else None
        if folder is None or folder["is_default"]:
            return

        def rename(name):
            self.store.rename_folder(folder["id"], name)
            self._refresh_folders()

        self._prompt("Переименовать папку", folder["name"], rename)

    def _delete_folder(self, *_args):
        folder = self.store.folder(self.folder_id) if self.folder_id not in (None, TRASH) else None
        if folder is None or folder["is_default"]:
            return

        def delete():
            self._flush_save(refresh=False)
            self.store.delete_folder(folder["id"])
            self.folder_id = None
            self.note_id = None
            self._refresh_folders()
            self._refresh_notes()
            self._toast("Заметки перенесены в папку «Заметки»")

        self._confirm("Удалить папку?", "Заметки из неё и вложенных папок будут перенесены в папку «Заметки».", delete)

    def _new_note(self, *_args):
        self._flush_save(refresh=False)
        self.tag = None
        if self.folder_id == TRASH:
            self.folder_id = None
            self._refresh_folders()
        if self.search.get_text():
            self.search.set_text("")
        note_id = self.store.create_note(self.folder_id)
        self.note_id = None
        self._refresh_notes(preferred=note_id)
        self._refresh_folders()
        self.title_entry.grab_focus()

    def _toggle_pin(self, *_args):
        if self.note_id is None:
            return
        self._flush_save(refresh=False)
        note = self.store.note(self.note_id)
        self.store.set_pinned(self.note_id, not note["pinned"])
        self.pin_button.set_tooltip_text("Открепить" if not note["pinned"] else "Закрепить")
        self._refresh_notes(preferred=self.note_id)

    def _move_note(self, *_args):
        if self.note_id is None:
            return
        folders = self.store.folders()
        names = {folder["id"]: folder for folder in folders}

        def path(folder):
            parts = [folder["name"]]
            parent = folder["parent_id"]
            while parent in names:
                parts.insert(0, names[parent]["name"])
                parent = names[parent]["parent_id"]
            return " / ".join(parts)

        dialog = Gtk.Dialog(title="Переместить заметку", transient_for=self, modal=True)
        dialog.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dialog.add_button("Переместить", Gtk.ResponseType.OK)
        dropdown = Gtk.DropDown.new_from_strings([path(folder) for folder in folders])
        dropdown.set_margin_top(16)
        dropdown.set_margin_bottom(16)
        dropdown.set_margin_start(16)
        dropdown.set_margin_end(16)
        dialog.get_content_area().append(dropdown)
        current_folder = self.store.note(self.note_id)["folder_id"]
        dropdown.set_selected(next((i for i, folder in enumerate(folders) if folder["id"] == current_folder), 0))
        note_id = self.note_id

        def respond(_dialog, response):
            index = dropdown.get_selected()
            dialog.destroy()
            if response == Gtk.ResponseType.OK and index < len(folders):
                self._flush_save(refresh=False)
                self.store.move_note(note_id, folders[index]["id"])
                self._refresh_folders()
                self._refresh_notes()

        dialog.connect("response", respond)
        dialog.present()

    def _trash_or_restore(self, *_args):
        if self.note_id is None:
            return
        self._flush_save(refresh=False)
        note = self.store.note(self.note_id)
        if note["deleted_at"] is None:
            self.store.trash_note(self.note_id)
        else:
            self.store.restore_note(self.note_id)
        self.note_id = None
        self._refresh_folders()
        self._refresh_notes()

    def _delete_forever(self, *_args):
        if self.note_id is None or self.folder_id != TRASH:
            return
        note_id = self.note_id

        def delete():
            self.store.delete_note_forever(note_id)
            self.note_id = None
            self._refresh_folders()
            self._refresh_notes()

        self._confirm("Удалить заметку навсегда?", "Это действие нельзя отменить.", delete)

    def _on_close(self, *_args):
        self._flush_save(refresh=False)
        if self._layout_save_source is not None:
            GLib.source_remove(self._layout_save_source)
            self._layout_save_source = None
        self._pane_layout.save()
        return False


def install_css():
    from pathlib import Path

    provider = Gtk.CssProvider()
    provider.load_from_path(str(Path(__file__).with_name("style.css")))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
