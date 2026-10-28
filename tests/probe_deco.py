#!/usr/bin/python3
# Кто рисует рамку окна: печатает режим (CSD = GTK, SSD = оконный менеджер).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gtktest as t  # noqa: E402

app = t.g.App()


def probe():
    w = app.win
    csd = "csd" in w.get_css_classes()
    print("XDG_CURRENT_DESKTOP=%s USE_CSD=%s -> рамка: %s, панель в окне: %s" % (
        os.environ.get("XDG_CURRENT_DESKTOP", ""), t.g.USE_CSD,
        "GTK (CSD)" if csd else "оконный менеджер (SSD)", w.toolbar is not None))
    if csd != t.g.USE_CSD:
        t.errors.append("режим декораций не совпал")


sys.exit(t.run(app, [(1200, probe)]))
