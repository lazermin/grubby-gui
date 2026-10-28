#!/usr/bin/python3
# Тесты без GUI: grubby_core и помощник (белый список, BLS-операции).
import glob
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import grubby_core as core  # noqa: E402

HELPER = os.path.join(ROOT, "grubby-gui-helper")
FAKE = os.path.join(HERE, "fake-grubby")
FAKE_MK = os.path.join(HERE, "fake-grub2-mkconfig")
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise SystemExit("FAIL: " + msg)
    ok += 1


# ── разбор вывода grubby ───────────────────────────────────────────────────
BLS = '''index=0
kernel="/boot/vmlinuz-5.14.0-427.el9.x86_64"
args="ro crashkernel=1G-4G:192M,4G-64G:256M,64G-:512M rd.lvm.lv=rhel/root rhgb quiet"
root="/dev/mapper/rhel-root"
initrd="/boot/initramfs-5.14.0-427.el9.x86_64.img $tuned_initrd"
title="Red Hat Enterprise Linux (5.14.0-427.el9.x86_64) 9.4 (Plow)"
id="abc-5.14.0-427.el9.x86_64"
index=1
kernel="/boot/vmlinuz-0-rescue-abc"
args="ro"
root="UUID=1234"
initrd="/boot/initramfs-0-rescue-abc.img"
title="Rescue"
id="abc-0-rescue"
'''
e = core.parse_info(BLS)
check(len(e) == 2, "две записи")
check(e[0]["version"] == "5.14.0-427.el9.x86_64", "версия из имени ядра")
check(e[0]["root"] == "/dev/mapper/rhel-root", "root")
check(e[0]["argv"][-1] == "quiet" and len(e[0]["argv"]) == 5, "argv")

LEGACY = '''index=0
kernel=/boot/vmlinuz-3.10.0-1160.el7.x86_64
args="ro crashkernel=auto rhgb quiet"
root=/dev/mapper/centos-root
initrd=/boot/initramfs-3.10.0-1160.el7.x86_64.img
title=CentOS Linux (3.10.0-1160.el7.x86_64) 7 (Core)
index=1
non linux entry
'''
e = core.parse_info(LEGACY)
check(e[0]["kernel"] == "/boot/vmlinuz-3.10.0-1160.el7.x86_64", "legacy kernel без кавычек")
check("kernel" not in e[1] and e[1]["title"] == "non linux entry", "не-Linux запись")
check(core.parse_default_index("2\n") == 2 and core.parse_default_index("") is None,
      "parse_default_index")
check(core.split_args('a b="x y" c') == ['a', 'b="x y"', 'c'], "split_args с кавычками")
check(core.format_cmd(["--args=a b"]) == "grubby '--args=a b'", "format_cmd кавычит")

ent = {"kernel": "/boot/vmlinuz-1"}
check(core.build_update_argv(ent, [], []) is None, "нет изменений — нет команды")
check(core.build_update_argv(ent, ["a", "b=1"], ["quiet"]) ==
      ["--update-kernel=/boot/vmlinuz-1", "--args=a b=1", "--remove-args=quiet"], "update argv")
check(core.build_update_argv(ent, ["a"], [], True, True) ==
      ["--update-kernel=ALL", "--args=a", "--no-etc-grub-update"], "update ALL")
check(core.is_bls({"default_grub_exists": True, "blscfg": "true"}) is True, "is_bls true")
check(core.is_bls({"default_grub_exists": True, "blscfg": None}) is False, "is_bls не задано")
check(core.is_bls({"default_grub_exists": False}) is None, "is_bls неизвестно")

# ── функции помощника (загружаем как модуль) ──────────────────────────────
loader = importlib.machinery.SourceFileLoader("helper", HELPER)
spec = importlib.util.spec_from_loader("helper", loader)
H = importlib.util.module_from_spec(spec)
loader.exec_module(H)

