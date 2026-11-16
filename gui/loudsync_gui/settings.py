"""Settings and Filters: the config file and the filter file, as forms.

Everything here is written to the same files the command line uses. Nothing
is kept on the side.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import _, core, dialogs, widgets  # noqa: E402

CONFLICT_LABELS = {
    "newer": _("Keep the newer one"),
    "older": _("Keep the older one"),
    "larger": _("Keep the larger one"),
    "smaller": _("Keep the smaller one"),
    "path1": _("Always keep this computer's"),
    "path2": _("Always keep the remote's"),
    "none": _("Keep both, pick no winner"),
}

BACKEND_LABELS = {"drive": "Google Drive", "dropbox": "Dropbox", "onedrive": "OneDrive"}

# (key, title, help, lower, upper, unit)
ADVANCED = (
    ("TRANSFERS", _("Parallel transfers"), _("Lower on a slow link or a low-powered machine."), 1, 64, ""),
    ("CHECKERS", _("Parallel checks"), None, 1, 128, ""),
    ("MAX_QUIET_SKIPS", _("Most runs to postpone in a row"),
     _("Something writing constantly must not be able to stop backups."), 1, 100, ""),
    ("CONFLICT_RACE_SECONDS", _("A conflict counts as a race below"),
     _("Versions closer than this are reported as one file saved mid-sync."), 0, 86400, "s"),
    ("FAIL_THRESHOLD", _("Failures before the first alert"), None, 1, 1000, ""),
    ("REMIND_EVERY", _("Remind every N failures after that"), None, 1, 10000, ""),
    ("WATCH_DEBOUNCE", _("Wait after a change before uploading"), None, 1, 600, "s"),
    ("MAX_REPO_DEPTH", _("How deep to look for git repos"), None, 1, 64, ""),
    ("LOG_MAX_MB", _("Rotate the log past"), _("0 never rotates."), 0, 10000, "MB"),
    ("LOG_KEEP", _("Old logs to keep"), None, 1, 50, ""),
)


def spin(lower, upper):
    s = Gtk.SpinButton.new_with_range(lower, upper, 1)
    s.set_digits(0)
    s.set_numeric(True)
    return s


class SettingsPage:
    def __init__(self, app, window):
        self.app = app
        self.window = window
        self.fields = {}          # key -> (get, set)
        self.loading = False
        self.widget, box = widgets.page_box()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(self.widget, True, True, 0)
        self.widget = outer
        box.pack_start(widgets.heading(_("Settings"), "x-large"), False, False, 0)

        # What to sync
        box.pack_start(widgets.section(_("What to sync")), False, False, 0)
        frame, rows = widgets.framed_list()
        self.folder = Gtk.FileChooserButton(title=_("Folder to sync"),
                                            action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.folder.connect("file-set", lambda *_a: self.changed())
        rows.add(widgets.row(_("Folder on this computer"),
                             _("Everything inside it syncs, except git repos and secret files."),
                             self.folder))
        account = Gtk.Box(spacing=6)
        self.remote = Gtk.ComboBoxText()
        self.remote.connect("changed", lambda *_a: self.changed())
        account.pack_start(self.remote, False, False, 0)
        account.pack_start(widgets.button(_("Connect another…"), self.connect_another), False, False, 0)
        rows.add(widgets.row(_("Cloud account"), _("Connected with rclone."), account))
        self.remote_path = Gtk.Entry(width_chars=18)
        self.remote_path.connect("changed", lambda *_a: self.changed())
        rows.add(widgets.row(_("Folder in the cloud"), None, self.remote_path))
        box.pack_start(frame, False, False, 0)
        self.fields["LOCAL_DIR"] = (self._get_folder, self._set_folder)
        self.fields["REMOTE"] = (self._get_remote, self._set_remote)

        # Behaviour
        box.pack_start(widgets.section(_("Behaviour")), False, False, 0)
        frame, rows = widgets.framed_list()
        rows.add(widgets.row(_("Desktop notifications"),
                             _("The whole point: you hear about it when something breaks."),
                             self._switch("NOTIFY")))
        versions = Gtk.Box(spacing=6)
        versions.pack_start(widgets.button(_("Open versions"), self.open_versions), False, False, 0)
        versions.pack_start(self._switch("KEEP_LOCAL_VERSIONS"), False, False, 0)
        rows.add(widgets.row(_("Keep local copies of overwritten files"),
                             _("When a change from the remote replaces a file here, the old one "
                               "is kept in a dated folder."), versions))
        rows.add(widgets.row(_("Wait for the folder to go quiet"),
                             _("Don't start a sync while a file was written in the last N "
                               "seconds. 0 turns it off."), self._spin("QUIET_SECONDS", 0, 3600)))
        rows.add(widgets.row(_("Safety brake (%)"),
                             _("Stop if a run would delete more than this share of either side."),
                             self._spin("MAX_DELETE_PERCENT", 1, 100)))
        self.policy = Gtk.ComboBoxText()
        for key, text in CONFLICT_LABELS.items():
            self.policy.append(key, text)
        self.policy.connect("changed", lambda *_a: self.changed())
        self.fields["CONFLICT_RESOLVE"] = (lambda: self.policy.get_active_id() or "newer",
                                           lambda v: self.policy.set_active_id(v))
        rows.add(widgets.row(_("When a file changed on both sides"),
                             _("The other version is always kept beside it."), self.policy))
        box.pack_start(frame, False, False, 0)

        # Startup: these act at once. They are about the session and systemd,
        # not the config file.
        box.pack_start(widgets.section(_("Startup")), False, False, 0)
        frame, rows = widgets.framed_list()
        self.tray_switch = Gtk.Switch()
        self.tray_switch.connect("notify::active", self._on_autostart)
        rows.add(widgets.row(_("Show the icon in the tray at login"), None, self.tray_switch))
        self.auto_switch = Gtk.Switch()
        self.auto_switch.connect("notify::active", self._on_automation)
        rows.add(widgets.row(_("Sync automatically"),
                             _("Uploads within seconds, checks the cloud every few seconds."),
                             self.auto_switch))
        box.pack_start(frame, False, False, 0)

        # Advanced
        advanced = Gtk.Expander(label=_("Advanced"))
        advanced.set_margin_top(12)
        frame, rows = widgets.framed_list()
        for key, title, help_text, lower, upper, unit in ADVANCED:
            label = f"{title} ({unit})" if unit else title
            rows.add(widgets.row(label, help_text, self._spin(key, lower, upper)))
        self.rclone_bin = Gtk.Entry(width_chars=22, placeholder_text=_("found automatically"))
        self.rclone_bin.connect("changed", lambda *_a: self.changed())
        self.fields["RCLONE_BIN"] = (lambda: self.rclone_bin.get_text().strip(),
                                     lambda v: self.rclone_bin.set_text(v))
        rows.add(widgets.row(_("rclone program"), _("Leave empty unless you have more than one."),
                             self.rclone_bin))
        advanced.add(frame)
        box.pack_start(advanced, False, False, 0)

        self.problems = widgets.label()
        self.problems.set_no_show_all(True)
        box.pack_start(self.problems, False, False, 6)

        # Action bar, always visible under the scrolled form.
        bar = Gtk.ActionBar()
        bar.pack_start(widgets.button(_("Open config file"), self.open_config))
        self.apply_button = widgets.button(_("Apply"), self.apply, suggested=True)
        self.revert_button = widgets.button(_("Revert"), self.load)
        bar.pack_end(self.apply_button)
        bar.pack_end(self.revert_button)
        outer.pack_end(bar, False, False, 0)

        self.remotes = []
        self.loaded = None
        self.load_remotes()
        self.load()

    # --- controls ---------------------------------------------------------

    def _switch(self, key):
        s = Gtk.Switch()
        s.connect("notify::active", lambda *_a: self.changed())
        self.fields[key] = (lambda: "1" if s.get_active() else "0",
                            lambda v: s.set_active(v == "1"))
        return s

    def _spin(self, key, lower, upper):
        s = spin(lower, upper)
        s.connect("value-changed", lambda *_a: self.changed())
        self.fields[key] = (lambda: str(s.get_value_as_int()),
                            lambda v: s.set_value(float(v) if v.isdigit() else 0))
        return s

    def _get_folder(self):
        path = self.folder.get_filename()
        return core.contract_home(path, self.app.paths.home) if path else ""

    def _set_folder(self, value):
        folder = core.expand_home(value, self.app.paths.home)
        if os.path.isdir(folder):
            self.folder.set_filename(folder)
        else:
            self.folder.unselect_all()

    def _get_remote(self):
        name = self.remote.get_active_id() or ""
        return f"{name}:{self.remote_path.get_text().strip()}" if name else ""

    def _set_remote(self, value):
        name, _sep, path = value.partition(":")
        if name and name not in [n for n, _b in self.remotes]:
            self.remote.append(name, _("{name} (not found in rclone)").format(name=name))
        self.remote.set_active_id(name)
        self.remote_path.set_text(path)

    # --- loading and applying ---------------------------------------------

    def load_remotes(self, select=None):
        rclone = core.find_rclone(self.app.config, self.app.paths.home)

        def work():
            try:
                remotes = core.list_remotes(rclone) if rclone else []
            except (OSError, RuntimeError):
                remotes = []
            GLib.idle_add(done, remotes)

        def done(remotes):
            self.remotes = remotes
            current = select or self.remote.get_active_id()
            self.loading = True
            self.remote.remove_all()
            for name, backend in remotes:
                self.remote.append(name, f"{name} ({BACKEND_LABELS.get(backend, backend)})")
            self.loading = False
            if self.app.config is not None:
                self._set_remote(f"{current or self.app.config.remote_name}:"
                                 f"{self.remote_path.get_text() or self.app.config.remote_path}")
            self.changed()
            return False

        threading.Thread(target=work, daemon=True).start()

    def load(self):
        cfg = self.app.config
        self.loaded = dict(cfg.values) if cfg is not None else None
        self.loading = True
        values = cfg.values if cfg is not None else core.DEFAULTS
        for key, (_get, set_) in self.fields.items():
            set_(values.get(key, core.DEFAULTS.get(key, "")))
        self.loading = False
        self.sync_startup()
        self.changed()

    def sync_startup(self):
        self.loading = True
        self.tray_switch.set_active(core.autostart_enabled(self.app.paths))
        a = self.app.status.automation if self.app.status else None
        self.auto_switch.set_active(bool(a and a.enabled))
        self.auto_switch.set_sensitive(bool(a and a.installed))
        self.loading = False

    def update(self):
        # The form follows the file only when the file changed and nothing is
        # being edited: reloading under someone's typing would eat it.
        cfg = self.app.config
        current = dict(cfg.values) if cfg is not None else None
        if current != self.loaded and not self.pending():
            self.load()
        else:
            self.sync_startup()

    def pending(self):
        cfg = self.app.config
        if cfg is None:
            return {}
        out = {}
        for key, (get, _set) in self.fields.items():
            value = get()
            if value != cfg.values.get(key, ""):
                out[key] = value
        return out

    def changed(self):
        if self.loading:
            return
        pending = self.pending()
        self.apply_button.set_sensitive(bool(pending))
        self.revert_button.set_sensitive(bool(pending))
        self.problems.hide()

    def apply(self):
        updates = self.pending()
        if not updates:
            return
        problems = core.validate(updates, self.app.paths.home)
        if problems:
            self.problems.set_markup("<b>" + GLib.markup_escape_text("\n".join(problems)) + "</b>")
            self.problems.get_style_context().add_class("loudsync-dot-error")
            self.problems.show()
            return
        if "LOCAL_DIR" in updates or "REMOTE" in updates:
            dialogs.change_pair(self.app, self.window, updates)
        else:
            try:
                core.write_config(self.app.paths, updates)
            except (OSError, core.ConfigError) as e:
                widgets.message(self.window, _("The settings were not saved"), str(e))
                return
            # The watcher reads the config once, when it starts.
            core.restart_watcher()
        self.app.reload_config()
        self.load()

    # --- buttons ----------------------------------------------------------

    def connect_another(self):
        name = dialogs.connect_account(self.app, self.window)
        if name:
            self.load_remotes(select=name)

    def open_versions(self):
        path = self.app.paths.state("versions")
        os.makedirs(path, exist_ok=True)
        widgets.open_path(path)

    def open_config(self):
        widgets.open_path(self.app.paths.config_file)

    def _on_autostart(self, switch, _param):
        if self.loading:
            return
        exec_path = os.path.realpath(sys.argv[0])
        core.set_autostart(self.app.paths, switch.get_active(), exec_path)

    def _on_automation(self, switch, _param):
        if self.loading:
            return
        on = switch.get_active()
        if not on and not widgets.confirm(
                self.window, _("Turn off automatic sync?"),
                _("Nothing will sync until you turn it back on, not even after a restart. "
                  "To stop for a while, pause instead."), _("Turn off"), destructive=True):
            self.sync_startup()
            return
        self.app.guard(lambda: core.set_automation(on), _("Could not change automatic sync"))


class FiltersPage:
    def __init__(self, app, window):
        self.app = app
        self.window = window
        self.widget, box = widgets.page_box()
        box.pack_start(widgets.heading(_("Filters"), "x-large"), False, False, 0)
        box.pack_start(widgets.label(
            _("Files matching these rules never leave this computer. Git repositories are "
              "excluded on their own and are listed below. Rules use rclone's filter syntax: "
              "one per line, starting with - to exclude.")), False, False, 0)
        box.pack_start(widgets.label(
            _("Saving reconciles the sync on the next run. Nothing is deleted. Filters go by "
              "name, not content: a password inside a document still gets uploaded."), dim=True),
            False, False, 0)
        self.view = Gtk.TextView(monospace=True, left_margin=8, right_margin=8, top_margin=6,
                                 bottom_margin=6)
        self.view.get_buffer().connect("changed", lambda *_a: self.changed())
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(260)
        scroller.add(self.view)
        frame = Gtk.Frame()
        frame.add(scroller)
        box.pack_start(frame, False, False, 6)
        buttons = Gtk.Box(spacing=6)
        self.save_button = widgets.button(_("Save"), self.save, suggested=True)
        self.revert_button = widgets.button(_("Revert"), self.load)
        buttons.pack_end(self.save_button, False, False, 0)
        buttons.pack_end(self.revert_button, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        self.repos = Gtk.Expander()
        self.repo_list = widgets.label(mono=True, selectable=True)
        self.repos.add(self.repo_list)
        box.pack_start(self.repos, False, False, 12)
        self.saved = None
        self.load()

    def path(self):
        cfg = self.app.config
        return cfg["FILTERS_BASE"] if cfg else self.app.paths.filters_base_default

    def text(self):
        buf = self.view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

    def load(self):
        self.saved = core.read_text(self.path())
        self.view.get_buffer().set_text(self.saved)
        self.changed()

    def changed(self):
        dirty = self.saved is not None and self.text() != self.saved
        self.save_button.set_sensitive(dirty)
        self.revert_button.set_sensitive(dirty)

    def save(self):
        try:
            core.write_text(self.path(), self.text())
        except OSError as e:
            widgets.message(self.window, _("The filters were not saved"), str(e))
            return
        self.load()

    def update(self):
        repos = self.app.status.repos
        self.repos.set_label(_("Git repositories excluded ({n})").format(n=len(repos)))
        self.repo_list.set_text("\n".join(repos) if repos else _("None found."))
        if self.saved is not None and self.text() == self.saved:
            on_disk = core.read_text(self.path())
            if on_disk != self.saved:
                self.load()
