"""The setup assistant: four numbered steps, one decision each.

1 Folder, 2 Cloud account, 3 What stays out, 4 First sync. Nothing is written
until step 4, and step 4 previews before it copies anything.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os
import shutil
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import _, core, dialogs, ngettext, widgets  # noqa: E402
from .settings import BACKEND_LABELS  # noqa: E402

STEPS = (
    ("folder", _("Folder")),
    ("account", _("Cloud account")),
    ("filters", _("What stays out")),
    ("sync", _("First sync")),
)


class Wizard(Gtk.Window):
    def __init__(self, app, parent=None):
        super().__init__(title=_("Set up loudsync"), transient_for=parent, modal=bool(parent))
        self.app = app
        self.set_default_size(720, 520)
        self.set_icon_name("loudsync")
        self.index = 0
        self.finished = False

        header = Gtk.HeaderBar(title=_("Set up loudsync"))
        self.back = widgets.button(_("Back"), self.go_back)
        self.next = widgets.button(_("Next"), self.go_next, suggested=True)
        header.pack_start(self.back)
        header.pack_end(self.next)
        self.set_titlebar(header)

        body = Gtk.Box()
        steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        steps.set_margin_top(18)
        steps.set_size_request(190, -1)
        self.step_rows = []
        for i, (_name, title) in enumerate(STEPS, 1):
            line = Gtk.Box(spacing=10)
            line.get_style_context().add_class("loudsync-step")
            number = Gtk.Label(label=str(i))
            number.get_style_context().add_class("loudsync-step-number")
            text = widgets.label(title, wrap=False)
            mark = Gtk.Label(label="")
            mark.get_style_context().add_class("loudsync-dot-ok")
            line.pack_start(number, False, False, 0)
            line.pack_start(text, False, False, 0)
            line.pack_start(mark, False, False, 0)
            steps.pack_start(line, False, False, 0)
            self.step_rows.append((line, number, text, mark))
        body.pack_start(steps, False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=200)
        self.stack.add_named(self._folder_page(), "folder")
        self.stack.add_named(self._account_page(), "account")
        self.stack.add_named(self._filters_page(), "filters")
        self.stack.add_named(self._sync_page(), "sync")
        body.pack_start(self.stack, True, True, 0)
        self.body = body
        self.add(body)
        self.connect("delete-event", self._on_close)
        header.show_all()
        body.show_all()     # the caller presents the window
        self._show()

    # --- pages ------------------------------------------------------------

    def _page(self, title, intro):
        scroller, box = widgets.page_box()
        box.set_size_request(440, -1)
        box.pack_start(widgets.heading(title, "x-large"), False, False, 0)
        box.pack_start(widgets.label(intro, dim=True), False, False, 0)
        return scroller, box

    def _folder_page(self):
        page, box = self._page(_("Which folder should loudsync keep in sync?"),
                               _("Everything inside it is copied to the cloud and kept the same "
                                 "on both sides. Pick the folder you work in, not your whole "
                                 "home."))
        self.folder = Gtk.FileChooserButton(title=_("Folder to sync"),
                                            action=Gtk.FileChooserAction.SELECT_FOLDER)
        cfg = self.app.config
        if cfg is not None and os.path.isdir(cfg.local_dir) and cfg.local_dir != self.app.paths.home:
            self.folder.set_filename(cfg.local_dir)
        else:
            self.folder.set_current_folder(self.app.paths.home)
        self.folder.connect("file-set", lambda *_a: self._folder_changed())
        box.pack_start(self.folder, False, False, 12)
        self.folder_note = widgets.label(dim=True)
        box.pack_start(self.folder_note, False, False, 0)
        return page

    def _folder_changed(self):
        path = self.folder.get_filename() or ""
        problems = core.validate({"LOCAL_DIR": path}, self.app.paths.home) if path else [
            _("Choose a folder to sync.")]
        if problems:
            self.folder_note.set_text(problems[0])
        else:
            self.folder_note.set_text(_("Looking for git repositories inside…"))
            depth = self.app.config.int("MAX_REPO_DEPTH") if self.app.config else 8

            def work():
                n = core.count_repos(path, depth)
                GLib.idle_add(self._repos_found, path, n)
            threading.Thread(target=work, daemon=True).start()
        self._update_buttons()

    def _repos_found(self, path, n):
        if path != self.folder.get_filename():
            return False
        if n:
            self.folder_note.set_text(ngettext(
                "{n} git repository inside will be left out: its backup is the remote you push to.",
                "{n} git repositories inside will be left out: their backup is the remote you push to.",
                n).format(n=n))
        else:
            self.folder_note.set_text(_("No git repositories inside."))
        return False

    def _account_page(self):
        page, box = self._page(_("Where should your files go?"),
                               _("loudsync uses rclone to talk to your cloud. Pick an account you "
                                 "already connected, or connect a new one: your browser opens to "
                                 "sign in."))
        self.remote_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(self.remote_list, False, False, 6)
        expander = Gtk.Expander(label=_("Connect a new account"))
        self.connect_box = dialogs.ConnectBox(self.app, self._connected)
        expander.add(self.connect_box)
        box.pack_start(expander, False, False, 6)
        self.connect_expander = expander
        box.pack_start(widgets.label(_("Folder in the cloud")), False, False, 6)
        self.remote_path = Gtk.Entry()
        cfg = self.app.config
        self.remote_path.set_text(cfg.remote_path if cfg and cfg.remote_path else "LoudSync")
        self.remote_path.connect("changed", lambda *_a: self._update_buttons())
        box.pack_start(self.remote_path, False, False, 0)
        box.pack_start(widgets.label(_("Created if it doesn't exist yet."), dim=True), False, False, 0)
        self.remote_buttons = []
        self._fill_remotes()
        return page

    def _fill_remotes(self, select=None):
        for child in self.remote_list.get_children():
            self.remote_list.remove(child)
        self.remote_buttons = []
        rclone = core.find_rclone(self.app.config, self.app.paths.home)
        try:
            remotes = core.list_remotes(rclone) if rclone else []
        except (OSError, RuntimeError):
            remotes = []
        if not rclone:
            self.remote_list.pack_start(widgets.label(
                _("rclone is not installed, and loudsync needs it to reach any cloud. Install it "
                  "from https://rclone.org/install/, then come back to this step.")), False, False, 0)
        elif not remotes:
            self.remote_list.pack_start(widgets.label(
                _("No accounts connected yet. Connect one below."), dim=True), False, False, 0)
        group = None
        current = select or (self.app.config.remote_name if self.app.config else "")
        for name, backend in remotes:
            text = f"{name} — {BACKEND_LABELS.get(backend, backend)}"
            button = Gtk.RadioButton.new_with_label_from_widget(group, text)
            group = group or button
            button.remote = name
            button.set_active(name == current)
            button.connect("toggled", lambda *_a: self._update_buttons())
            self.remote_list.pack_start(button, False, False, 0)
            self.remote_buttons.append(button)
        self.connect_expander.set_expanded(bool(rclone) and not remotes)
        self.remote_list.show_all()

    def _connected(self, name):
        self._fill_remotes(select=name)
        self.connect_expander.set_expanded(False)
        self._update_buttons()

    def _chosen_remote(self):
        for b in self.remote_buttons:
            if b.get_active():
                return b.remote
        return ""

    def _filters_page(self):
        page, box = self._page(_("What stays out"),
                               _("Some things should never leave this computer, or have a "
                                 "better backup already. loudsync keeps them out on its own."))
        items = (
            _("Git repositories. Their backup is the remote you push to, and two-way syncing a "
              ".git folder corrupts it."),
            _("Secrets, by file name: .env files, private keys, certificates, service-account "
              "JSON, .netrc and .pgpass, VPN configs and database dumps."),
            _("A folder called _secrets, anywhere: it never leaves this computer."),
            _("Build output and caches: node_modules, virtual environments, __pycache__ and the like."),
        )
        for text in items:
            line = Gtk.Box(spacing=8)
            line.pack_start(Gtk.Label(label="•", valign=Gtk.Align.START), False, False, 0)
            line.pack_start(widgets.label(text), True, True, 0)
            box.pack_start(line, False, False, 0)
        warning = widgets.label(markup="<b>" + GLib.markup_escape_text(
            _("Filters go by file name, not by what is inside. A password pasted into a document "
              "still gets uploaded.")) + "</b>")
        warning.set_margin_top(12)
        box.pack_start(warning, False, False, 0)
        box.pack_start(widgets.label(_("You can add your own rules later, on the Filters page."),
                                     dim=True), False, False, 0)
        self.understood = Gtk.CheckButton(label=_("I understand what is and isn't filtered"))
        self.understood.connect("toggled", lambda *_a: self._update_buttons())
        box.pack_start(self.understood, False, False, 12)
        return page

    def _sync_page(self):
        page, box = self._page(_("First sync"),
                               _("First a preview that changes nothing, then the real thing when "
                                 "you say so."))
        self.summary = widgets.label(mono=True, selectable=True)
        box.pack_start(self.summary, False, False, 6)
        self.first_sync = dialogs.FirstSync(self.app, self._synced)
        box.pack_start(self.first_sync, True, True, 0)
        return page

    # --- navigation -------------------------------------------------------

    def _valid(self):
        name = STEPS[self.index][0]
        if name == "folder":
            path = self.folder.get_filename()
            return bool(path) and not core.validate({"LOCAL_DIR": path}, self.app.paths.home)
        if name == "account":
            return bool(self._chosen_remote()) and "\n" not in self.remote_path.get_text()
        if name == "filters":
            return self.understood.get_active()
        return self.finished

    def _update_buttons(self):
        running = self.first_sync.process.running
        self.back.set_sensitive(self.index > 0 and not running and not self.finished)
        self.next.set_sensitive(self._valid() and not running)
        self.next.set_label(_("Finish") if STEPS[self.index][0] == "sync" else _("Next"))

    def _show(self):
        self.stack.set_visible_child_name(STEPS[self.index][0])
        for i, (line, number, text, mark) in enumerate(self.step_rows):
            current = i == self.index
            for w in (number, text):
                ctx = w.get_style_context()
                if current:
                    ctx.remove_class("dim-label")
                else:
                    ctx.add_class("dim-label")
            mark.set_text("✓" if i < self.index else "")
        if STEPS[self.index][0] == "folder":
            self._folder_changed()
        self._update_buttons()

    def go_back(self):
        if self.index > 0:
            self.index -= 1
            self._show()

    def go_next(self):
        name = STEPS[self.index][0]
        if name == "sync":
            self._finish()
            return
        if name == "filters" and not self._prepare():
            return
        self.index += 1
        self._show()

    def _prepare(self):
        """Write the config the first sync will use. The engine reads the same
        file, so it is written before the preview, not after."""
        paths = self.app.paths
        folder = core.contract_home(self.folder.get_filename(), paths.home)
        remote = f"{self._chosen_remote()}:{self.remote_path.get_text().strip()}"
        updates = {"LOCAL_DIR": folder, "REMOTE": remote}
        problems = core.validate(updates, paths.home)
        if problems:
            widgets.message(self, _("Something needs fixing first"), "\n".join(problems))
            return False
        try:
            if not os.path.isfile(paths.config_file):
                example = core.template("loudsync.conf.example", paths)
                if not example:
                    raise OSError(_("The example config is missing. Run install.sh again."))
                core.create_config(paths, core.read_text(example))
            self.app.reload_config()
            filters = self.app.config["FILTERS_BASE"] if self.app.config else paths.filters_base_default
            if not os.path.isfile(filters):
                shipped = core.template("filters-base.txt", paths)
                if not shipped:
                    raise OSError(_("The default filters are missing. Run install.sh again."))
                os.makedirs(os.path.dirname(filters), exist_ok=True)
                shutil.copyfile(shipped, filters)
            # A timer firing mid-setup would run a normal sync on a pair that
            # has no state yet, and count the failure.
            core.hold_automation()
            core.write_config(paths, updates)
        except (OSError, core.ConfigError) as e:
            widgets.message(self, _("The settings could not be written"), str(e))
            return False
        self.app.reload_config()
        self.summary.set_text(f"{folder}\n  ⇄  {remote}")
        GLib.idle_add(lambda: self.first_sync.preview() and False)
        return True

    def _synced(self, ok):
        self.finished = ok
        self._update_buttons()

    def _finish(self):
        self.app.guard(lambda: core.set_automation(True), _("Could not turn on automatic sync"))
        try:
            core.set_autostart(self.app.paths, True, os.path.realpath(sys.argv[0]))
        except OSError:
            pass    # the tray at login is a convenience; syncing doesn't depend on it
        self.app.refresh()
        self.destroy()
        self.app.show_window("status")

    def _on_close(self, *_args):
        if self.first_sync.process.running:
            if not widgets.confirm(self, _("Stop the first sync?"),
                                   _("What was already copied stays. You can run the setup "
                                     "again from the Status page."), _("Stop"), destructive=True):
                return True
            self.first_sync.process.cancel()
        return False