check(H.read_blscfg("A=1\nGRUB_ENABLE_BLSCFG=false\n") == "false", "read_blscfg false")
check(H.read_blscfg('GRUB_ENABLE_BLSCFG="true"  # c\n') == "true", "read_blscfg кавычки/коммент")
check(H.read_blscfg("#GRUB_ENABLE_BLSCFG=true\n") is None, "read_blscfg комментарий")
check(H.read_blscfg("X=1\n") is None, "read_blscfg нет")
t = H.set_blscfg("A=1\nGRUB_ENABLE_BLSCFG=false\nB=2\n")
check(t == "A=1\nGRUB_ENABLE_BLSCFG=true\nB=2\n", "set_blscfg замена")
check(H.set_blscfg("A=1\n") == "A=1\nGRUB_ENABLE_BLSCFG=true\n", "set_blscfg дописать")
check(H.set_blscfg("#GRUB_ENABLE_BLSCFG=false\n").endswith("GRUB_ENABLE_BLSCFG=true\n")
      and "#GRUB_ENABLE_BLSCFG=false" in H.set_blscfg("#GRUB_ENABLE_BLSCFG=false\n"),
      "set_blscfg не трогает комментарии")


def mkroot(blscfg="false", entries=1, efi=None):
    r = tempfile.mkdtemp(prefix="ggroot-")
    os.makedirs(os.path.join(r, "etc/default"))
    os.makedirs(os.path.join(r, "boot/loader/entries"))
    os.makedirs(os.path.join(r, "boot/grub2"))
    with open(os.path.join(r, "etc/default/grub"), "w") as f:
        f.write('GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX="rhgb quiet"\nGRUB_ENABLE_BLSCFG=%s\n' % blscfg)
    with open(os.path.join(r, "boot/grub2/grub.cfg"), "w") as f:
        f.write("old\n")
    for i in range(entries):
        open(os.path.join(r, "boot/loader/entries/e%d.conf" % i), "w").close()
    if efi:
        os.makedirs(os.path.join(r, "sys/firmware/efi"))
        for vendor, content in efi.items():
            d = os.path.join(r, "boot/efi/EFI", vendor)
            os.makedirs(d)
            with open(os.path.join(d, "grub.cfg"), "w") as f:
                f.write(content)
    return r


class C(object):
    def __init__(self, root, mk=FAKE_MK):
        self.ctx = H.Ctx([])
        self.ctx.fakeroot, self.ctx.mkconfig_override = root, mk


# UEFI: заглушка в ESP -> /boot/grub2/grub.cfg; полный конфиг в ESP -> он
stub = "search --no-floppy --fs-uuid --set=dev abcd\nset prefix=($dev)/grub2\nconfigfile $prefix/grub.cfg\n"
r = mkroot(efi={"redos": stub, "BOOT": "x" * 10})
check(H.grub_cfg_target(C(r).ctx).endswith("/boot/grub2/grub.cfg"), "UEFI заглушка -> /boot/grub2")
r = mkroot(efi={"redos": "### BEGIN /etc/grub.d/00_header ###\n" + "x" * 5000})
check(H.grub_cfg_target(C(r).ctx).endswith("/boot/efi/EFI/redos/grub.cfg"), "UEFI полный конфиг в ESP")
st = H.bls_status(C(r).ctx)
check(st["efi"] and st["grub_cfg"] == "/boot/efi/EFI/redos/grub.cfg", "bls_status UEFI путь без fakeroot")

# переход на BLS: успех
r = mkroot()
res = H.enable_bls(C(r).ctx)
check(res["rc"] == 0, "enable_bls успех: %s" % res)
txt = open(os.path.join(r, "etc/default/grub")).read()
check("GRUB_ENABLE_BLSCFG=true" in txt and 'GRUB_CMDLINE_LINUX="rhgb quiet"' in txt, "файл изменён аккуратно")
check(len(glob.glob(os.path.join(r, "etc/default/grub.grubby-gui-*.bak"))) == 1, "бэкап /etc/default/grub")
check(len(glob.glob(os.path.join(r, "boot/grub2/grub.cfg.grubby-gui-*.bak"))) == 1, "бэкап grub.cfg")
check("BLS" in open(os.path.join(r, "boot/grub2/grub.cfg")).read(), "grub.cfg перегенерирован")
check(H.bls_status(C(r).ctx)["blscfg"] == "true", "статус после перехода")

