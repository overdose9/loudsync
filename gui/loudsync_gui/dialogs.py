"""Dialogs: connecting a cloud account, the first sync of a folder and a
remote, and reviewing a rename plan the engine won't apply on its own.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import shutil
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import _, core, ngettext, widgets  # noqa: E402

TERMINALS = (
    ("x-terminal-emulator", lambda argv: ["x-terminal-emulator", "-e", *argv]),
    ("gnome-terminal", lambda argv: ["gnome-terminal", "--", *argv]),
    ("konsole", lambda argv: ["konsole", "-e", *argv]),
    ("xfce4-terminal", lambda argv: ["xfce4-terminal", "-x", *argv]),
    ("xterm", lambda argv: ["xterm", "-e", *argv]),
)


WEBSITE = "https://github.com/overdose9/loudsync"


def about(app, parent=None):
    """Which loudsync this is. The version is read from the installed engine,
    the thing that actually moves the files, not from this window's own code:
    after a half-finished upgrade the two can differ, and the engine is the
    one a bug report needs."""
    paths = app.paths
    version = core.engine_version(paths) or _("unknown")
    rclone = core.rclone_version(app.config, paths.home)
    facts = [
        _("Sync engine: {path}").format(path=paths.engine),
        (_("rclone: {version}").format(version=rclone) if rclone
         else _("rclone: not found")),
        _("Settings: {path}").format(path=paths.config_file),
        _("Log: {path}").format(path=paths.log),
    ]
    dialog = Gtk.AboutDialog(transient_for=parent, modal=parent is not None)
    dialog.set_program_name("loudsync")
    dialog.set_version(version)
    dialog.set_logo_icon_name("loudsync")
    dialog.set_comments(
        _("Two-way folder sync that knows what a git repo is, refuses to upload "
          "your secrets, and shouts when it breaks.") + "\n\n" + "\n".join(facts))
    dialog.set_website(WEBSITE)
    dialog.set_website_label(_("Source code and issues"))
    dialog.set_copyright("Copyright © 2026 Sebastián Flores")
    dialog.set_license_type(Gtk.License.GPL_3_0)
    dialog.connect("response", lambda d, _r: d.destroy())
    dialog.present()
    return dialog


def open_terminal(argv):
    for binary, build in TERMINALS:
        if shutil.which(binary):
            subprocess.Popen(build(argv), start_new_session=True)
            return True
    return False


# --- Connecting a cloud account ---------------------------------------------


class ConnectBox(Gtk.Box):
    """Provider, a name, and rclone's browser sign-in. Shared by the settings
    dialog and the setup assistant."""

    def __init__(self, app, on_connected):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.app = app
        self.on_connected = on_connected
        self.provider = Gtk.ComboBoxText()
        for backend, text in core.PROVIDERS:
            self.provider.append(backend, text)
        self.provider.set_active(0)
        self.provider.connect("changed", lambda *_a: self._suggest_name())
        self.name = Gtk.Entry(width_chars=16)
        self.name.connect("changed", lambda *_a: self._validate())
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        grid.attach(widgets.label(_("Service")), 0, 0, 1, 1)
        grid.attach(self.provider, 1, 0, 1, 1)
        grid.attach(widgets.label(_("Name for this account")), 0, 1, 1, 1)
        grid.attach(self.name, 1, 1, 1, 1)
        self.pack_start(grid, False, False, 0)
        self.problem = widgets.label(dim=True)
        self.pack_start(self.problem, False, False, 0)
        buttons = Gtk.Box(spacing=6)
        self.connect_button = widgets.button(_("Connect"), self.start, suggested=True)
        self.cancel_button = widgets.button(_("Stop waiting"), self.cancel)
        self.cancel_button.set_no_show_all(True)
        other = widgets.button(_("Other provider… (opens rclone in a terminal)"), self.other)
        buttons.pack_start(self.connect_button, False, False, 0)
        buttons.pack_start(self.cancel_button, False, False, 0)
        buttons.pack_end(other, False, False, 0)
        self.pack_start(buttons, False, False, 0)
        self.process = widgets.ProcessView()
        self.process.set_no_show_all(True)
        self.pack_start(self.process, True, True, 0)
        self.existing = set()
        self.rclone = core.find_rclone(app.config, app.paths.home)
        self._refresh_existing()

    def _refresh_existing(self):
        try:
            self.existing = {n for n, _b in core.list_remotes(self.rclone)} if self.rclone else set()
        except (OSError, RuntimeError):
            self.existing = set()
        self._suggest_name()

    def _suggest_name(self):
        base = {"drive": "gdrive", "dropbox": "dropbox", "onedrive": "onedrive"}.get(
            self.provider.get_active_id(), "cloud")
        name, i = base, 2
        while name in self.existing:
            name, i = f"{base}{i}", i + 1
        self.name.set_text(name)

    def _validate(self):
        name = self.name.get_text().strip()
        problem = ""
        if not self.rclone:
            problem = _("rclone is not installed. Install it from https://rclone.org/install/ "
                        "(a single file in ~/.local/bin is enough).")
        elif not core.REMOTE_NAME_RE.match(name):
            problem = _("Use letters, numbers, spaces, dots, dashes or underscores.")
        elif name in self.existing:
            problem = _("There is already an account called {name}.").format(name=name)
        self.problem.set_text(problem)
        self.connect_button.set_sensitive(not problem and not self.process.running)
        return not problem

    def start(self):
        if not self._validate():
            return
        name, backend = self.name.get_text().strip(), self.provider.get_active_id()
        widgets.reveal(self.process)
        self.cancel_button.show()
        self.connect_button.set_sensitive(False)

        def done(code, _out, _log):
            self.cancel_button.hide()
            self._refresh_existing()
            if code == 0 and name in self.existing:
                self.process.say(_("Connected as {name}.").format(name=name))
                self.on_connected(name)
            else:
                self.process.say(_("The account was not connected. The details below say why."))
                self.process.details.set_expanded(True)
                self._validate()

        self.process.start(core.connect_remote_argv(self.rclone, name, backend),
                           _("Waiting for you to sign in, in the browser window that just opened…"),
                           done)

    def cancel(self):
        self.process.cancel()

    def other(self):
        if not open_terminal([self.rclone or "rclone", "config"]):
            widgets.message(self.get_toplevel(), _("No terminal found"),
                            _("Open a terminal and run: rclone config"))


def connect_account(app, parent):
    """Returns the new remote's name, or None."""
    dialog = Gtk.Dialog(title=_("Connect a cloud account"), transient_for=parent, modal=True,
                        use_header_bar=True)
    dialog.set_default_size(520, 360)
    result = {}

    def connected(name):
        result["name"] = name
        GLib.timeout_add(800, lambda: dialog.response(Gtk.ResponseType.OK) and False)

    box = ConnectBox(app, connected)
    area = dialog.get_content_area()
    area.set_border_width(18)
    area.set_spacing(12)
    area.pack_start(widgets.label(_("Your browser opens to sign in. loudsync never sees your "
                                    "password: rclone keeps a token in its own config.")),
                    False, False, 0)
    area.pack_start(box, True, True, 0)
    dialog.show_all()
    dialog.run()
    box.cancel()
    dialog.destroy()
    return result.get("name")


