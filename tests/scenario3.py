#!/usr/bin/python3
# Сценарий 3 (демо-режим): буфер обмена, справка grubby, «О программе», непарная кавычка.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gtktest as t  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
app = t.g.App()
W = lambda: app.win  # noqa: E731
got = {}


def copy():
    W().arg_entry.set_text("nomodeset")
    W().on_add_arg()
    W().copy_preview()
    cb = W().get_clipboard()
    cb.read_text_async(None, lambda c, r: got.__setitem__("clip", c.read_text_finish(r)))


def check_clip():
    if not (got.get("clip") or "").startswith("sudo grubby --update-kernel="):
        t.errors.append("буфер обмена: %r" % got.get("clip"))


def quote():
    W().reset_pending()
    W().arg_entry.set_text('foo="bar')
    W().on_add_arg()
    if W().pending_add or "кавычка" not in W().msg_label.get_text():
        t.errors.append("непарная кавычка не отловлена")


def snap_top(name):
    def f():
        d = t.top_dialogs(app)
        if not d:
            return t.errors.append("нет окна " + name)
        t.snap(d[-1], os.path.join(OUT, name + ".png"))
        d[-1].close()
    return f


steps = [
    (1500, copy),
    (500, check_clip),
    (100, quote),
    (100, lambda: W().on_grubby_help()),
    (800, snap_top("13-help")),
    (100, lambda: W().on_about()),
    (800, snap_top("14-about")),
    (300, lambda: print("OK3" if not t.errors else "")),
]
sys.exit(t.run(app, steps))
