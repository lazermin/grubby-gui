NAME     = grubby-gui
VERSION  = 1.0.1
PREFIX  ?= /usr
DESTDIR ?=

DATADIR    = $(PREFIX)/share
LIBEXECDIR = $(PREFIX)/libexec
BINDIR     = $(PREFIX)/bin

FILES = grubby_gui.py grubby_core.py grubby-gui-helper Makefile grubby-gui.spec README.md LICENSE \
        data/grubby-gui.desktop data/grubby-gui.svg data/io.github.grubbygui.policy \
        tests/fake-grubby tests/fake-grub2-mkconfig tests/test_logic.py tests/gtktest.py \
        tests/screenshot.py tests/scenario2.py tests/scenario3.py tests/probe_deco.py

.PHONY: all install uninstall run demo demo-reset test gui-test dist rpm srpm clean

all:
	@echo "Цели: run | demo | demo-reset | test | gui-test | install | uninstall | dist | rpm"

run:
	./grubby_gui.py

# Безопасный показ интерфейса на поддельном grubby (система не меняется)
demo:
	GRUBBY_GUI_DEMO=$(CURDIR)/tests/fake-grubby ./grubby_gui.py

# Сбросить демо-состояние (записи и режим не-BLS)
demo-reset:
	rm -rf ~/.cache/grubby-gui-demo.json ~/.cache/grubby-gui-demo-root

test:
	python3 tests/test_logic.py

# GUI-сценарии в демо-режиме (нужен X-сервер; без экрана: xvfb-run make gui-test)
gui-test: demo-reset
	mkdir -p /tmp/grubby-gui-shots
	python3 tests/screenshot.py /tmp/grubby-gui-shots
	$(MAKE) demo-reset
	python3 tests/scenario2.py /tmp/grubby-gui-shots
	python3 tests/scenario3.py /tmp/grubby-gui-shots

install:
	install -Dm755 grubby_gui.py        $(DESTDIR)$(DATADIR)/$(NAME)/grubby_gui.py
	install -Dm644 grubby_core.py       $(DESTDIR)$(DATADIR)/$(NAME)/grubby_core.py
	install -Dm755 grubby-gui-helper    $(DESTDIR)$(LIBEXECDIR)/$(NAME)/grubby-gui-helper
	install -dm755                      $(DESTDIR)$(BINDIR)
	ln -sf ../share/$(NAME)/grubby_gui.py $(DESTDIR)$(BINDIR)/$(NAME)
	install -Dm644 data/grubby-gui.desktop $(DESTDIR)$(DATADIR)/applications/$(NAME).desktop
	install -Dm644 data/grubby-gui.svg  $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(NAME).svg
	install -Dm644 data/io.github.grubbygui.policy \
	        $(DESTDIR)$(DATADIR)/polkit-1/actions/io.github.grubbygui.policy

uninstall:
	rm -f  $(DESTDIR)$(BINDIR)/$(NAME)
	rm -rf $(DESTDIR)$(DATADIR)/$(NAME) $(DESTDIR)$(LIBEXECDIR)/$(NAME)
	rm -f  $(DESTDIR)$(DATADIR)/applications/$(NAME).desktop
	rm -f  $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(NAME).svg
	rm -f  $(DESTDIR)$(DATADIR)/polkit-1/actions/io.github.grubbygui.policy

dist:
	rm -rf $(NAME)-$(VERSION)
	mkdir -p $(NAME)-$(VERSION)
	cp --parents $(FILES) $(NAME)-$(VERSION)/
	tar czf $(NAME)-$(VERSION).tar.gz $(NAME)-$(VERSION)
	rm -rf $(NAME)-$(VERSION)

# Нужен пакет rpm-build:  sudo dnf install rpm-build
rpm: dist
	rpmbuild -ta $(NAME)-$(VERSION).tar.gz
	@echo; echo "Готово: ~/rpmbuild/RPMS/noarch/"

srpm: dist
	rpmbuild -ts $(NAME)-$(VERSION).tar.gz

clean:
	rm -rf $(NAME)-$(VERSION) $(NAME)-$(VERSION).tar.gz __pycache__ tests/__pycache__
