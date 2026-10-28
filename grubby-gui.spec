Name:           grubby-gui
Version:        1.0.1
Release:        1%{?dist}
Summary:        Graphical front-end for grubby (GRUB2 boot entry manager)
Summary(ru):    Графическая оболочка для grubby (управление загрузчиком GRUB2)

License:        GPL-2.0-or-later
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  make
Requires:       python3
Requires:       python3-gobject
Requires:       gtk4 >= 4.6
Requires:       grubby
Recommends:     grub2-tools
Requires:       polkit
Requires:       hicolor-icon-theme

%description
grubby-gui is a simple GTK 4 interface for grubby: view GRUB2 boot entries,
choose the default kernel, add or remove kernel command line parameters
(for one entry or for ALL), add and remove boot entries, and switch a
non-BLS GRUB2 configuration to BootLoaderSpec (GRUB_ENABLE_BLSCFG=true).
Every action shows the exact grubby command that will be executed.

%description -l ru
grubby-gui — простой GTK 4 интерфейс для grubby: просмотр записей меню
GRUB2, выбор ядра по умолчанию, добавление и удаление параметров ядра
(для одной записи или для всех), добавление и удаление записей,
перевод загрузчика в режим BLS (GRUB_ENABLE_BLSCFG=true).
Перед выполнением показывается точная команда grubby.

%prep
%autosetup

%build
# нечего собирать

%install
%make_install PREFIX=%{_prefix}

%check
python3 -m py_compile grubby_gui.py grubby_core.py grubby-gui-helper
python3 tests/test_logic.py

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{_datadir}/%{name}/
%{_libexecdir}/%{name}/
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{name}.svg
%{_datadir}/polkit-1/actions/io.github.grubbygui.policy

%changelog
* Fri Oct 23 2026 lazermin <lazermin@users.noreply.github.com> - 1.0.1-1
- Интерфейс переписан на GTK 4; логика вынесена в grubby_core.py
- В KDE/LXQt рамку окна рисует оконный менеджер (окно растягивается за края),
  кнопки заголовка перенесены на панель внутри окна
- Обновлён каталог параметров ядра
- Переход на BLS: GRUB_ENABLE_BLSCFG=true + grub2-mkconfig, с резервными копиями и откатом
- Убрано примечание про dnf remove в подтверждении удаления записи
- В вопросе о несохранённых изменениях кнопка «Отмена» переименована в «Назад»

* Thu Oct 22 2026 lazermin <lazermin@users.noreply.github.com> - 1.0.0-1
- Первый выпуск
