# -*- coding: utf-8 -*-
"""
grubby_core — основная логика grubby-gui, без зависимости от GTK.

* Backend      — связь с привилегированным помощником (pkexec)
* parse_info   — разбор вывода `grubby --info=...`
* format_cmd   — команда grubby в виде строки для показа/копирования
* PRESETS      — каталог популярных параметров ядра
* prepare_demo_root — окружение для демо-режима (поддельный grubby)

Совместим с Python 3.6+.
"""

import json
import os
import shutil
import subprocess
import sys
import threading

APP_ID = "io.github.grubbygui"
APP_NAME = "Менеджер загрузки GRUB2"
VERSION = "1.0.1"

INSTALLED_HELPER = "/usr/libexec/grubby-gui/grubby-gui-helper"
HERE = os.path.dirname(os.path.realpath(__file__))


# ═══════════════════════════════════════════════════════════════════════════
#  Каталог популярных параметров ядра: (категория, [(параметр, описание, edit)])
#  edit=True — значение нужно уточнить перед добавлением
# ═══════════════════════════════════════════════════════════════════════════
PRESETS = [
    ("Управление питанием процессора", [
        ("amd_pstate=disable", "Отключить драйвер AMD P-State (управление частотой процессоров AMD)", False),
        ("intel_pstate=disable", "Отключить драйвер Intel P-State (управление частотой процессоров Intel)", False),
        ("intel_idle.max_cstate=1", "Ограничить глубину простоя процессоров Intel состоянием C1", True),
        ("processor.max_cstate=1", "Ограничить максимальное состояние простоя процессора (драйвер ACPI processor)", True),
    ]),
    ("ACPI, IOMMU и оборудование", [
        ("acpi=off", "Отключить ACPI — может нарушить управление питанием и обнаружение оборудования", False),
        ("iommu=pt", "IOMMU в режиме passthrough по умолчанию (другие значения: soft, off и др.)", False),
        ("iommu.strict=0", "Отключить строгий (синхронный) сброс IOTLB при освобождении DMA-отображений", False),
    ]),
    ("Графика и видеодрайверы", [
        ("i915.enable_dc=0", "Intel i915: отключить энергосбережение дисплейного блока (DC-состояния)", False),
        ("i915.enable_drrs=0", "Intel i915: отключить динамическое переключение частоты обновления (DRRS)", False),
        ("i915.enable_fbc=0", "Intel i915: отключить сжатие кадрового буфера (FBC)", False),
        ("i915.enable_psr=0", "Intel i915: отключить Panel Self Refresh (PSR)", False),
        ("i915.force_probe=<device_id>", "Intel i915: принудительно использовать драйвер для указанного ID устройства (если версия драйвера это поддерживает)", True),
        ("i915.modeset=1", "Intel i915: включить настройку видеорежима ядром (KMS)", False),
        ("nomodeset", "Запретить драйверам ядра настраивать видеорежим (KMS) — помогает при чёрном экране", False),
        ("nouveau.modeset=0", "Nouveau (NVIDIA): отключить настройку видеорежима", False),
    ]),
    ("Звук", [
        ("snd_hda_intel.dmic_detect=0", "Intel HDA: отключить обнаружение цифровых микрофонов (DMIC)", False),
        ("snd_hda_intel.power_save=0", "Intel HDA: отключить энергосбережение аудиоустройства", False),
    ]),
    ("Безопасность и аудит", [
        ("audit=0", "Отключить подсистему аудита ядра", False),
        ("enforcing=0", "Перевести SELinux в режим permissive (если SELinux включён)", False),
        ("mitigations=off", "Отключить защиту от аппаратных уязвимостей — снижает безопасность системы", False),
    ]),
    ("Файловые системы", [
        ("fsck.mode=force", "Принудительно проверять файловые системы при загрузке (systemd-fsck)", False),
        ("fsck.repair=yes", "Автоматически исправлять найденные ошибки файловых систем (systemd-fsck)", False),
    ]),
    ("Сеть", [
        ("ipv6.disable=1", "Отключить поддержку IPv6 в ядре", False),
    ]),
    ("Загрузка и журналирование", [
        ("loglevel=7", "Выводить все сообщения ядра, включая отладочные", True),
        ("quiet", "Уменьшить количество сообщений при загрузке", False),
        ("rhgb", "Графический экран загрузки (Red Hat Graphical Boot)", False),
        ("systemd.unit=multi-user.target", "Загрузка без графического окружения (multi-user.target)", False),
    ]),
]

