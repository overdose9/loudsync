"""The tray icon: the main way loudsync is seen, like Drive's or OneDrive's.

XApp's status icon first (native on Cinnamon, and shown by MATE and Xfce
through xapp-sn-watcher), AppIndicator second (GNOME with the extension, KDE).
With neither there is no tray, and the window is the whole interface.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import _, core, icons, ngettext  # noqa: E402

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icons")
INSTALLED_ICON_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "icons", "hicolor", "scalable", "apps")


def _load_xapp():
    try:
        gi.require_version("XApp", "1.0")
        from gi.repository import XApp
    except (ValueError, ImportError):
        return None
    return XApp if XApp.StatusIcon.any_monitors() else None


def _load_ayatana():
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3
    except (ValueError, ImportError):
        return None
    return AyatanaAppIndicator3


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon_dir = os.path.normpath(ICON_DIR)
        self.menu = self._build_menu()
        self.backend = None
        xapp = _load_xapp()
        if xapp is not None:
            self.backend = "xapp"
            self.icon = xapp.StatusIcon()
            self.icon.set_name("loudsync")
            self.icon.set_secondary_menu(self.menu)
            self.icon.connect("activate", lambda *_a: app.show_window())
            self.icon.set_visible(True)
            return
        ayatana = _load_ayatana()
        if ayatana is not None:
            self.backend = "ayatana"
            self.icon = ayatana.Indicator.new(
                "loudsync", "loudsync-setup-symbolic",
                ayatana.IndicatorCategory.APPLICATION_STATUS)
            self.icon.set_icon_theme_path(self.icon_dir)
            self.icon.set_title("loudsync")
            self.icon.set_menu(self.menu)
            # AppIndicator has no left click of its own: the middle click
            # opens the window, the same as the first menu item.
            self.icon.set_secondary_activate_target(self.open_item)
            self.icon.set_status(ayatana.IndicatorStatus.ACTIVE)

    @property
    def available(self):
        return self.backend is not None

    def _item(self, text, callback=None, sensitive=True):
        item = Gtk.MenuItem(label=text)
        item.set_sensitive(sensitive)
        if callback:
            item.connect("activate", lambda *_a: callback())
        self.menu.append(item)
        return item

    def _build_menu(self):
        self.menu = Gtk.Menu()
        app = self.app
        self.status_item = self._item("loudsync", sensitive=False)
        self.menu.append(Gtk.SeparatorMenuItem())
        self.open_item = self._item(_("Open loudsync"), app.show_window)
        self.folder_item = self._item(_("Open folder"), app.open_folder)
        self.sync_item = self._item(_("Sync now"), app.sync_now)

        self.pause_item = self._item(_("Pause syncing"))
        pause_menu = Gtk.Menu()
        for text, seconds in ((_("For 1 hour"), 3600), (_("For 8 hours"), 8 * 3600),
                              (_("Until I resume"), None)):
            sub = Gtk.MenuItem(label=text)
            sub.connect("activate", lambda _i, s=seconds: app.pause(s))
            pause_menu.append(sub)
        self.pause_item.set_submenu(pause_menu)
        self.resume_item = self._item(_("Resume syncing"), app.resume)

        self.conflicts_item = self._item("", lambda: app.show_window("conflicts"))
        self.menu.append(Gtk.SeparatorMenuItem())
        self._item(_("Quit (syncing keeps running)"), app.quit_tray)
        self.menu.show_all()
        return self.menu

    def _xapp_icon(self, name):
        """The panel draws symbolic icons by theme name only: given a path,
        Cinnamon's applet looks the path up as a name and shows an empty slot.
        So an installed icon goes by name. From a checkout, where nothing is
        installed, a path is the best there is; colour icons work that way."""
        if os.path.isfile(os.path.join(INSTALLED_ICON_DIR, name + ".svg")):
            return name
        return os.path.join(self.icon_dir, name + ".svg")

    def update(self, headline, status, conflict_count):
        key = (headline.tooltip, headline.state, status.running, conflict_count,
               status.automation.paused, status.automation.running, status.configured)
        if key == getattr(self, "_shown", None):
            return
        self._shown = key
        name = icons.tray_name(headline)
        if self.backend == "xapp":
            self.icon.set_icon_name(self._xapp_icon(name))
            self.icon.set_tooltip_text(headline.tooltip)
        elif self.backend == "ayatana":
            self.icon.set_icon_full(name, headline.title)

        self.status_item.set_label(headline.tooltip)
        ready = headline.state not in (core.SETUP, core.BROKEN)
        a = status.automation
        paused = a is not None and (a.paused or not a.running)
        self.folder_item.set_sensitive(status.configured)
        self.sync_item.set_sensitive(ready and not status.running)
        self.pause_item.set_visible(ready and not paused)
        self.resume_item.set_visible(ready and paused and a is not None and a.installed)
        self.conflicts_item.set_visible(conflict_count > 0)
        self.conflicts_item.set_label(ngettext(
            "Review {n} conflict…", "Review {n} conflicts…", conflict_count).format(n=conflict_count))


def pause_until(seconds):
    return time.time() + seconds if seconds else None
