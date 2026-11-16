"""The main window: a sidebar of five pages, the answer first on each.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import shutil
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import _, core, describe, ngettext, widgets  # noqa: E402
from .conflicts import ConflictsPage  # noqa: E402
from .settings import FiltersPage, SettingsPage  # noqa: E402


class StatusPage:
    """Direction A: the state and its time, the actions, then the facts that
    back the state up."""

    def __init__(self, app, window):
        self.app = app
        self.window = window
        self.widget, box = widgets.page_box()

        self.image = Gtk.Image(halign=Gtk.Align.START)
        self.title = widgets.label()
        self.detail = widgets.label(dim=True, selectable=True)
        box.pack_start(self.image, False, False, 0)
        box.pack_start(self.title, False, False, 0)
        box.pack_start(self.detail, False, False, 0)

        # What went wrong and what to do about it. Only in alert states.
        self.alert = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.alert.get_style_context().add_class("loudsync-alert")
        self.alert_title = widgets.label()
        self.alert_body = widgets.label(selectable=True)
        self.alert_buttons = Gtk.Box(spacing=6)
        self.alert_buttons.set_margin_top(6)
        self.alert_details = widgets.technical_details()
        for w in (self.alert_title, self.alert_body, self.alert_buttons, self.alert_details):
            self.alert.pack_start(w, False, False, 0)
        # Shown or hidden by update(); show_all() is a no-op on a widget
        # marked no_show_all, so these two are left unmarked.
        box.pack_start(self.alert, False, False, 6)

        self.buttons = Gtk.Box(spacing=6)
        self.sync_button = widgets.button(_("Sync now"), app.sync_now, suggested=True)
        self.pause_button = Gtk.MenuButton()
        inner = Gtk.Box(spacing=4)
        inner.pack_start(Gtk.Label(label=_("Pause")), False, False, 0)
        inner.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON),
                         False, False, 0)
        inner.show_all()
        self.pause_button.add(inner)
        menu = Gtk.Menu()
        for text, seconds in ((_("For 1 hour"), 3600), (_("For 8 hours"), 8 * 3600),
                              (_("Until I resume"), None)):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _i, s=seconds: app.pause(s))
            menu.append(item)
        menu.show_all()
        self.pause_button.set_popup(menu)
        self.resume_button = widgets.button(_("Resume"), app.resume, suggested=True)
        self.turn_on_button = widgets.button(_("Turn on"), app.turn_on, suggested=True)
        self.setup_button = widgets.button(_("Set up…"), app.show_wizard, suggested=True)
        self.conflicts_button = widgets.button(_("Review conflicts"), lambda: window.show_page("conflicts"))
        self.folder_button = widgets.button(_("Open folder"), app.open_folder)
        for b in (self.setup_button, self.sync_button, self.resume_button, self.turn_on_button,
                  self.pause_button, self.conflicts_button, self.folder_button):
            b.set_no_show_all(True)
            self.buttons.pack_start(b, False, False, 0)
        box.pack_start(self.buttons, False, False, 6)

        self.facts_frame, facts = widgets.framed_list()
        self.folder_value = widgets.label(mono=True, wrap=False)
        self.remote_value = widgets.label(mono=True, wrap=False)
        self.instant_value = widgets.label(wrap=False)
        self.check_value = widgets.label(wrap=False)
        self.repos_value = widgets.label(wrap=False)
        self.folder_row = widgets.row(_("Folder"), widget=self.folder_value, activatable=True)
        self.instant_row = widgets.row(_("Instant uploads"), " ", widget=self.instant_value)
        self.repos_row = widgets.row(_("Git repositories excluded"), widget=self.repos_value,
                                     activatable=True)
        for r in (self.folder_row, widgets.row(_("Remote"), widget=self.remote_value),
                  self.instant_row, widgets.row(_("Checks the remote"), widget=self.check_value),
                  self.repos_row):
            facts.add(r)
        facts.connect("row-activated", self._on_fact)
        box.pack_start(self.facts_frame, False, False, 6)

    def _on_fact(self, _list, r):
        if r is self.folder_row:
            self.app.open_folder()
        elif r is self.repos_row:
            self.window.show_page("filters")

    def update(self):
        app, s, h = self.app, self.app.status, self.app.headline
        self.image.set_from_surface(app.style.state_surface(h, 64, self.image))
        self.title.set_markup(f"<span size='xx-large' weight='bold'>{GLib.markup_escape_text(h.title)}</span>")
        self.detail.set_text(h.detail)

        a = s.automation
        setup = h.state == core.SETUP
        paused = a.paused
        off = a.installed and not a.enabled and not a.running
        shown = {
            self.setup_button: setup,
            # A normal run would only stop again at a pending decision.
            self.sync_button: not setup and h.state not in (core.BROKEN, core.DECISION),
            self.resume_button: not setup and paused,
            self.turn_on_button: not setup and off,
            self.pause_button: not setup and a.running,
            self.conflicts_button: not setup and len(app.conflicts) > 0,
            self.folder_button: s.configured,
        }
        for button, visible in shown.items():
            button.set_visible(visible)
        # One suggested action at a time: when paused or off, it's turning back on.
        ctx = self.sync_button.get_style_context()
        if paused or off:
            ctx.remove_class("suggested-action")
        else:
            ctx.add_class("suggested-action")
        self.sync_button.set_sensitive(not s.running)
        self.sync_button.set_tooltip_text(_("A sync is running right now.") if s.running else None)

        self._update_alert(h, s)
        self._update_facts(s, setup)

    def _update_alert(self, h, s):
        key = (h.state, s.fail_cause, s.needs_decision, s.failures)
        if key == getattr(self, "_alert_key", None):
            return
        self._alert_key = key
        for child in self.alert_buttons.get_children():
            self.alert_buttons.remove(child)
        ctx = self.alert.get_style_context()
        ctx.remove_class("warning")
        details = ""
        buttons = [(_("Open log"), self.app.open_log)]

        if h.state == core.BROKEN:
            title = _("How to fix it")
            body = _("Check the folder and the cloud account in Settings. If they look right, "
                     "the log says more.")
            buttons.insert(0, (_("Open settings"), lambda: self.window.show_page("settings")))
        elif h.state == core.DECISION:
            title = _("A move needs your approval")
            body = _("Something that changes what gets synced moved or was edited, and the plan "
                     "to follow it on the remote is too large to apply on its own. Syncing stopped "
                     "until you look at it. Nothing was deleted.")
            details = s.needs_decision
            buttons.insert(0, (_("Review the plan…"), self.app.review_plan))
        elif h.state == core.FAILING and s.fail_cause:
            lines = s.fail_cause.splitlines()
            details = s.fail_cause
            if "belong to another account" in lines[0]:
                # The engine's wording carries the provider's error code for
                # the log. Here it is said plainly; the code stays in details.
                n = sum(1 for line in lines if line.startswith("  "))
                title = _("Files you don't own are blocking the sync")
                body = ngettext(
                    "{n} file on the remote belongs to another account, so this one can't delete "
                    "it. Every run will fail until it leaves the synced folder: remove it in your "
                    "provider's web interface, or ask its owner to.",
                    "{n} files on the remote belong to another account, so this one can't delete "
                    "them. Every run will fail until they leave the synced folder: remove them in "
                    "your provider's web interface, or ask their owner to.", n).format(n=n)
            else:
                title = _("Why it is failing")
                body = lines[0] + ("\n" + lines[-1] if len(lines) > 1 else "")
        elif h.state == core.FAILING:
            title = _("The log has the details")
            body = _("The last runs ended with an error while the network was up, so this is "
                     "not just being offline.")
            details = "\n".join(core.recent_errors(self.app.paths))
        else:
            self.alert.hide()
            return

        self.alert_title.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        self.alert_body.set_text(body)
        widgets.set_text(self.alert_details.view, details)
        self.alert_details.set_visible(bool(details))
        for text, callback in buttons:
            self.alert_buttons.pack_start(widgets.button(text, callback), False, False, 0)
        self.alert.show_all()
        self.alert_details.set_visible(bool(details))

    def _update_facts(self, s, setup):
        if setup or self.app.config is None:
            self.facts_frame.hide()
            return
        cfg, a = self.app.config, s.automation
        self.folder_value.set_text(core.contract_home(cfg.local_dir, self.app.paths.home))
        self.remote_value.set_text(cfg["REMOTE"])
        if a.instant_uploads:
            self.instant_value.set_text(_("On"))
            self.instant_row.subtitle.hide()
        else:
            self.instant_value.set_text(_("Off"))
            if a.running and shutil.which("inotifywait") is None:
                hint = _("Local changes wait for the minute check. Install inotify-tools to "
                         "upload within seconds.")
            elif a.running:
                hint = _("The watcher is not running. Local changes wait for the minute check.")
            else:
                hint = _("Nothing syncs while paused.")
            self.instant_row.subtitle.set_text(hint)
            self.instant_row.subtitle.show()
        self.check_value.set_text(_("Every minute") if a.running else
                                  (_("Paused") if a.paused else _("Off")))
        self.repos_value.set_text(f"{len(s.repos)}  ›")
        self.facts_frame.show_all()
        if a.instant_uploads:
            self.instant_row.subtitle.hide()


class ActivityPage:
    def __init__(self, app):
        self.app = app
        self.widget, box = widgets.page_box()
        box.pack_start(widgets.heading(_("Activity"), "x-large"), False, False, 0)
        box.pack_start(widgets.label(_("What each run did, newest first. The full log has every "
                                       "file."), dim=True), False, False, 0)
        self.empty = widgets.label(_("No runs recorded yet."), dim=True)
        self.empty.set_no_show_all(True)
        box.pack_start(self.empty, False, False, 6)
        self.frame, self.rows = widgets.framed_list()
        box.pack_start(self.frame, False, False, 6)
        bottom = Gtk.Box()
        bottom.pack_start(widgets.button(_("Open full log"), app.open_log), False, False, 0)
        box.pack_start(bottom, False, False, 6)
        self.shown = None

    def update(self):
        events = self.app.status.events
        key = (len(events), events[-1].when if events else None)
        if key == self.shown:
            return
        self.shown = key
        for child in self.rows.get_children():
            self.rows.remove(child)
        items = describe.activity(events)
        self.empty.set_visible(not items)
        self.frame.set_visible(bool(items))
        now = datetime.now()
        for item in items:
            line = Gtk.Box(spacing=10)
            dot = Gtk.Label(label="●")
            dot.get_style_context().add_class(f"loudsync-dot-{item.tone}")
            line.pack_start(dot, False, False, 0)
            line.pack_start(widgets.label(item.text), True, True, 0)
            when = item.when.strftime("%H:%M") if item.when.date() == now.date() \
                else item.when.strftime("%d %b %H:%M")
            line.pack_end(widgets.label(when, dim=True, wrap=False), False, False, 0)
            r = Gtk.ListBoxRow(selectable=False, activatable=False)
            r.add(line)
            self.rows.add(r)
        self.rows.show_all()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="loudsync")
        self.app = app
        self.set_default_size(860, 600)
        self.set_icon_name("loudsync")

        header = Gtk.HeaderBar(title="loudsync", show_close_button=True)
        self.spinner = Gtk.Spinner()
        about = Gtk.Button.new_from_icon_name("help-about-symbolic", Gtk.IconSize.BUTTON)
        about.set_tooltip_text(_("About loudsync"))
        about.set_relief(Gtk.ReliefStyle.NONE)
        about.connect("clicked", lambda _b: app.show_about())
        header.pack_end(about)
        header.pack_end(self.spinner)
        self.set_titlebar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=200)
        self.status_page = StatusPage(app, self)
        self.conflicts_page = ConflictsPage(app)
        self.activity_page = ActivityPage(app)
        self.settings_page = SettingsPage(app, self)
        self.filters_page = FiltersPage(app, self)
        self.pages = [
            ("status", _("Status"), self.status_page),
            ("conflicts", _("Conflicts"), self.conflicts_page),
            ("activity", _("Activity"), self.activity_page),
            ("settings", _("Settings"), self.settings_page),
            ("filters", _("Filters"), self.filters_page),
        ]

        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE)
        self.sidebar.get_style_context().add_class("sidebar")
        self.sidebar.get_style_context().add_class("loudsync-sidebar")
        self.sidebar.set_size_request(180, -1)
        self.badge = Gtk.Label()
        self.badge.get_style_context().add_class("loudsync-badge")
        self.badge.set_no_show_all(True)
        for name, title, page in self.pages:
            self.stack.add_named(page.widget, name)
            r = Gtk.ListBoxRow()
            r.name = name
            line = Gtk.Box(spacing=6)
            line.pack_start(widgets.label(title, wrap=False), True, True, 0)
            if name == "conflicts":
                line.pack_end(self.badge, False, False, 0)
            r.add(line)
            self.sidebar.add(r)
        self.sidebar.connect("row-selected", self._on_select)

        body = Gtk.Box()
        side = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        side.add(self.sidebar)
        body.pack_start(side, False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        body.pack_start(self.stack, True, True, 0)
        self.add(body)
        self.connect("delete-event", self._on_close)
        self.show_all()
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))

    def _on_select(self, _list, r):
        if r is not None:
            self.stack.set_visible_child_name(r.name)
            page = dict((n, p) for n, _t, p in self.pages)[r.name]
            if hasattr(page, "on_shown"):
                page.on_shown()

    def show_page(self, name):
        for i, (n, _t, _p) in enumerate(self.pages):
            if n == name:
                self.sidebar.select_row(self.sidebar.get_row_at_index(i))

    def _on_close(self, *_args):
        # With a tray icon, closing the window hides it: the icon is the app.
        if self.app.tray is not None and self.app.tray.available:
            self.hide()
            return True
        return False

    def update(self):
        s = self.app.status
        if s.running:
            self.spinner.start()
        else:
            self.spinner.stop()
        n = len(self.app.conflicts)
        self.badge.set_text(str(n))
        self.badge.set_visible(n > 0)
        self.badge.set_tooltip_text(ngettext("{n} conflict", "{n} conflicts", n).format(n=n))
        for _n, _t, page in self.pages:
            page.update()
