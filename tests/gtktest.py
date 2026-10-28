# Общие средства GUI-тестов (GTK 4): пошаговые сценарии и снимки окон.
import os
import sys
import traceback

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("GRUBBY_GUI_DEMO", os.path.join(HERE, "fake-grubby"))

import grubby_gui as g  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

errors = []


def snap(widget, path):
    """Сохранить изображение виджета/окна в PNG."""
    w, h = widget.get_width(), widget.get_height()
    p = Gtk.WidgetPaintable.new(widget)
    s = Gtk.Snapshot()
    p.snapshot(s, w, h)
    node = s.to_node()
    if node is None:
        raise RuntimeError("пустой снимок")
    tex = widget.get_native().get_renderer().render_texture(node, None)
    tex.save_to_png(path)
    print("saved", os.path.basename(path))


def top_dialogs(app):
    return [w for w in Gtk.Window.list_toplevels()
            if w is not app.win and w.get_visible() and isinstance(w, Gtk.Window)
            and w.get_transient_for() is app.win]


def run(app, steps):
    def nxt(i):
        if i >= len(steps):
            app.quit()
            return False
        d, fn = steps[i]

        def go():
            nxt(i + 1)
            try:
                fn()
            except Exception:
                traceback.print_exc()
                errors.append("исключение на шаге %d" % i)
            return False
        GLib.timeout_add(d, go)
        return False
    app.connect("activate", lambda *_: GLib.timeout_add(300, lambda: nxt(0)))
    app.run([sys.argv[0]])
    if errors:
        print("ERRORS:", errors)
    return 1 if errors else 0
