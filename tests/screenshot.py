#!/usr/bin/python3
# Сценарий 1 (демо-режим): главное окно, изменения параметров, каталог,
# применение, журнал, окно добавления записи. Сохраняет снимки в каталог argv[1].
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gtktest as t  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
app = t.g.App()
W = lambda: app.win  # noqa: E731
P = lambda n: os.path.join(OUT, n + ".png")  # noqa: E731


def select(idx):
    r = next(r for r in W().rows if r.entry["index"] == idx)
    W().listbox.select_row(r)


def add_pending():
    W().arg_entry.set_text("nomodeset console=ttyS0,115200")
    W().on_add_arg()
    W().on_chip("quiet", "normal")


def snap_dialog(name):
    def f():
        d = t.top_dialogs(app)
        if not d:
            t.errors.append("нет окна для " + name)
            return
        t.snap(d[-1], P(name))
    return f


def close_dialogs():
    for d in t.top_dialogs(app):
        d.close()


steps = [
    (1500, lambda: t.snap(W(), P("01-main"))),
    (100, add_pending),
    (500, lambda: t.snap(W(), P("02-pending"))),
    (100, lambda: W().btn_catalog.popup() if hasattr(W().btn_catalog, "popup")
     else W().catalog.popup()),
    (700, lambda: t.snap(W().catalog, P("03-catalog"))),
    (100, lambda: W().catalog.popdown()),
    (100, lambda: W().on_apply()),
    (100, lambda: W().btn_log.set_active(True)),
    (1200, lambda: t.snap(W(), P("04-applied-log"))),
    (100, lambda: select(3)),
    (500, lambda: t.snap(W(), P("05-rescue"))),
    (100, lambda: W().on_add_entry()),
    (600, snap_dialog("06-add-dialog")),
    (100, close_dialogs),
    (300, lambda: None),
]
sys.exit(t.run(app, steps))