# Параметры, изменение которых может помешать загрузке
RISKY_REMOVE = ("ro", "rw")
RISKY_ADD = ("init", "selinux", "acpi")


# ═══════════════════════════════════════════════════════════════════════════
#  Разбор вывода grubby
# ═══════════════════════════════════════════════════════════════════════════
def split_args(s):
    """Делит строку параметров по пробелам, сохраняя кавычки внутри токенов."""
    out, cur, quote = [], [], False
    for ch in s or "":
        if ch == '"':
            quote = not quote
            cur.append(ch)
        elif ch.isspace() and not quote:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def arg_key(token):
    return token.split("=", 1)[0]


def kernel_version(path):
    base = os.path.basename(path or "")
    return base[len("vmlinuz-"):] if base.startswith("vmlinuz-") else base


def parse_info(text):
    """Разбирает вывод `grubby --info=...` (BLS и старый формат) в список словарей."""
    entries, cur = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("index="):
            try:
                idx = int(line.split("=", 1)[1].strip().strip('"'))
            except ValueError:
                continue
            cur = {"index": idx}
            entries.append(cur)
            continue
        if cur is None:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = v[1:-1]
            cur[k.strip()] = v
        else:
            cur["note"] = line
    for e in entries:
        e["version"] = kernel_version(e.get("kernel", ""))
        e["argv"] = split_args(e.get("args", ""))
        if not e.get("title"):
            e["title"] = e.get("note") or os.path.basename(e.get("kernel", "")) \
                or "Запись %d" % e["index"]
    return entries