# --- The first sync of a folder and a remote ---------------------------------


class FirstSync(Gtk.Box):
    """Preview, then the real thing. A --resync unions both sides and never
    deletes, which is why it is safe to offer; the preview says how much it
    will copy before anything moves."""

    def __init__(self, app, on_finished):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.on_finished = on_finished
        self.result = widgets.label()
        self.pack_start(self.result, False, False, 0)
        buttons = Gtk.Box(spacing=6)
        self.preview_button = widgets.button(_("Preview again"), self.preview)
        self.start_button = widgets.button(_("Start syncing"), self.start, suggested=True)
        self.preview_button.set_no_show_all(True)
        self.start_button.set_no_show_all(True)
        buttons.pack_start(self.start_button, False, False, 0)
        buttons.pack_start(self.preview_button, False, False, 0)
        self.pack_start(buttons, False, False, 0)
        self.process = widgets.ProcessView()
        self.pack_start(self.process, True, True, 0)
        self.done = False

    def preview(self):
        self.start_button.hide()
        self.preview_button.hide()
        self.result.set_text("")

        def done(code, _out, log_slice):
            self.preview_button.show()
            if code != 0:
                self.result.set_markup("<b>" + GLib.markup_escape_text(
                    _("The preview failed, so nothing was synced. The details below say why: "
                      "usually the folder in the cloud or the account.")) + "</b>")
                self.process.say("")
                self.process.details.set_expanded(True)
                return
            n = core.dry_run_copies(log_slice)
            if n == 0:
                text = _("Both sides already match: nothing needs copying.")
            else:
                text = ngettext(
                    "{n} file will be copied between this computer and the cloud.",
                    "{n} files will be copied between this computer and the cloud.", n).format(n=n)
            text += " " + _("Nothing gets deleted: the first sync only adds what each side is "
                            "missing. When a file differs, the one on this computer wins.")
            self.result.set_text(text)
            self.process.say(_("Preview finished."))
            self.start_button.show()

        self.process.start([self.app.paths.engine, "--resync", "--dry-run"],
                           _("Comparing both sides without changing anything…"), done,
                           follow_log=self.app.paths.log)

    def start(self):
        self.start_button.hide()
        self.preview_button.hide()

        def done(code, _out, _log):
            if code == 0:
                self.done = True
                self.result.set_text(_("The first sync finished. From now on loudsync keeps both "
                                       "sides in step, and shouts if that stops."))
                self.process.say("")
                self.on_finished(True)
            else:
                self.result.set_markup("<b>" + GLib.markup_escape_text(
                    _("The first sync failed. Nothing was deleted. The details below say why.")) + "</b>")
                self.process.say("")
                self.process.details.set_expanded(True)
                self.preview_button.show()
                self.on_finished(False)

        self.process.start([self.app.paths.engine, "--resync"],
                           _("Syncing for the first time. On a big folder this takes a while…"),
                           done, follow_log=self.app.paths.log)


