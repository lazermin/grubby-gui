#!/usr/bin/python3
# Сценарий 2 (демо-режим): несохранённые изменения, смена записи по умолчанию,
# удаление с подтверждением, режим ALL, переход на BLS. Проверяет итоговое состояние.
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gtktest as t  # noqa: E402
from gi.repository import Gtk  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
STATE = os.path.expanduser("~/.cache/grubby-gui-demo.json")
ROOT = os.path.expanduser("~/.cache/grubby-gui-demo-root")
app = t.g.App()
W = lambda: app.win  # noqa: E731
P = lambda n: os.path.join(OUT, n + ".png")  # noqa: E731
err = t.errors.append


def select(idx):
    W().listbox.select_row(next(r for r in W().rows if r.entry["index"] == idx))


def dialog():
    d = t.top_dialogs(app)
    return d[-1] if d else None


def dialog_texts(d):
    out, stack = [], [d]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            out.append(w.get_text())
        if isinstance(w, Gtk.Button) and w.get_label():
            out.append("[%s]" % w.get_label())
        c = w.get_first_child()
        while c:
            stack.append(c)
            c = c.get_next_sibling()
    return "\n".join(out)


def press(label_text):
    def f():
        d = dialog()
        if not d:
            return err("нет диалога для кнопки " + label_text)
        stack = [d]
        while stack:
            w = stack.pop()
            if isinstance(w, Gtk.Button) and w.get_label() == label_text:
                w.emit("clicked")
                return
            c = w.get_first_child()
            while c:
                stack.append(c)
                c = c.get_next_sibling()
        err("кнопка «%s» не найдена" % label_text)
    return f


def expect_dialog(name, must=(), must_not=()):
    def f():
        d = dialog()
        if not d:
            return err("нет диалога " + name)
        t.snap(d, P(name))
        txt = dialog_texts(d)
        for m in must:
            if m not in txt:
                err("%s: нет текста «%s»" % (name, m))
        for m in must_not:
            if m in txt:
                err("%s: лишний текст «%s»" % (name, m))
    return f


def pending_then_switch():
    select(0)
    W().arg_entry.set_text("nomodeset")
    W().on_add_arg()
    select(1)          # должен появиться вопрос, выделение остаётся на 0


def check_still_0():
    if W().selected["index"] != 0 or not W().pending_add:
        err("после «Назад» выделение/изменения потеряны")


def check_switched_1():
    if W().selected["index"] != 1 or W().pending_add:
        err("после «Отменить изменения» не перешли на запись 1")


def all_mode():
    select(0)
    W().scope_all.set_active(True)
    W().no_etc.set_active(True)
    W().arg_entry.set_text("mitigations=off")
    W().on_add_arg()
    W().on_chip("rhgb", "normal")


def verify_grubby():
    st = json.load(open(STATE))
    ents = st["entries"]
    if len(ents) != 3:
        err("ожидалось 3 записи, есть %d" % len(ents))
    if not ents[st["default"]]["kernel"].endswith("427.13.1.el9_4.x86_64"):
        err("неверная запись по умолчанию")
    for e in ents:
        a = e["args"].split()
        if "mitigations=off" not in a or "rhgb" in a:
            err("ALL не применился к %s" % e["kernel"])


def verify_bls():
    txt = open(os.path.join(ROOT, "etc/default/grub")).read()
    if "GRUB_ENABLE_BLSCFG=true" not in txt or "GRUB_ENABLE_BLSCFG=false" in txt:
        err("GRUB_ENABLE_BLSCFG не переключён")
    if "GRUB_CMDLINE_LINUX=" not in txt:
        err("остальное содержимое /etc/default/grub потеряно")
    if not glob.glob(os.path.join(ROOT, "etc/default/grub.grubby-gui-*.bak")):
        err("нет резервной копии /etc/default/grub")
    if not glob.glob(os.path.join(ROOT, "boot/grub2/grub.cfg.grubby-gui-*.bak")):
        err("нет резервной копии grub.cfg")
    if "BLS" not in open(os.path.join(ROOT, "boot/grub2/grub.cfg")).read():
        err("grub.cfg не перегенерирован")
    if W().bls_revealer.get_reveal_child():
        err("баннер «не BLS» не скрылся")
    log = W().log_buf.get_text(W().log_buf.get_start_iter(), W().log_buf.get_end_iter(), False)
    for m in ("--no-etc-grub-update", "Резервная копия", "grub2-mkconfig"):
        if m not in log:
            err("в журнале нет «%s»" % m)
    print("STATE OK" if not t.errors else "")


steps = [
    (1500, pending_then_switch),
    (600, expect_dialog("07-unsaved", must=("[Назад]", "[Отменить изменения]"),
                        must_not=("[Отмена]",))),
    (100, press("Назад")),
    (300, check_still_0),
    (100, lambda: select(1)),
    (500, press("Отменить изменения")),
    (300, check_switched_1),
    (100, lambda: W().on_set_default()),
    (1000, lambda: select(2)),
    (300, lambda: W().on_remove()),
    (600, expect_dialog("08-remove-confirm", must=("Запись будет удалена из меню загрузки GRUB",),
                        must_not=("dnf", "удалить ядро полностью", "Файлы ядра"))),
    (100, press("Удалить")),
    (1200, all_mode),
    (500, lambda: t.snap(W(), P("09-all-mode"))),
    (100, lambda: W().on_apply()),
    (1200, verify_grubby),
    (100, lambda: W().on_bls()),
    (600, expect_dialog("10-bls-confirm", must=("GRUB_ENABLE_BLSCFG=true", "grub2-mkconfig -o",
                                                 "/boot/grub2/grub.cfg"))),
    (100, press("Перейти на BLS")),
    (1500, lambda: t.snap(W(), P("11-bls-done"))),
    (100, verify_bls),
    (100, lambda: W().on_bls()),
    (600, expect_dialog("12-bls-already", must=("Загрузчик работает в режиме BLS",))),
    (100, press("Закрыть")),
    (300, lambda: None),
]
sys.exit(t.run(app, steps))
