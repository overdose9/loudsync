"""The application: one instance, a tray icon, a window on demand.

Reads the engine's state every two seconds, and at once when a file in the
state directory changes. The reading happens off the main thread, so a slow
systemctl never freezes the window.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, _, core, describe, dialogs, widgets  # noqa: E402
from .style import Style  # noqa: E402
from .tray import ICON_DIR, Tray, pause_until  # noqa: E402

REFRESH_SECONDS = 2
CONFLICT_SCAN_SECONDS = 60


class LoudsyncApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.paths = core.Paths.from_env()
        self.config = None
        self.config_error = ""
        self.status = None
        self.headline = None
        self.conflicts = []
        self.window = None
        self.wizard = None
        self.tray = None
        self.style = None
        self._events = []
        self._log_key = None
        self._refreshing = False
        self._scanning = False
        self._monitor = None

    # --- lifecycle --------------------------------------------------------

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_application_name("loudsync")
        Gtk.IconTheme.get_default().append_search_path(os.path.normpath(ICON_DIR))
        Gtk.Window.set_default_icon_name("loudsync")
        self.style = Style()
        self.style.listeners.append(self._redraw)
        self.reload_config()
        self.status = core.read_status(self.paths, self.config, self.config_error)
        self.headline = describe.headline_for(self.status)
        self.tray = Tray(self)
        if self.tray.available:
            self.hold()     # the icon keeps the app alive with no window open
        self._watch_state_dir()
        self.refresh()
        self.scan_conflicts()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)
        GLib.timeout_add_seconds(CONFLICT_SCAN_SECONDS, self._scan_tick)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        # --background is what the login autostart passes: tray only. Without
        # a tray to live in, the window is the only way to be seen.
        if "--background" not in args or not self.tray.available:
            self.show_window()
        return 0

    def quit_tray(self):
        if self.window is not None:
            self.window.destroy()
        self.quit()

    # --- state ------------------------------------------------------------

    def reload_config(self):
        try:
            self.config = core.read_config(self.paths)
            self.config_error = ""
        except FileNotFoundError:
            self.config, self.config_error = None, ""
        except core.ConfigError as e:
            self.config = None
            self.config_error = _("The config file has an error: {error}").format(error=e)
        if not os.access(self.paths.engine, os.X_OK):
            self.config_error = _("The loudsync engine is not installed at {path}. Run install.sh.").format(
                path=self.paths.engine)

    def _watch_state_dir(self):
        os.makedirs(self.paths.state_home, exist_ok=True)
        self._monitor = Gio.File.new_for_path(self.paths.state_home).monitor_directory(
            Gio.FileMonitorFlags.NONE, None)
        self._monitor.set_rate_limit(500)
        self._monitor.connect("changed", lambda *_a: self.refresh())

    def _tick(self):
        self.refresh()
        return True

    def _scan_tick(self):
        self.scan_conflicts()
        return True

    def _read_events(self):
        # Re-parse the log only when it changed: it can be 50 MB.
        try:
            st = os.stat(self.paths.log)
            key = (st.st_ino, st.st_size, st.st_mtime_ns)
        except FileNotFoundError:
            key = None
        if key != self._log_key:
            self._log_key = key
            self._events = core.read_log_events(self.paths)
        return self._events

    def _config_changed(self):
        try:
            st = os.stat(self.paths.config_file)
            key = (st.st_ino, st.st_mtime_ns)
        except FileNotFoundError:
            key = None
        changed = key != getattr(self, "_config_key", None)
        self._config_key = key
        return changed

    def refresh(self):
        if self._refreshing:
            return
        if self._config_changed():
            self.reload_config()    # edited by hand, or by the engine's install
        self._refreshing = True
        config, config_error = self.config, self.config_error

        def work():
            try:
                status = core.read_status(self.paths, config, config_error,
                                          events=self._read_events())
            except Exception as e:  # never let a bad read kill the tray
                print(f"loudsync-gui: could not read state: {e}", file=sys.stderr)
                status = None
            GLib.idle_add(self._apply, status)

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status):
        self._refreshing = False
        if status is None:
            return False
        was_running = self.status.running if self.status else False
        self.status = status
        if was_running and not status.running:
            self.scan_conflicts()   # a run just finished: it may have left some
        self._redraw()
        return False

    def _redraw(self):
        self.headline = describe.headline_for(self.status, len(self.conflicts))
        if self.tray is not None and self.tray.available:
            self.tray.update(self.headline, self.status, len(self.conflicts))
        if self.window is not None:
            self.window.update()

    def scan_conflicts(self):
        if self._scanning or self.config is None or not os.path.isdir(self.config.local_dir):
            return
        self._scanning = True
        folder = self.config.local_dir

        def work():
            try:
                found = core.find_conflicts(folder)
            except OSError:
                found = self.conflicts
            GLib.idle_add(done, found)

        def done(found):
            self._scanning = False
            self.conflicts = found
            self._redraw()
            return False

        threading.Thread(target=work, daemon=True).start()

    # --- windows ----------------------------------------------------------

    def show_window(self, page=None):
        if self.headline and self.headline.state == core.SETUP and page is None \
                and not self.status.configured:
            self.show_wizard()
            return
        if self.window is None:
            from .window import MainWindow
            self.window = MainWindow(self)
            self.window.connect("destroy", self._window_gone)
            self.window.update()
        if page:
            self.window.show_page(page)
        self.window.present()

    def _window_gone(self, *_args):
        self.window = None

    def show_wizard(self):
        if self.wizard is not None:
            self.wizard.present()
            return
        from .wizard import Wizard
        self.wizard = Wizard(self, self.window)
        self.wizard.connect("destroy", self._wizard_gone)
        self.add_window(self.wizard)
        self.wizard.present()

    def _wizard_gone(self, *_args):
        self.wizard = None
        self.reload_config()
        self.refresh()

    def parent(self):
        return self.window if self.window is not None and self.window.get_visible() else None

    # --- actions ----------------------------------------------------------

    def guard(self, action, failure_title):
        """Run an action; if it fails, say so where the person will see it."""
        try:
            action()
        except (RuntimeError, OSError, core.ConfigError) as e:
            self.report(failure_title, str(e))
        self.refresh()

    def report(self, title, text):
        parent = self.parent()
        if parent is not None:
            widgets.message(parent, title, text)
        else:
            note = Gio.Notification.new(title)
            note.set_body(text)
            note.set_priority(Gio.NotificationPriority.HIGH)
            self.send_notification(None, note)

    def sync_now(self):
        self.guard(lambda: core.sync_now(self.paths), _("Could not start a sync"))

    def pause(self, seconds):
        self.guard(lambda: core.pause(pause_until(seconds)), _("Could not pause syncing"))

    def resume(self):
        self.guard(core.resume, _("Could not resume syncing"))

    def turn_on(self):
        self.guard(lambda: core.set_automation(True), _("Could not turn on automatic sync"))

    def open_folder(self):
        if self.config is not None and os.path.isdir(self.config.local_dir):
            widgets.open_path(self.config.local_dir)

    def open_log(self):
        if os.path.exists(self.paths.log):
            widgets.open_path(self.paths.log)

    def review_plan(self):
        dialogs.review_plan(self, self.parent())


def main(argv=None):
    # The window class docks and window lists use to find the menu entry
    # (loudsync.desktop) and its icon. Left alone it would be "loudsync-gui".
    GLib.set_prgname("loudsync")
    Gdk.set_program_class("loudsync")
    app = LoudsyncApp()
    return app.run(argv if argv is not None else sys.argv)