def change_pair(app, parent, updates):
    """Settings asked for a different folder or remote. That is a new sync
    relationship: pause, point the config at it, preview, first sync, resume.
    Cancelled or failed, the old config comes back."""
    if not widgets.confirm(
            parent, _("Start syncing a different folder or cloud?"),
            _("Syncing pauses, loudsync compares the new pair and shows how much it would copy, "
              "and you confirm before anything moves. Files that exist on only one side get "
              "copied to the other. Nothing is deleted."), _("Continue")):
        return
    cfg = app.config
    old = {k: cfg.values.get(k, "") for k in updates}
    was = app.status.automation
    core.hold_automation()
    try:
        core.write_config(app.paths, updates)
    except (OSError, core.ConfigError) as e:
        _restore(was)
        widgets.message(parent, _("The settings were not saved"), str(e))
        return

    dialog = Gtk.Dialog(title=_("First sync"), transient_for=parent, modal=True, use_header_bar=True)
    dialog.set_default_size(620, 440)
    finished = {"ok": False}
    close = dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)

    def on_finished(ok):
        finished["ok"] = ok
        if ok:
            close.set_label(_("Done"))

    box = FirstSync(app, on_finished)
    area = dialog.get_content_area()
    area.set_border_width(18)
    area.pack_start(box, True, True, 0)
    dialog.show_all()
    GLib.idle_add(lambda: box.preview() and False)
    while True:
        dialog.run()
        if not box.process.running:
            break
        if widgets.confirm(dialog, _("Stop the first sync?"),
                           _("What was already copied stays. The old settings come back."),
                           _("Stop"), destructive=True):
            box.process.cancel()
            while box.process.running:
                Gtk.main_iteration()
            finished["ok"] = False
            break
    dialog.destroy()

    if finished["ok"]:
        if was.enabled or was.running:
            app.guard(lambda: core.set_automation(True), _("Could not turn syncing back on"))
    else:
        try:
            core.write_config(app.paths, old)
        except (OSError, core.ConfigError) as e:
            widgets.message(parent, _("The old settings could not be restored"), str(e))
        _restore(was)
    app.reload_config()


def _restore(was):
    if was.running:
        try:
            core.resume()
        except RuntimeError:
            pass


# --- A rename plan too large to apply unattended -----------------------------


def review_plan(app, parent):
    cfg = app.config
    rclone = core.find_rclone(cfg, app.paths.home)
    dialog = Gtk.Dialog(title=_("Review the plan"), transient_for=parent, modal=True,
                        use_header_bar=True)
    dialog.set_default_size(720, 520)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    apply = dialog.add_button(_("Apply on the remote"), Gtk.ResponseType.OK)
    apply.get_style_context().add_class("suggested-action")
    apply.set_sensitive(False)
    area = dialog.get_content_area()
    area.set_border_width(18)
    area.set_spacing(10)
    area.pack_start(widgets.label(
        _("These folders and files were renamed or moved here. Applying renames them on the "
          "remote the same way, server-side, and writes a script that reverses exactly what it "
          "did. Anything that doesn't match one to one is left alone.")), False, False, 0)
    plan = Gtk.TextView(editable=False, monospace=True, left_margin=8, top_margin=6)
    scroller = Gtk.ScrolledWindow()
    scroller.add(plan)
    area.pack_start(scroller, True, True, 0)
    process = widgets.ProcessView()
    area.pack_start(process, False, False, 0)
    dialog.show_all()
    process.details.hide()

    def planned(code, output, _log):
        widgets.set_text(plan, output)
        if code == 0:
            process.say(_("This is what would be applied. Nothing has been touched yet."))
            apply.set_sensitive(True)
        else:
            process.say(_("Could not build the plan. Check the network and the account."))

    process.start(["python3", app.paths.rename_helper, rclone, cfg.local_dir, cfg["REMOTE"],
                   app.paths.state("filters-generated.txt"), "--dry-run",
                   "--state-dir", app.paths.state_home],
                  _("Comparing both sides (this hashes files, it can take a while)…"), planned)
    answer = dialog.run()
    process.cancel()
    dialog.destroy()
    if answer != Gtk.ResponseType.OK:
        return

    run = Gtk.Dialog(title=_("Applying the plan"), transient_for=parent, modal=True,
                     use_header_bar=True)
    run.set_default_size(620, 400)
    close = run.add_button(_("Close"), Gtk.ResponseType.CLOSE)
    close.set_sensitive(False)
    view = widgets.ProcessView()
    run.get_content_area().set_border_width(18)
    run.get_content_area().pack_start(view, True, True, 0)
    run.show_all()

    def applied(code, _out, _log):
        close.set_sensitive(True)
        view.say(_("Done: the renames are on the remote and the sync reconciled.") if code == 0
                 else _("It did not finish. The details below say why; the log has the rest."))
        view.details.set_expanded(code != 0)
        app.refresh()

    view.start([app.paths.engine, "--propagate-rename", "--yes"],
               _("Renaming on the remote, then reconciling…"), applied, follow_log=app.paths.log)
    run.run()
    run.destroy()