def parse_default_index(text):
    try:
        return int((text or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def shell_quote(a):
    if a and all(c.isalnum() or c in "-_=./:,+@%" for c in a):
        return a
    return "'" + a.replace("'", "'\\''") + "'"


def format_cmd(argv, prog="grubby"):
    return prog + " " + " ".join(shell_quote(a) for a in argv)


def build_update_argv(entry, add, remove, all_entries=False, no_etc=False):
    """Аргументы grubby для изменения параметров ядра (None, если менять нечего)."""
    if not entry or not (add or remove):
        return None
    target = "ALL" if all_entries else entry.get("kernel", "")
    argv = ["--update-kernel=" + target]
    if add:
        argv.append("--args=" + " ".join(add))
    if remove:
        argv.append("--remove-args=" + " ".join(remove))
    if all_entries and no_etc:
        argv.append("--no-etc-grub-update")
    return argv


def is_bls(status):
    """status — ответ помощника на bls-status. True/False, None — неизвестно."""
    if not status or not status.get("default_grub_exists"):
        return None
    return (status.get("blscfg") or "").lower() == "true"


# ═══════════════════════════════════════════════════════════════════════════
#  Связь с привилегированным помощником
# ═══════════════════════════════════════════════════════════════════════════
class HelperError(Exception):
    pass


class Backend(object):
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.next_id = 1
        self.ready_info = {}
        self.demo = os.environ.get("GRUBBY_GUI_DEMO")  # путь к поддельному grubby

    def helper_path(self):
        local = os.path.join(HERE, "grubby-gui-helper")
        if os.path.exists(local):                     # запуск из папки с исходниками
            return local
        if os.access(INSTALLED_HELPER, os.X_OK):      # установлено в /usr
            return INSTALLED_HELPER
        # установлено с другим PREFIX: <prefix>/share/grubby-gui -> <prefix>/libexec/…
        return os.path.normpath(os.path.join(HERE, "..", "..", "libexec",
                                             "grubby-gui", "grubby-gui-helper"))

    def command(self):
        helper = self.helper_path()
        if self.demo:
            root = os.environ.get("GRUBBY_GUI_DEMO_ROOT") or os.path.expanduser(
                "~/.cache/grubby-gui-demo-root")
            prepare_demo_root(root)
            mk = os.path.join(os.path.dirname(os.path.abspath(self.demo)),
                              "fake-grub2-mkconfig")
            return [sys.executable, helper, "--grubby", self.demo,
                    "--fakeroot", root, "--mkconfig", mk]
        if os.geteuid() == 0:
            return [sys.executable, helper]
        if not shutil.which("pkexec"):
            raise HelperError(
                "Не найден pkexec (пакет polkit).\n"
                "Установите его или запустите программу от root.")
        if helper == INSTALLED_HELPER:
            # для установленного помощника есть polkit-политика
            return ["pkexec", helper]
        return ["pkexec", sys.executable, helper]

    def start(self):
        self.stop()
        cmd = self.command()
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, universal_newlines=True, bufsize=1)
        except OSError as e:
            raise HelperError("Не удалось запустить помощник: %s" % e)
        line = self.proc.stdout.readline()
        if not line:
            rc = self.proc.wait()
            err = (self.proc.stderr.read() or "").strip()
            self.proc = None
            if rc in (126, 127) and not err:
                raise HelperError("Аутентификация отменена или не пройдена.")
            if "authentication agent" in err.lower():
                raise HelperError(
                    "Не найден агент polkit для запроса пароля.\n"
                    "Запустите программу из графической сессии (GNOME, KDE, Xfce…).")
            raise HelperError(err or "Помощник завершился с кодом %d." % rc)
        try:
            self.ready_info = json.loads(line)
        except ValueError:
            raise HelperError("Помощник ответил непонятно: %s" % line.strip())
        if not self.ready_info.get("grubby"):
            raise HelperError(
                "grubby не найден в системе.\nУстановите его: sudo dnf install grubby")
        return self.ready_info

    def _request(self, payload):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                raise HelperError("Привилегированный помощник не запущен.")
            payload["id"] = self.next_id
            self.next_id += 1
            try:
                self.proc.stdin.write(json.dumps(payload) + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
            except (OSError, ValueError) as e:
                raise HelperError("Связь с помощником потеряна: %s" % e)
            if not line:
                raise HelperError("Помощник неожиданно завершился.")
            return json.loads(line)

    def call(self, argv):
        """Выполнить grubby с аргументами argv. -> {"rc", "out", "err"}"""
        return self._request({"argv": argv})

    def op(self, name):
        """Специальная операция помощника: bls-status, enable-bls."""
        return self._request({"op": name})

    def stop(self):
        p, self.proc = self.proc, None
        if p:
            try:
                p.stdin.close()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════
#  Демо-режим: поддельная файловая система для проверки перехода на BLS
# ═══════════════════════════════════════════════════════════════════════════
DEMO_DEFAULT_GRUB = """GRUB_TIMEOUT=5
GRUB_DISTRIBUTOR="$(sed 's, release .*$,,g' /etc/system-release)"
GRUB_DEFAULT=saved
GRUB_DISABLE_SUBMENU=true
GRUB_TERMINAL_OUTPUT="console"
GRUB_CMDLINE_LINUX="resume=/dev/mapper/ro-swap rd.lvm.lv=ro/root rd.lvm.lv=ro/swap rhgb quiet"
GRUB_DISABLE_RECOVERY="true"
GRUB_ENABLE_BLSCFG=false
"""


def prepare_demo_root(root):
    """Создать (если нет) демо-каталог: /etc/default/grub в режиме не-BLS и т.д."""
    files = {
        "etc/default/grub": DEMO_DEFAULT_GRUB,
        "boot/grub2/grub.cfg": "# демо: старый grub.cfg (не BLS)\nmenuentry 'Linux' {\n}\n",
        "boot/loader/entries/demo-%s.conf" % os.uname()[2]:
            "title Demo\nversion %s\nlinux /vmlinuz-%s\n" % (os.uname()[2], os.uname()[2]),
    }
    for rel, content in files.items():
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            d = os.path.dirname(p)
            if not os.path.isdir(d):
                os.makedirs(d)
            with open(p, "w") as f:
                f.write(content)
