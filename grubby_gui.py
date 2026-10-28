#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
grubby-gui — графическая оболочка для grubby (управление загрузчиком GRUB2).
Интерфейс на GTK 4 (4.6+). Вся логика — в grubby_core.py.
"""

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

import grubby_core as core  # noqa: E402
from grubby_core import arg_key, format_cmd, split_args  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
#  Оформление
# ═══════════════════════════════════════════════════════════════════════════
CSS = """
.entry-title { font-size: 1.45em; font-weight: bold; }
.section-title { font-weight: bold; font-size: 1.08em; }
.dim { opacity: 0.62; }
.mono { font-family: monospace; }
.star { color: #e5a50a; font-size: 1.2em; }

.badge { border-radius: 99px; padding: 1px 8px; font-size: 0.82em; font-weight: bold; }
.badge-default { background-color: #3584e4; color: #ffffff; }
.badge-running { background-color: #26a269; color: #ffffff; }
.badge-rescue  { background-color: #c64600; color: #ffffff; }

.chip { border-radius: 99px; padding: 1px 3px 1px 11px;
        border: 1px solid alpha(currentColor, 0.22);
        background-color: alpha(currentColor, 0.05); }
.chip label { font-family: monospace; }
.chip button { min-height: 20px; min-width: 20px; padding: 0; margin: 1px; border-radius: 99px; }
.chip-added   { background-color: alpha(#2ec27e, 0.20); border-color: #2ec27e; }
.chip-removed { background-color: alpha(#e01b24, 0.12); border-color: alpha(#e01b24, 0.7); }
.chip-root    { background-color: alpha(#3584e4, 0.12); border-color: alpha(#3584e4, 0.6);
                padding: 2px 11px; }

.cmd-preview { font-family: monospace; padding: 8px 12px; border-radius: 6px;
               background-color: alpha(currentColor, 0.07); }
.side-header { font-weight: bold; font-size: 0.86em; padding: 10px 12px 4px 12px; opacity: 0.7; }
.preset-name { font-family: monospace; font-weight: bold; }
.preset-cat  { font-weight: bold; font-size: 0.86em; opacity: 0.7; padding: 8px 10px 2px 10px; }
.props { border: 1px solid alpha(currentColor, 0.15); border-radius: 8px; padding: 12px; }

.msgbar { padding: 6px 8px 6px 14px; }
.msgbar.info    { background-color: alpha(#3584e4, 0.16); }
.msgbar.success { background-color: alpha(#2ec27e, 0.20); }
.msgbar.error   { background-color: alpha(#e01b24, 0.18); }
.msgbar.warning { background-color: alpha(#e5a50a, 0.22); }

.banner { padding: 10px 14px; background-color: alpha(#e5a50a, 0.22);
          border-bottom: 1px solid alpha(#e5a50a, 0.5); }
.banner-title { font-weight: bold; }

.dlg-title { font-weight: bold; font-size: 1.2em; }
.dlg-buttons button { min-height: 34px; }
.toolbar { padding: 6px; }
"""


# Кто рисует рамку окна. В GNOME — сам GTK (HeaderBar с кнопками в заголовке).
# В KDE/LXQt — оконный менеджер: стоит GTK-окну задать свой заголовок, GTK
# переходит на клиентские декорации, и в KWin окно плохо растягивается за края.
# Без своего заголовка GTK 4 отдаёт рамку KWin (Wayland и X11), а кнопки
# переезжают на панель внутри окна. Переопределение: GRUBBY_GUI_CSD=1 или 0.
def detect_csd():
    env = os.environ.get("GRUBBY_GUI_CSD")
    if env in ("0", "1"):
        return env == "1"
    desk = ":".join((os.environ.get("XDG_CURRENT_DESKTOP", ""),
                     os.environ.get("XDG_SESSION_DESKTOP", ""),
                     os.environ.get("DESKTOP_SESSION", ""))).lower()
    return not any(k in desk for k in ("kde", "plasma", "lxqt"))


USE_CSD = detect_csd()


def add_css(css, priority):
    prov = Gtk.CssProvider()
    if hasattr(prov, "load_from_string"):          # GTK 4.12+
        prov.load_from_string(css)
    else:
        try:
            prov.load_from_data(css.encode("utf-8"))
        except TypeError:
            prov.load_from_data(css, -1)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, priority)
    return prov


def label(text="", css=None, xalign=0.0, wrap=False, selectable=False,
          ellipsize=None, markup=False):
    lb = Gtk.Label()
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    lb.set_xalign(xalign)
    if wrap:
        lb.set_wrap(True)
        lb.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if selectable:
        lb.set_selectable(True)
    if ellipsize is not None:
        lb.set_ellipsize(ellipsize)
    for c in (css or "").split():
        lb.add_css_class(c)
    return lb


def margins(w, top, end=None, bottom=None, start=None):
    end = top if end is None else end
    bottom = top if bottom is None else bottom
    start = end if start is None else start
    w.set_margin_top(top)
    w.set_margin_end(end)
    w.set_margin_bottom(bottom)
    w.set_margin_start(start)
    return w


def badge(text, kind):
    lb = label(text, "badge badge-" + kind)
    lb.set_valign(Gtk.Align.CENTER)
    return lb


def icon_button(icon, tooltip, cb=None, flat=False):
    b = Gtk.Button.new_from_icon_name(icon)
    b.set_tooltip_text(tooltip)
    if flat:
        b.add_css_class("flat")
    if cb:
        b.connect("clicked", cb)
    return b


def run_async(func, done):
    """Выполнить func() в потоке, затем done(result, error) в главном цикле."""
    def worker():
        try:
            res, err = func(), None
        except Exception as e:  # noqa
            res, err = None, e
        GLib.idle_add(lambda: (done(res, err), False)[1])
    t = threading.Thread(target=worker)
    t.daemon = True
    t.start()


def set_clipboard(widget, text):
    cb = widget.get_clipboard()
    try:
        cb.set(text)
    except (TypeError, AttributeError):
        v = GObject.Value(str, text)
        cb.set_content(Gdk.ContentProvider.new_for_value(v))


# ═══════════════════════════════════════════════════════════════════════════
#  Диалоги (GTK 4: асинхронные, без run())
# ═══════════════════════════════════════════════════════════════════════════
def ask(parent, title, text, ok_label, callback, destructive=False,
        cancel_label="Отмена", kind="question"):
    """Окно подтверждения. callback(True/False) вызывается один раз.
    ok_label=None — только кнопка закрытия (информационное окно)."""
    win = Gtk.Window(transient_for=parent, modal=True, resizable=False)
    win.set_title(title)
    win.set_titlebar(Gtk.Box())          # без заголовка, как у message-диалогов
    win.add_css_class("dialog")
    win.add_css_class("message")
    win.set_default_size(500, -1)
    state = {"done": False}

    def finish(ok):
        if not state["done"]:
            state["done"] = True
            win.destroy()
            if callback:
                callback(ok)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    content = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), 24, 28)
    icons = {"question": "dialog-question-symbolic", "warning": "dialog-warning-symbolic",
             "info": "dialog-information-symbolic", "error": "dialog-error-symbolic"}
    head = Gtk.Box(spacing=12)
    img = Gtk.Image.new_from_icon_name(icons.get(kind, icons["question"]))
    img.set_pixel_size(32)
    img.set_valign(Gtk.Align.START)
    head.append(img)
    t = label(title, "dlg-title", wrap=True)
    t.set_max_width_chars(48)
    t.set_hexpand(True)
    head.append(t)
    content.append(head)
    body = label(text, wrap=True, selectable=True)
    body.set_max_width_chars(64)
    content.append(body)
    box.append(content)

    btns = Gtk.Box(spacing=8, homogeneous=True)
    btns.add_css_class("dlg-buttons")
    margins(btns, 0, 16, 16, 16)
    cancel = Gtk.Button.new_with_label(cancel_label if ok_label else "Закрыть")
    cancel.connect("clicked", lambda *_: finish(False))
    btns.append(cancel)
    if ok_label:
        ok = Gtk.Button.new_with_label(ok_label)
        ok.add_css_class("destructive-action" if destructive else "suggested-action")
        ok.connect("clicked", lambda *_: finish(True))
        btns.append(ok)
    box.append(btns)
    win.set_child(box)

    keys = Gtk.EventControllerKey()
    keys.connect("key-pressed", lambda _c, kv, _kc, _st:
                 (finish(False), True)[1] if kv == Gdk.KEY_Escape else False)
    win.add_controller(keys)
    win.connect("close-request", lambda *_: (finish(False), False)[1])
    win.present()
    cancel.grab_focus()
    GLib.idle_add(lambda: (body.select_region(0, 0), False)[1])   # без автовыделения текста
    return win


def text_window(parent, title, text):
    win = Gtk.Window(transient_for=parent, modal=True, title=title)
    win.set_default_size(780, 560)
    if USE_CSD:
        win.set_titlebar(Gtk.HeaderBar())
    tv = Gtk.TextView(editable=False, monospace=True)
    margins(tv, 8, 12)
    tv.get_buffer().set_text(text)
    sw = Gtk.ScrolledWindow()
    sw.set_child(tv)
    win.set_child(sw)
    win.present()


def choose_file(parent, title, initial_dir, callback):
    """Выбор файла: Gtk.FileDialog (GTK 4.10+) или FileChooserNative (4.0+)."""
    start = Gio.File.new_for_path(initial_dir) if os.path.isdir(initial_dir) else None
    if hasattr(Gtk, "FileDialog"):
        d = Gtk.FileDialog(title=title, modal=True)
        if start:
            d.set_initial_folder(start)

        def done(dlg, res):
            try:
                f = dlg.open_finish(res)
            except GLib.Error:
                return
            if f and f.get_path():
                callback(f.get_path())
        d.open(parent, None, done)
        parent._file_dialog = d
    else:
        d = Gtk.FileChooserNative(title=title, transient_for=parent, modal=True,
                                  action=Gtk.FileChooserAction.OPEN,
                                  accept_label="Выбрать", cancel_label="Отмена")
        if start:
            try:
                d.set_current_folder(start)
            except GLib.Error:
                pass

        def resp(dlg, r):
            if r == Gtk.ResponseType.ACCEPT and dlg.get_file():
                callback(dlg.get_file().get_path())
            dlg.destroy()
        d.connect("response", resp)
        d.show()
        parent._file_dialog = d


# ═══════════════════════════════════════════════════════════════════════════
#  Контейнер с переносом строк (GtkFlowBox выравнивает по колонкам)
# ═══════════════════════════════════════════════════════════════════════════
class WrapBox(Gtk.Widget):
    __gtype_name__ = "GrubbyGuiWrapBox"

    def __init__(self, spacing=6):
        Gtk.Widget.__init__(self)
        self.spacing = spacing
        self.kids = []

    def set_items(self, items):
        for k in self.kids:
            k.unparent()
        self.kids = list(items)
        for k in self.kids:
            k.set_parent(self)
        self.queue_resize()

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _rows(self, width):
        rows, row, used = [], [], 0
        for k in self.kids:
            mn, nat = k.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
            w = max(mn, min(nat, width))
            if row and used + self.spacing + w > width:
                rows.append(row)
                row, used = [], 0
            used += w + (self.spacing if row else 0)
            row.append((k, w))
        if row:
            rows.append(row)
        return rows

    def _row_height(self, row):
        return max(k.measure(Gtk.Orientation.VERTICAL, w)[1] for k, w in row)

    def do_measure(self, orientation, for_size):
        if not self.kids:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            sizes = [k.measure(orientation, -1) for k in self.kids]
            mn = max(s[0] for s in sizes)
            nat = sum(s[1] for s in sizes) + self.spacing * (len(sizes) - 1)
            return mn, nat, -1, -1
        width = for_size if for_size > 0 else 10 ** 6
        rows = self._rows(width)
        h = sum(self._row_height(r) for r in rows) + self.spacing * (len(rows) - 1)
        return h, h, -1, -1

    def do_size_allocate(self, width, height, baseline):
        y = 0
        for row in self._rows(width):
            rh = self._row_height(row)
            x = 0
            for k, w in row:
                r = Gdk.Rectangle()
                r.x, r.y, r.width, r.height = x, y, w, rh
                k.size_allocate(r, -1)
                x += w + self.spacing
            y += rh + self.spacing

    def do_dispose(self):
        for k in self.kids:
            k.unparent()
        self.kids = []
        Gtk.Widget.do_dispose(self)


class Chip(Gtk.Box):
    def __init__(self, text, state, on_click):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class("chip")
        self.set_valign(Gtk.Align.CENTER)
        lb = Gtk.Label()
        esc = GLib.markup_escape_text(text)
        lb.set_markup("<s>%s</s>" % esc if state == "removed" else esc)
        self.append(lb)
        if state == "root":
            self.add_css_class("chip-root")
            self.set_tooltip_text("Корневая ФС — grubby выводит её отдельно. "
                                  "Изменяйте только если точно знаете, зачем.")
            return
        if state in ("added", "removed"):
            self.add_css_class("chip-" + state)
        tips = {"normal": "Удалить параметр", "added": "Отменить добавление",
                "removed": "Вернуть параметр"}
        icon = "edit-undo-symbolic" if state == "removed" else "window-close-symbolic"
        btn = icon_button(icon, tips.get(state, ""), flat=True)
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda _b: on_click(text, state))
        self.append(btn)


# ═══════════════════════════════════════════════════════════════════════════
#  Окно добавления записи
# ═══════════════════════════════════════════════════════════════════════════
class AddEntryWindow(Gtk.Window):
    def __init__(self, parent, on_ok):
        Gtk.Window.__init__(self, transient_for=parent, modal=True,
                            title="Новая запись загрузки")
        self.set_default_size(660, -1)
        self.on_ok = on_ok
        cancel = Gtk.Button.new_with_label("Отмена")
        cancel.connect("clicked", lambda *_: self.destroy())
        self.ok = Gtk.Button.new_with_label("Добавить")
        self.ok.add_css_class("suggested-action")
        self.ok.connect("clicked", lambda *_: self._accept())

        box = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), 18)
        self.set_child(box)
        if USE_CSD:
            hb = Gtk.HeaderBar()
            hb.set_show_title_buttons(False)
            hb.pack_start(cancel)
            hb.pack_end(self.ok)
            self.set_titlebar(hb)
        else:   # рамку рисует оконный менеджер — кнопки внизу окна
            self._bottom = Gtk.Box(spacing=8)
            self._bottom.set_halign(Gtk.Align.END)
            self._bottom.set_margin_top(6)
            self._bottom.append(cancel)
            self._bottom.append(self.ok)
        box.append(label(
            "Создаёт новую запись в меню GRUB для указанного ядра. Обычно это не "
            "нужно: пакеты kernel добавляют записи сами. Полезно для собственных "
            "сборок ядра или особых вариантов загрузки.", "dim", wrap=True))

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        box.append(grid)
        self.kernel = self._path_row("Выберите файл ядра (vmlinuz)")
        self.initrd = self._path_row("Выберите initramfs")
        self.title_entry = Gtk.Entry(hexpand=True)
        self.title_entry.set_placeholder_text("например: Моё ядро 6.9 (отладка)")
        self.args_entry = Gtk.Entry(hexpand=True)
        self.args_entry.set_placeholder_text("дополнительные параметры, необязательно")
        self.copy_default = Gtk.CheckButton(
            label="Скопировать параметры и root из записи по умолчанию (--copy-default)")
        self.copy_default.set_active(True)
        self.make_default = Gtk.CheckButton(
            label="Сделать новую запись загрузкой по умолчанию (--make-default)")
        rows = [("Ядро", self.kernel[0]), ("initramfs", self.initrd[0]),
                ("Название", self.title_entry), ("Параметры", self.args_entry)]
        for i, (name, w) in enumerate(rows):
            grid.attach(label(name, "dim", xalign=1.0), 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)
        grid.attach(self.copy_default, 1, len(rows), 1, 1)
        grid.attach(self.make_default, 1, len(rows) + 1, 1, 1)

        box.append(label("Будет выполнено:", "dim"))
        self.preview = label("", "cmd-preview", wrap=True, selectable=True)
        box.append(self.preview)
        if not USE_CSD:
            box.append(self._bottom)

        for w in (self.title_entry, self.args_entry, self.initrd[1]):
            w.connect("changed", self._update)
        self.kernel[1].connect("changed", self._kernel_changed)
        for w in (self.copy_default, self.make_default):
            w.connect("toggled", self._update)
        self._update()
        self.present()

    def _path_row(self, title):
        row = Gtk.Box(spacing=6, hexpand=True)
        entry = Gtk.Entry(hexpand=True)
        entry.add_css_class("mono")
        entry.set_placeholder_text("/boot/…")
        btn = Gtk.Button.new_with_label("Обзор…")
        btn.connect("clicked", lambda *_: choose_file(
            self, title, "/boot", lambda p: entry.set_text(p)))
        row.append(entry)
        row.append(btn)
        return row, entry

    def _kernel_changed(self, *_):
        k = self.kernel[1].get_text().strip()
        ver = core.kernel_version(k) if os.path.basename(k).startswith("vmlinuz-") else ""
        if ver and not self.initrd[1].get_text():
            guess = os.path.join(os.path.dirname(k), "initramfs-%s.img" % ver)
            if os.path.exists(guess):
                self.initrd[1].set_text(guess)
        if ver and not self.title_entry.get_text():
            self.title_entry.set_text("Linux %s (вручную)" % ver)
        self._update()

    def argv(self):
        k = self.kernel[1].get_text().strip()
        if not k:
            return None
        a = ["--add-kernel=" + k]
        i = self.initrd[1].get_text().strip()
        if i:
            a.append("--initrd=" + i)
        t = self.title_entry.get_text().strip()
        if t:
            a.append("--title=" + t)
        extra = self.args_entry.get_text().strip()
        if extra:
            a.append("--args=" + extra)
        if self.copy_default.get_active():
            a.append("--copy-default")
        if self.make_default.get_active():
            a.append("--make-default")
        return a

    def _update(self, *_):
        a = self.argv()
        self.ok.set_sensitive(a is not None)
        self.preview.set_text(format_cmd(a) if a else
                              "grubby --add-kernel=…  (укажите файл ядра)")

    def _accept(self):
        a = self.argv()
        if a:
            self.destroy()
            self.on_ok(a)


# ═══════════════════════════════════════════════════════════════════════════
#  Главное окно
# ═══════════════════════════════════════════════════════════════════════════
class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.set_default_size(1100, 740)
        self.set_icon_name("grubby-gui")
        self.set_title(core.APP_NAME)
        self.backend = core.Backend()
        self.entries = []
        self.rows = []
        self.default_index = None
        self.bls = None               # ответ помощника bls-status
        self.selected = None
        self.pending_add = []
        self.pending_remove = []
        self.supports_no_etc = False
        self.running = os.uname()[2]
        self._suppress_select = False
        self._msg_timeout = None
        self.action_widgets = []

        self._build_header()
        self._build_body()
        self._install_actions()
        self.connect("close-request", lambda *_: (self.backend.stop(), False)[1])
        self.start_helper()

    # ── шапка ──────────────────────────────────────────────────────────────
    def _build_header(self):
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tbox.set_valign(Gtk.Align.CENTER)
        self.subtitle = label("", "subtitle dim", xalign=0.5)
        if USE_CSD:
            # GNOME: кнопки в заголовке окна (HeaderBar)
            tbox.append(label(core.APP_NAME, "title", xalign=0.5))
            tbox.append(self.subtitle)
            hb = Gtk.HeaderBar()
            hb.set_title_widget(tbox)
            self.set_titlebar(hb)
            self.toolbar = None
            pack_start, pack_end = hb.pack_start, hb.pack_end
        else:
            # KDE/LXQt: заголовок и рамку рисует оконный менеджер, кнопки — на панели
            tbox.append(self.subtitle)
            self.toolbar = Gtk.CenterBox()
            self.toolbar.add_css_class("toolbar")
            left, right = Gtk.Box(spacing=6), Gtk.Box(spacing=6)
            self.toolbar.set_start_widget(left)
            self.toolbar.set_center_widget(tbox)
            self.toolbar.set_end_widget(right)
            pack_start = left.append
            pack_end = lambda w: right.prepend(w)  # noqa: E731  (как у HeaderBar: справа налево)
        self._update_subtitle()

        self.btn_refresh = icon_button("view-refresh-symbolic", "Обновить (F5)",
                                       lambda *_: self.reload())
        self.btn_add = icon_button("list-add-symbolic", "Добавить запись загрузки…",
                                   lambda *_: self.on_add_entry())
        pack_start(self.btn_refresh)
        pack_start(self.btn_add)
        self.action_widgets += [self.btn_refresh, self.btn_add]

        menu = Gio.Menu()
        menu.append("Режим загрузчика (BLS)…", "win.bls")
        menu.append("Справка grubby (--help)", "win.grubby-help")
        menu.append("О программе", "win.about")
        mb = Gtk.MenuButton()
        mb.set_icon_name("open-menu-symbolic")
        mb.set_menu_model(menu)
        pack_end(mb)

        self.btn_log = Gtk.ToggleButton()
        self.btn_log.set_icon_name("utilities-terminal-symbolic")
        self.btn_log.set_tooltip_text("Журнал выполненных команд")
        self.btn_log.connect("toggled",
                             lambda b: self.log_revealer.set_reveal_child(b.get_active()))
        pack_end(self.btn_log)
        self.spinner = Gtk.Spinner()
        pack_end(self.spinner)

    def _update_subtitle(self):
        mode = {True: " · BLS", False: " · не BLS", None: ""}[core.is_bls(self.bls)]
        self.subtitle.set_text("grubby · %s · ядро %s%s" % (
            socket.gethostname(), self.running, mode))

    # ── тело ───────────────────────────────────────────────────────────────
    def _build_body(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)
        if self.toolbar:
            outer.append(self.toolbar)
            outer.append(Gtk.Separator())

        # строка сообщений
        self.msgbar = Gtk.Box(spacing=8)
        self.msgbar.add_css_class("msgbar")
        self.msg_label = label("", wrap=True)
        self.msg_label.set_hexpand(True)
        self.msgbar.append(self.msg_label)
        self.msgbar.append(icon_button("window-close-symbolic", "Закрыть",
                                       lambda *_: self.hide_message(), flat=True))
        self.msg_revealer = Gtk.Revealer()
        self.msg_revealer.set_child(self.msgbar)
        outer.append(self.msg_revealer)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_vexpand(True)
        outer.append(self.stack)

        self.stack.add_named(self._status_page(
            "dialog-password-symbolic", "Требуются права администратора",
            "Подтвердите запуск в окне запроса пароля.\n"
            "Пароль спрашивается один раз за сеанс работы программы.",
            spinner=True), "waiting")
        err_page, self.err_title, self.err_text = self._status_page(
            "dialog-warning-symbolic", "Не удалось получить доступ к grubby", "",
            button=("Повторить", lambda *_: self.start_helper()), want_labels=True)
        self.stack.add_named(err_page, "error")

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.append(self._build_bls_banner())
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_start_child(self._build_sidebar())
        paned.set_end_child(self._build_details())
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_position(360)
        main.append(paned)
        self.stack.add_named(main, "main")

        # журнал команд
        self.log_buf = Gtk.TextBuffer()
        for name, props in (("cmd", {"weight": Pango.Weight.BOLD}),
                            ("ok", {"foreground": "#26a269"}),
                            ("err", {"foreground": "#e01b24"}),
                            ("dim", {"foreground": "#8a8a8a"})):
            self.log_buf.create_tag(name, **props)
        self.log_view = Gtk.TextView(buffer=self.log_buf, editable=False,
                                     cursor_visible=False, monospace=True)
        self.log_view.set_left_margin(10)
        self.log_view.set_top_margin(6)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(-1, 180)
        sw.set_child(self.log_view)
        logbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        logbox.append(Gtk.Separator())
        logbox.append(sw)
        self.log_revealer = Gtk.Revealer()
        self.log_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.log_revealer.set_child(logbox)
        outer.append(self.log_revealer)

    def _status_page(self, icon, title, text, spinner=False, button=None, want_labels=False):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        margins(box, 24)
        img = Gtk.Image.new_from_icon_name(icon)
        img.set_pixel_size(72)
        img.add_css_class("dim")
        box.append(img)
        t = label(title, "entry-title", xalign=0.5)
        box.append(t)
        tx = label(text, "dim", xalign=0.5, wrap=True, selectable=True)
        tx.set_justify(Gtk.Justification.CENTER)
        tx.set_max_width_chars(70)
        box.append(tx)
        if spinner:
            sp = Gtk.Spinner()
            sp.start()
            box.append(sp)
        if button:
            b = Gtk.Button.new_with_label(button[0])
            b.add_css_class("suggested-action")
            b.set_halign(Gtk.Align.CENTER)
            b.connect("clicked", button[1])
            self.retry_btn = b
            box.append(b)
        if want_labels:
            return box, t, tx
        return box

    def _build_bls_banner(self):
        box = Gtk.Box(spacing=12)
        box.add_css_class("banner")
        img = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        img.set_pixel_size(24)
        box.append(img)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        v.set_hexpand(True)
        v.append(label("Загрузчик работает не в режиме BLS", "banner-title"))
        self.banner_text = label("", wrap=True)
        v.append(self.banner_text)
        box.append(v)
        b = Gtk.Button.new_with_label("Перейти на BLS…")
        b.add_css_class("suggested-action")
        b.set_valign(Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self.on_bls())
        box.append(b)
        self.action_widgets.append(b)
        self.bls_revealer = Gtk.Revealer()
        self.bls_revealer.set_child(box)
        return self.bls_revealer

    def _build_sidebar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_size_request(300, -1)
        box.append(label("ЗАПИСИ МЕНЮ ЗАГРУЗКИ", "side-header"))
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.listbox.connect("row-selected", self.on_row_selected)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_child(self.listbox)
        box.append(sw)
        box.append(margins(label(
            "Порядок соответствует меню GRUB. ★ — загружается по умолчанию.",
            "dim", wrap=True), 10, 12))
        return box

    def _build_details(self):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.details_stack = Gtk.Stack()
        sw.set_child(self.details_stack)
        self.details_stack.add_named(self._status_page(
            "view-list-symbolic", "Выберите запись", "Слева — список записей меню GRUB."),
            "empty")

        d = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), 20, 28)
        self.details_stack.add_named(d, "entry")

        self.d_title = label("", "entry-title", wrap=True, selectable=True)
        d.append(self.d_title)
        self.d_badges = Gtk.Box(spacing=6)
        d.append(self.d_badges)

        act = Gtk.Box(spacing=8)
        self.btn_default = Gtk.Button.new_with_label("★  Загружать по умолчанию")
        self.btn_default.add_css_class("suggested-action")
        self.btn_default.set_tooltip_text("grubby --set-default-index=N")
        self.btn_default.connect("clicked", lambda *_: self.on_set_default())
        self.btn_remove = Gtk.Button.new_with_label("Удалить запись…")
        self.btn_remove.add_css_class("destructive-action")
        self.btn_remove.set_tooltip_text("grubby --remove-kernel=…")
        self.btn_remove.connect("clicked", lambda *_: self.on_remove())
        act.append(self.btn_default)
        act.append(self.btn_remove)
        d.append(act)
        self.action_widgets += [self.btn_default, self.btn_remove]

        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        grid.add_css_class("props")
        self.props = {}
        rows = [("index", "Индекс"), ("version", "Версия ядра"), ("kernel", "Файл ядра"),
                ("initrd", "initramfs"), ("root", "Корневая ФС"), ("id", "ID записи (BLS)")]
        for i, (key, name) in enumerate(rows):
            grid.attach(label(name, "dim", xalign=1.0), 0, i, 1, 1)
            v = label("", "mono", selectable=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            v.set_hexpand(True)
            grid.attach(v, 1, i, 1, 1)
            self.props[key] = v
        d.append(grid)

        d.append(margins(label("Параметры ядра", "section-title"), 4, 0, 0, 0))
        d.append(label(
            "Нажмите × чтобы удалить параметр, или добавьте новый ниже. "
            "Ничего не меняется, пока вы не нажмёте «Применить».", "dim", wrap=True))
        self.chips = WrapBox(spacing=6)
        d.append(self.chips)

        addrow = Gtk.Box(spacing=6)
        self.arg_entry = Gtk.Entry(hexpand=True)
        self.arg_entry.set_placeholder_text(
            "Новый параметр, например  nomodeset  или  console=ttyS0,115200")
        self.arg_entry.add_css_class("mono")
        self.arg_entry.connect("activate", lambda *_: self.on_add_arg())
        btn_add_arg = Gtk.Button.new_with_label("Добавить")
        btn_add_arg.connect("clicked", lambda *_: self.on_add_arg())
        self.btn_catalog = Gtk.MenuButton()
        if hasattr(self.btn_catalog, "set_child"):           # GTK 4.6+
            cbox = Gtk.Box(spacing=6)
            cbox.append(Gtk.Image.new_from_icon_name("view-list-bullet-symbolic"))
            cbox.append(Gtk.Label(label="Каталог параметров"))
            self.btn_catalog.set_child(cbox)
        else:
            self.btn_catalog.set_label("Каталог параметров")
        self.catalog = self._build_catalog()
        self.btn_catalog.set_popover(self.catalog)
        addrow.append(self.arg_entry)
        addrow.append(btn_add_arg)
        addrow.append(self.btn_catalog)
        d.append(addrow)

        scope = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        srow = Gtk.Box(spacing=18)
        srow.append(label("Применить к:", "dim"))
        self.scope_one = Gtk.CheckButton(label="только этой записи")
        self.scope_all = Gtk.CheckButton(label="всем записям (ALL)")
        self.scope_all.set_group(self.scope_one)
        self.scope_one.set_active(True)
        self.scope_all.set_tooltip_text(
            "Изменит все записи меню, а также, как правило, GRUB_CMDLINE_LINUX "
            "в /etc/default/grub — параметры сохранятся и для будущих ядер.")
        srow.append(self.scope_one)
        srow.append(self.scope_all)
        scope.append(srow)
        self.no_etc = Gtk.CheckButton(
            label="Не изменять GRUB_CMDLINE_LINUX в /etc/default/grub (--no-etc-grub-update)")
        self.no_etc.set_margin_start(110)
        scope.append(self.no_etc)
        d.append(scope)
        for w in (self.scope_one, self.scope_all, self.no_etc):
            w.connect("toggled", lambda *_: self.refresh_pending_ui())

        prow = Gtk.Box(spacing=6)
        self.preview = label("", "cmd-preview", wrap=True, selectable=True)
        self.preview.set_hexpand(True)
        prow.append(self.preview)
        copy = icon_button("edit-copy-symbolic", "Скопировать команду",
                           lambda *_: self.copy_preview())
        copy.set_valign(Gtk.Align.START)
        prow.append(copy)
        d.append(prow)

        brow = Gtk.Box(spacing=8)
        brow.set_halign(Gtk.Align.END)
        self.btn_reset = Gtk.Button.new_with_label("Сбросить")
        self.btn_reset.connect("clicked", lambda *_: self.reset_pending())
        self.btn_apply = Gtk.Button.new_with_label("Применить изменения")
        self.btn_apply.add_css_class("suggested-action")
        self.btn_apply.connect("clicked", lambda *_: self.on_apply())
        brow.append(self.btn_reset)
        brow.append(self.btn_apply)
        d.append(brow)
        self.action_widgets.append(self.btn_apply)
        return sw

    def _build_catalog(self):
        pop = Gtk.Popover()
        box = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), 6)
        self.cat_search = Gtk.SearchEntry()
        self.cat_search.set_placeholder_text("Поиск параметра…")
        box.append(self.cat_search)
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb.set_activate_on_single_click(True)
        self.cat_rows = []
        for cat, items in core.PRESETS:
            r = Gtk.ListBoxRow(activatable=False, selectable=False)
            r.set_child(label(cat.upper(), "preset-cat"))
            lb.append(r)
            self.cat_rows.append((r, cat, None))
            for name, desc, edit in items:
                r = Gtk.ListBoxRow()
                v = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1), 5, 10)
                top = Gtk.Box(spacing=6)
                top.append(label(name, "preset-name"))
                if edit:
                    top.append(label("уточните значение", "dim"))
                v.append(top)
                v.append(label(desc, "dim", wrap=True))
                r.set_child(v)
                lb.append(r)
                self.cat_rows.append((r, cat, (name, desc, edit)))
        presets = {r: p for r, _c, p in self.cat_rows}

        def filt(row):
            q = self.cat_search.get_text().strip().lower()
            if not q:
                return True
            p = presets.get(row)
            if p is None:   # заголовок категории — показывать, если есть совпадения
                cat = next(c for rr, c, _p in self.cat_rows if rr == row)
                return any(q in (n + " " + d).lower()
                           for c, items in core.PRESETS if c == cat for n, d, _e in items)
            return q in p[0].lower() or q in p[1].lower()
        lb.set_filter_func(filt)
        self.cat_search.connect("search-changed", lambda *_: lb.invalidate_filter())
        lb.connect("row-activated", lambda _l, r: self.on_preset(presets.get(r)))
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_size_request(470, 420)
        sw.set_child(lb)
        box.append(sw)
        pop.set_child(box)
        return pop

    def _install_actions(self):
        for name, cb in (("refresh", lambda *_: self.reload()),
                         ("bls", lambda *_: self.on_bls()),
                         ("grubby-help", lambda *_: self.on_grubby_help()),
                         ("about", lambda *_: self.on_about())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)

    # ── сообщения и журнал ─────────────────────────────────────────────────
    def show_message(self, text, kind="info", timeout=7):
        self.msg_label.set_text(text)
        for k in ("info", "success", "error", "warning"):
            self.msgbar.remove_css_class(k)
        self.msgbar.add_css_class(kind)
        self.msg_revealer.set_reveal_child(True)
        if self._msg_timeout:
            GLib.source_remove(self._msg_timeout)
            self._msg_timeout = None
        if timeout:
            self._msg_timeout = GLib.timeout_add_seconds(timeout, self._auto_hide)

    def _auto_hide(self):
        self._msg_timeout = None
        self.hide_message()
        return False

    def hide_message(self):
        self.msg_revealer.set_reveal_child(False)

    def log_line(self, text, tag=None):
        end = self.log_buf.get_end_iter()
        if tag:
            self.log_buf.insert_with_tags_by_name(end, text, tag)
        else:
            self.log_buf.insert(end, text)

    def log(self, cmd, res, quiet=False):
        self.log_line(time.strftime("%H:%M:%S  "), "dim")
        self.log_line("# " + cmd, "cmd")
        rc = res.get("rc", -1)
        self.log_line("   → код %s\n" % rc, "ok" if rc == 0 else "err")
        out = (res.get("out") or "").rstrip()
        err = (res.get("err") or "").rstrip()
        if out and not quiet:
            lines = out.splitlines()
            if len(lines) > 40:
                out = "\n".join(lines[:40]) + "\n… (ещё %d строк)" % (len(lines) - 40)
            self.log_line(out + "\n", "dim")
        if err:
            self.log_line(err + "\n", "err")
        GLib.idle_add(self._scroll_log)

    def _scroll_log(self):
        self.log_view.scroll_to_iter(self.log_buf.get_end_iter(), 0.0, False, 0, 0)
        return False

    def set_busy(self, busy):
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        for w in self.action_widgets:
            w.set_sensitive(not busy)
        if not busy:
            self.update_action_sensitivity()

    # ── помощник и загрузка данных ─────────────────────────────────────────
    def start_helper(self):
        self.stack.set_visible_child_name("waiting")

        def work():
            info = self.backend.start()
            h = self.backend.call(["--help"])
            return info, (h.get("out", "") + h.get("err", ""))

        def done(res, err):
            if err:
                self.show_error_page(str(err))
                return
            info, helptext = res
            self.supports_no_etc = "--no-etc-grub-update" in helptext
            self.log_line("Помощник запущен (uid=%s), grubby: %s%s\n" % (
                info.get("uid"), info.get("grubby"),
                "  [ДЕМО-РЕЖИМ]" if self.backend.demo else ""), "dim")
            self.stack.set_visible_child_name("main")
            self.reload()
        run_async(work, done)

    def reload(self, select_kernel=None, select_index=None):
        if self.stack.get_visible_child_name() != "main":
            return
        if select_kernel is None and self.selected:
            select_kernel = self.selected.get("kernel")
            select_index = self.selected.get("index")
        self.set_busy(True)

        def work():
            return (self.backend.call(["--info=ALL"]),
                    self.backend.call(["--default-index"]),
                    self.backend.op("bls-status"))

        def done(res, err):
            self.set_busy(False)
            if err:
                self.fail(err)
                return
            r1, r2, r3 = res
            self.log("grubby --info=ALL", r1, quiet=True)
            self.log("grubby --default-index", r2)
            if r1.get("rc") != 0:
                self.show_message("grubby --info=ALL завершился с ошибкой:\n" +
                                  (r1.get("err") or r1.get("out") or "").strip(), "error", 0)
            self.entries = core.parse_info(r1.get("out", ""))
            self.default_index = core.parse_default_index(r2.get("out"))
            self.bls = r3.get("data") if r3.get("rc") == 0 else None
            self.update_bls_banner()
            self.populate(select_kernel, select_index)
        run_async(work, done)

    def update_bls_banner(self):
        st = self.bls or {}
        legacy = core.is_bls(self.bls) is False
        if legacy:
            val = st.get("blscfg")
            self.banner_text.set_text(
                "GRUB_ENABLE_BLSCFG=%s в %s. grubby меняет записи в %s, но GRUB их не "
                "читает — изменения могут не попасть в меню загрузки." % (
                    val if val else "(не задано)", st.get("default_grub"),
                    st.get("entries_dir")))
        self.bls_revealer.set_reveal_child(legacy)
        self._update_subtitle()

    def fail(self, err):
        if isinstance(err, core.HelperError):
            self.show_error_page(str(err), "Связь с grubby потеряна")
        else:
            self.show_message("Ошибка: %s" % err, "error", 0)

    def show_error_page(self, text, title=None):
        if title:
            self.err_title.set_text(title)
        self.err_text.set_text(text)
        self.stack.set_visible_child_name("error")
        self.retry_btn.grab_focus()
        GLib.idle_add(lambda: (self.err_text.select_region(0, 0), False)[1])

    def is_running(self, e):
        return os.path.basename(e.get("kernel", "")) == "vmlinuz-" + self.running

    def is_default(self, e):
        return self.default_index is not None and e["index"] == self.default_index

    def _make_row(self, e):
        row = Gtk.ListBoxRow()
        row.entry = e
        h = margins(Gtk.Box(spacing=10), 6, 6)
        num = label(str(e["index"]), "dim mono", xalign=0.5)
        num.set_width_chars(2)
        h.append(num)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        v.set_hexpand(True)
        t = label(e["title"], wrap=True, ellipsize=Pango.EllipsizeMode.END)
        t.set_lines(2)
        if self.is_default(e):
            t.set_markup("<b>%s</b>" % GLib.markup_escape_text(e["title"]))
        t.set_tooltip_text(e["title"])
        v.append(t)
        v.append(label(e.get("version") or e.get("note", ""), "dim mono",
                       ellipsize=Pango.EllipsizeMode.END))
        h.append(v)
        if self.is_default(e):
            star = label("★", "star")
            star.set_tooltip_text("Загружается по умолчанию")
            h.append(star)
        if self.is_running(e):
            b = badge("сейчас", "running")
            b.set_tooltip_text("Это ядро загружено в данный момент")
            h.append(b)
        row.set_child(h)
        return row

    def populate(self, select_kernel=None, select_index=None):
        self._suppress_select = True
        for r in self.rows:
            self.listbox.remove(r)
        self.rows = [self._make_row(e) for e in self.entries]
        for r in self.rows:
            self.listbox.append(r)
        target = None
        if select_kernel:
            target = next((r for r in self.rows if r.entry.get("kernel") == select_kernel and
                           (select_index is None or r.entry["index"] == select_index)), None) \
                or next((r for r in self.rows if r.entry.get("kernel") == select_kernel), None)
        target = target or next((r for r in self.rows if self.is_default(r.entry)), None) \
            or (self.rows[0] if self.rows else None)
        self._suppress_select = False
        if target:
            self._select_row_silently(target)
            self.show_entry(target.entry)
        else:
            self.selected = None
            self.details_stack.set_visible_child_name("empty")

    def _select_row_silently(self, row):
        self._suppress_select = True
        self.listbox.select_row(row)
        self._suppress_select = False

    def has_pending(self):
        return bool(self.pending_add or self.pending_remove)

    def on_row_selected(self, lb, row):
        if self._suppress_select or row is None or self.selected is row.entry:
            return
        if not self.has_pending():
            self.show_entry(row.entry)
            return
        # есть несохранённые изменения: вернуть выделение и спросить
        new_entry = row.entry
        old = next((r for r in self.rows if r.entry is self.selected), None)
        if old:
            self._select_row_silently(old)

        def answer(ok):
            if ok:
                self.pending_add, self.pending_remove = [], []
                r = next((r for r in self.rows if r.entry is new_entry), None)
                if r:
                    self._select_row_silently(r)
                    self.show_entry(new_entry)
        ask(self, "Отменить несохранённые изменения?",
            "Изменения параметров ядра для «%s» ещё не применены." % self.selected["title"],
            "Отменить изменения", answer, destructive=True, cancel_label="Назад",
            kind="warning")

    def show_entry(self, e):
        self.selected = e
        self.pending_add, self.pending_remove = [], []
        self.details_stack.set_visible_child_name("entry")
        self.d_title.set_text(e["title"])
        child = self.d_badges.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.d_badges.remove(child)
            child = nxt
        if self.is_default(e):
            self.d_badges.append(badge("★ по умолчанию", "default"))
        if self.is_running(e):
            self.d_badges.append(badge("загружено сейчас", "running"))
        if "rescue" in (e.get("kernel", "") + e.get("title", "")).lower():
            self.d_badges.append(badge("rescue", "rescue"))
        for key, w in self.props.items():
            val = str(e.get(key, "")) or "—"
            w.set_text(val)
            w.set_tooltip_text(val)
        self.refresh_pending_ui()

    def update_action_sensitivity(self):
        e = self.selected
        isdef = bool(e) and self.is_default(e)
        self.btn_default.set_sensitive(bool(e) and not isdef and "kernel" in e)
        self.btn_default.set_label("★  Уже загружается по умолчанию" if isdef
                                   else "★  Загружать по умолчанию")
        self.btn_remove.set_sensitive(bool(e) and "kernel" in e)
        self.btn_apply.set_sensitive(self.has_pending())
        self.btn_reset.set_sensitive(self.has_pending())

    # ── параметры ядра ─────────────────────────────────────────────────────
    def refresh_pending_ui(self):
        e = self.selected
        if not e:
            return
        replaced = set(arg_key(a) for a in self.pending_add if "=" in a)
        items = []

        def add_chip(text, state):
            items.append(Chip(text, state, self.on_chip))

        if e.get("root"):
            add_chip("root=" + e["root"], "root")
        for a in e["argv"]:
            if a in self.pending_remove:
                add_chip(a, "removed")
            elif a not in self.pending_add and "=" in a and arg_key(a) in replaced:
                add_chip(a, "removed")
            else:
                add_chip(a, "normal")
        for a in self.pending_add:
            if a not in e["argv"]:
                add_chip(a, "added")
        if not items:
            items.append(label("(параметров нет)", "dim"))
        self.chips.set_items(items)

        self.no_etc.set_visible(self.supports_no_etc)
        self.no_etc.set_sensitive(self.scope_all.get_active())
        argv = self.build_update_argv()
        if argv:
            self.preview.set_text(format_cmd(argv))
        else:
            self.preview.set_markup("<span alpha='60%%'>%s</span>" % GLib.markup_escape_text(
                "grubby --update-kernel=…  (изменений пока нет)"))
        self.update_action_sensitivity()

    def build_update_argv(self):
        return core.build_update_argv(
            self.selected, self.pending_add, self.pending_remove,
            all_entries=self.scope_all.get_active(),
            no_etc=self.supports_no_etc and self.no_etc.get_active())

    def on_chip(self, text, state):
        if state == "normal":
            if text not in self.pending_remove:
                self.pending_remove.append(text)
        elif state == "removed":
            if text in self.pending_remove:
                self.pending_remove.remove(text)
            else:   # параметр «заменён» новым значением — отменяем замену
                k = arg_key(text)
                self.pending_add = [a for a in self.pending_add if arg_key(a) != k]
        elif state == "added" and text in self.pending_add:
            self.pending_add.remove(text)
        self.refresh_pending_ui()

    def add_tokens(self, tokens):
        e = self.selected
        if not e:
            return
        skipped = []
        for t in tokens:
            if t in self.pending_remove:
                self.pending_remove.remove(t)
                continue
            if t in e["argv"] or t in self.pending_add:
                skipped.append(t)
                continue
            if "=" in t:
                self.pending_add = [a for a in self.pending_add if arg_key(a) != arg_key(t)]
            self.pending_add.append(t)
        if skipped and not self.scope_all.get_active():
            self.show_message("Уже есть: " + " ".join(skipped))
        self.refresh_pending_ui()

    def on_add_arg(self):
        text = self.arg_entry.get_text().strip()
        if not text:
            self.arg_entry.grab_focus()
            return
        if text.count('"') % 2:
            self.show_message("Непарная кавычка в параметре.", "warning")
            return
        self.add_tokens(split_args(text))
        self.arg_entry.set_text("")

    def on_preset(self, preset):
        if not preset:
            return
        name, _desc, edit = preset
        self.catalog.popdown()
        if edit:
            self.arg_entry.set_text(name)
            self.arg_entry.grab_focus()
            pos = name.find("=")
            if pos >= 0 and " " not in name:
                self.arg_entry.select_region(pos + 1, -1)
            self.show_message("Уточните значение «%s» и нажмите «Добавить»." % name, timeout=5)
        else:
            self.add_tokens(split_args(name))

    def reset_pending(self):
        self.pending_add, self.pending_remove = [], []
        self.refresh_pending_ui()

    def copy_preview(self):
        argv = self.build_update_argv()
        if argv:
            set_clipboard(self, "sudo " + format_cmd(argv))
            self.show_message("Команда скопирована в буфер обмена.", timeout=3)

    # ── изменения ──────────────────────────────────────────────────────────
    def run_change(self, argv, success_text, select_kernel=None, select_index=None):
        self.set_busy(True)

        def done(res, err):
            self.set_busy(False)
            if err:
                self.fail(err)
                return
            self.log(format_cmd(argv), res)
            if res.get("rc") == 0:
                self.pending_add, self.pending_remove = [], []
                self.show_message(success_text, "success")
            else:
                msg = (res.get("err") or res.get("out") or "").strip() or \
                    "код возврата %s" % res.get("rc")
                self.show_message("grubby сообщил об ошибке:\n" + msg, "error", 0)
                self.btn_log.set_active(True)
            self.reload(select_kernel, select_index)
        run_async(lambda: self.backend.call(argv), done)

    def on_apply(self):
        argv = self.build_update_argv()
        if not argv:
            return
        e = self.selected
        where = "всех записей" if self.scope_all.get_active() else "«%s»" % e["title"]

        def go(ok=True):
            if ok:
                self.run_change(argv, "Параметры ядра для %s обновлены. Изменения "
                                "вступят в силу после перезагрузки." % where,
                                e.get("kernel"), e["index"])
        risky = [a for a in self.pending_remove if arg_key(a) in core.RISKY_REMOVE] + \
                [a for a in self.pending_add if arg_key(a) in core.RISKY_ADD]
        if risky:
            ask(self, "Изменить критичные параметры?",
                "Параметры %s влияют на возможность загрузки. Убедитесь, что в меню "
                "GRUB есть другая рабочая запись." % ", ".join(risky), "Применить", go,
                kind="warning")
        else:
            go()

    def on_set_default(self):
        e = self.selected
        if e:
            self.run_change(["--set-default-index=%d" % e["index"]],
                            "Теперь по умолчанию загружается «%s»." % e["title"],
                            e.get("kernel"), e["index"])

    def on_remove(self):
        e = self.selected
        if not e:
            return
        text = "Запись будет удалена из меню загрузки GRUB:\n%s" % e.get("kernel")
        same = [x for x in self.entries if x.get("kernel") == e.get("kernel")]
        if len(same) > 1:
            text += "\n\nЭто ядро используют %d записи — grubby удалит их все." % len(same)
        if self.is_running(e):
            text += "\n\n⚠ Это ядро загружено сейчас."
        if self.is_default(e):
            text += "\n⚠ Это запись по умолчанию — после удаления GRUB выберет другую."
        if len(self.entries) <= 1:
            text += "\n\n⛔ Это единственная запись — система не сможет загрузиться!"

        def answer(ok):
            if ok:
                self.selected = None
                self.run_change(["--remove-kernel=" + e["kernel"]],
                                "Запись «%s» удалена из меню загрузки." % e["title"])
        ask(self, "Удалить «%s»?" % e["title"], text, "Удалить", answer,
            destructive=True, kind="warning")

    def on_add_entry(self):
        def ok(argv):
            k = argv[0].split("=", 1)[1]
            self.run_change(argv, "Новая запись добавлена.", k, None)
        AddEntryWindow(self, ok)

    # ── BLS ────────────────────────────────────────────────────────────────
    def on_bls(self):
        st = self.bls
        mode = core.is_bls(st)
        if not st or mode is None:
            ask(self, "Режим BLS не определён",
                "Не найден файл /etc/default/grub — похоже, система не использует GRUB2 "
                "в стандартной конфигурации.", None, None, kind="info")
            return
        info = ("Записей в %s: %d\nПрошивка: %s\nФайл конфигурации GRUB: %s" % (
            st["entries_dir"], st["entries"], "UEFI" if st.get("efi") else "BIOS",
            st["grub_cfg"]))
        if mode:
            ask(self, "Загрузчик работает в режиме BLS",
                "GRUB_ENABLE_BLSCFG=true — меню GRUB строится из записей BLS, которыми "
                "управляет grubby.\n\n" + info, None, None, kind="info")
            return
        if not st.get("mkconfig"):
            ask(self, "Не найден grub2-mkconfig",
                "Установите пакет grub2-tools и повторите.", None, None, kind="error")
            return
        if st["entries"] == 0:
            ask(self, "Нет записей BLS",
                "В %s нет ни одной записи — после перехода меню GRUB было бы пустым, "
                "поэтому переход недоступен.\n\nСоздайте запись для текущего ядра, "
                "например:\nsudo kernel-install add $(uname -r) /lib/modules/$(uname -r)/vmlinuz"
                "\n\nи обновите окно (F5)." % st["entries_dir"], None, None, kind="error")
            return
        text = (
            "Будет выполнено:\n"
            "1. Резервные копии %s и %s (*.grubby-gui-<дата>.bak)\n"
            "2. В %s: GRUB_ENABLE_BLSCFG=true (сейчас: %s)\n"
            "3. %s -o %s\n\n"
            "%s\n\nМеню GRUB будет строиться из записей BLS. "
            "Если grub2-mkconfig завершится с ошибкой, изменения будут откачены." % (
                st["default_grub"], st["grub_cfg"], st["default_grub"],
                st.get("blscfg") or "не задано", os.path.basename(st["mkconfig"]),
                st["grub_cfg"], info))

        def answer(ok):
            if ok:
                self.do_enable_bls()
        ask(self, "Перевести загрузчик в режим BLS?", text, "Перейти на BLS", answer)

    def do_enable_bls(self):
        self.set_busy(True)

        def done(res, err):
            self.set_busy(False)
            if err:
                self.fail(err)
                return
            cfg = (self.bls or {}).get("grub_cfg", "")
            self.log("включение BLS: GRUB_ENABLE_BLSCFG=true; grub2-mkconfig -o " + cfg, res)
            if res.get("rc") == 0:
                self.show_message("Загрузчик переведён в режим BLS. Новое меню GRUB "
                                  "будет использовано при следующей загрузке.", "success", 10)
            else:
                self.show_message("Не удалось перейти на BLS: %s. Подробности — в журнале." %
                                  (res.get("err") or "ошибка"), "error", 0)
                self.btn_log.set_active(True)
            self.reload()
        run_async(lambda: self.backend.op("enable-bls"), done)

    # ── прочее ─────────────────────────────────────────────────────────────
    def on_grubby_help(self):
        def done(res, err):
            if err:
                self.fail(err)
            else:
                text_window(self, "Справка grubby",
                            (res.get("out") or "") + (res.get("err") or ""))
        run_async(lambda: self.backend.call(["--help"]), done)

    def on_about(self):
        d = Gtk.AboutDialog(transient_for=self, modal=True)
        d.set_program_name(core.APP_NAME)
        d.set_version(core.VERSION)
        d.set_logo_icon_name("grubby-gui")
        d.set_comments("Графическая оболочка для grubby — управление записями "
                       "загрузчика GRUB2: ядро по умолчанию, параметры ядра, "
                       "записи меню и переход на BLS.")
        d.set_license_type(Gtk.License.GPL_2_0)
        d.present()


class App(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id=core.APP_ID,
                                 flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        add_css(CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        q = Gio.SimpleAction.new("quit", None)
        q.connect("activate", lambda *_: self.quit())
        self.add_action(q)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.refresh", ["F5", "<Control>r"])

    def do_activate(self):
        if not self.win:
            self.win = MainWindow(self)
        self.win.present()


def main():
    if "--version" in sys.argv:
        print("grubby-gui", core.VERSION)
        return 0
    return App().run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
