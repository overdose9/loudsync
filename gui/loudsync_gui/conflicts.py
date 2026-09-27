"""The Conflicts page: each file changed on both sides, both versions kept,
and a human decides which one counts.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import _, core, describe, ngettext, widgets  # noqa: E402


class ConflictsPage:
    def __init__(self, app):
        self.app = app
        self.widget, box = widgets.page_box()
        self.title = widgets.label()
        self.intro = widgets.label(dim=True)
        box.pack_start(self.title, False, False, 0)
        box.pack_start(self.intro, False, False, 0)
        self.notice = widgets.label()
        self.notice.set_no_show_all(True)
        box.pack_start(self.notice, False, False, 0)
        self.frame, self.rows = widgets.framed_list()
        box.pack_start(self.frame, False, False, 6)
        self.shown = None

    def say(self, text):
        self.notice.set_text(text)
        self.notice.set_visible(bool(text))

    def update(self):
        conflicts = self.app.conflicts
        key = tuple((c.copy_path, c.copy_mtime, c.original_mtime) for c in conflicts)
        if key == self.shown:
            return
        self.shown = key
        n = len(conflicts)
        if n:
            title = ngettext("{n} file needs a decision", "{n} files need a decision", n).format(n=n)
            intro = _("Both versions were kept side by side, so nothing is lost. Compare them, "
                      "then keep one. The other goes to the trash, and the sync carries your "
                      "choice to the other side.")
        else:
            title = _("Nothing to decide")
            intro = _("When a file changes on both sides, both versions are kept and listed here.")
        self.title.set_markup(f"<span size='x-large' weight='bold'>{GLib.markup_escape_text(title)}</span>")
        self.intro.set_text(intro)
        for child in self.rows.get_children():
            self.rows.remove(child)
        race = self.app.config.int("CONFLICT_RACE_SECONDS") if self.app.config else 120
        for c in conflicts:
            self.rows.add(self._row(c, race))
        self.frame.set_visible(n > 0)
        self.rows.show_all()

    def _row(self, c, race):
        r = Gtk.ListBoxRow(selectable=False, activatable=False)
        line = Gtk.Box(spacing=10)
        glyph = Gtk.Image(valign=Gtk.Align.START)
        glyph.set_from_surface(self.app.style.state_surface(
            describe.Headline("", "warning", "warning", False, "", ""), 18, glyph))
        line.pack_start(glyph, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        folder = os.path.dirname(c.rel)
        name = GLib.markup_escape_text(os.path.basename(c.rel))
        where = GLib.markup_escape_text(folder + "/") if folder else ""
        col.pack_start(widgets.label(markup=f"<b>{name}</b>  <small>{where}</small>"), False, False, 0)
        current, other, note = describe.conflict_lines(c, race)
        col.pack_start(widgets.label(current, dim=True), False, False, 0)
        col.pack_start(widgets.label(other, dim=True), False, False, 0)
        if note:
            col.pack_start(widgets.label(markup=f"<i>{GLib.markup_escape_text(note)}</i>", dim=True),
                           False, False, 0)
        buttons = Gtk.Box(spacing=6)
        buttons.set_margin_top(6)
        opener = widgets.button(_("Open both"), lambda: self._open(c))
        keep = widgets.button(_("Keep current"), lambda: self._resolve(c, "original", r))
        keep_other = widgets.button(_("Keep other copy"), lambda: self._resolve(c, "copy", r))
        keep.set_sensitive(c.original_exists)
        for b in (opener, keep, keep_other):
            buttons.pack_start(b, False, False, 0)
        col.pack_start(buttons, False, False, 0)
        line.pack_start(col, True, True, 0)
        r.add(line)
        return r

    def _open(self, c):
        for path in (c.original_path, c.copy_path):
            if os.path.exists(path):
                try:
                    widgets.open_path(path)
                except GLib.Error as e:
                    self.say(_("Could not open {name}: {error}").format(
                        name=os.path.basename(path), error=e.message))

    def _resolve(self, c, keep, r):
        r.set_sensitive(False)
        try:
            core.resolve_conflict(c, keep, widgets.trash)
        except FileNotFoundError:
            self.say(_("{name} was already settled elsewhere.").format(name=os.path.basename(c.rel)))
        except GLib.Error as e:
            # No trash on this filesystem (or no permission): nothing is
            # deleted instead. The human can move it by hand.
            r.set_sensitive(True)
            self.say(_("Could not move a version of {name} to the trash, so nothing was touched: "
                       "{error}").format(name=os.path.basename(c.rel), error=e.message))
            return
        except OSError as e:
            r.set_sensitive(True)
            self.say(_("Could not settle {name}: {error}").format(
                name=os.path.basename(c.rel), error=e.strerror or str(e)))
            return
        else:
            kept = _("current version") if keep == "original" else _("other copy")
            self.say(_("Kept the {which} of {name}. The other one is in the trash.").format(
                which=kept, name=os.path.basename(c.rel)))
        self.app.scan_conflicts()