# переход на BLS: ошибка mkconfig -> откат
r = mkroot()
res = H.enable_bls(C(r, mk=shutil.which("false")).ctx)
check(res["rc"] != 0 and "откачены" in res["out"], "ошибка mkconfig -> откат")
check("GRUB_ENABLE_BLSCFG=false" in open(os.path.join(r, "etc/default/grub")).read(), "файл восстановлен")
check(open(os.path.join(r, "boot/grub2/grub.cfg")).read() == "old\n", "grub.cfg восстановлен")

# нет записей BLS -> отказ без изменений
r = mkroot(entries=0)
res = H.enable_bls(C(r).ctx)
check(res["rc"] != 0 and "нет записей" in res["err"], "пустой entries -> отказ")
check("=false" in open(os.path.join(r, "etc/default/grub")).read(), "без изменений при отказе")
check(not glob.glob(os.path.join(r, "etc/default/*.bak")), "без бэкапов при отказе")

# ── помощник как процесс: протокол и белый список ─────────────────────────
r = mkroot()
state = tempfile.mktemp(suffix=".json")
reqs = [
    {"id": 1, "argv": ["--info=ALL"]},
    {"id": 2, "argv": ["--evil"]},
    {"id": 3, "argv": ["--args"]},
    {"id": 4, "argv": ["--title=a\nb"]},
    {"id": 5, "argv": "--info=ALL"},
    {"id": 6, "op": "bls-status"},
    {"id": 7, "op": "rm-rf"},
    {"id": 8, "op": "enable-bls"},
]
args = [sys.executable, HELPER]
if os.geteuid() != 0:
    args += ["--grubby", FAKE, "--fakeroot", r, "--mkconfig", FAKE_MK]
p = subprocess.run(args, input="".join(json.dumps(x) + "\n" for x in reqs),
                   stdout=subprocess.PIPE, universal_newlines=True,
                   env=dict(os.environ, FAKE_GRUBBY_STATE=state))
lines = [json.loads(x) for x in p.stdout.splitlines()]
check(lines[0].get("ready") is True and lines[0].get("protocol") == 2, "helper READY v2")
R = {x["id"]: x for x in lines[1:]}
check(R[2]["rc"] == -1 and "не разрешён" in R[2]["err"], "запрет неизвестного ключа")
check(R[3]["rc"] == -1 and R[4]["rc"] == -1 and R[5]["rc"] == -1, "запрет некорректных argv")
check(R[7]["rc"] == -1 and "неизвестная операция" in R[7]["err"], "запрет неизвестной операции")
if os.geteuid() != 0:
    check(R[1]["rc"] == 0 and "index=0" in R[1]["out"], "helper --info=ALL")
    check(R[6]["rc"] == 0 and R[6]["data"]["blscfg"] == "false", "op bls-status")
    check(R[8]["rc"] == 0, "op enable-bls")
else:
    # от root подмены путей игнорируются
    p = subprocess.run([sys.executable, HELPER, "--grubby", "/bin/sh", "--fakeroot", r],
                       input="", stdout=subprocess.PIPE, universal_newlines=True)
    check(json.loads(p.stdout.splitlines()[0])["grubby"] != "/bin/sh", "root: --grubby игнорируется")
    c = H.Ctx(["--fakeroot", r, "--mkconfig", "/bin/sh"])
    check(c.fakeroot is None and c.mkconfig_override is None, "root: --fakeroot/--mkconfig игнорируются")

print("OK: %d проверок" % ok)
