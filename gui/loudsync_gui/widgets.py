"""Small building blocks shared by the pages, the assistant and the dialogs.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os
import signal
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from . import _  # noqa: E402

CONTENT_WIDTH = 560


def label(text="", markup=None, dim=False, wrap=True, selectable=False, mono=False):
    w = Gtk.Label(xalign=0, wrap=wrap, selectable=selectable)
    w.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if markup is not None:
        w.set_markup(markup)
    else:
        w.set_text(text)
    if dim:
        w.get_style_context().add_class("dim-label")
    if mono:
        # Not every theme styles the .monospace class; an attribute always works.
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_family_new("monospace"))
        w.set_attributes(attrs)
    return w


def heading(text, size="xx-large"):
    return label(markup=f"<span size='{size}' weight='bold'>{GLib.markup_escape_text(text)}</span>")


def section(text):
    w = label(text.upper(), dim=True)
    w.get_style_context().add_class("loudsync-section")
    w.set_margin_top(18)
    return w


def page_box():
    """A page: scrollable, content left-aligned at a readable width."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(36)
    box.set_margin_end(36)
    box.set_halign(Gtk.Align.START)
    box.set_size_request(CONTENT_WIDTH, -1)
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroller.add(box)
    return scroller, box


def framed_list():
    frame = Gtk.Frame()
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.get_style_context().add_class("loudsync-rows")
    frame.add(rows)
    return frame, rows


def row(title, subtitle=None, widget=None, activatable=False):
    """A preference-style row: title, dim help under it, control on the right."""
    r = Gtk.ListBoxRow(activatable=activatable, selectable=False)
    box = Gtk.Box(spacing=12)
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
    text.pack_start(label(title), False, False, 0)
    r.subtitle = None
    if subtitle:
        r.subtitle = label(subtitle, dim=True)
        r.subtitle.set_max_width_chars(48)
        text.pack_start(r.subtitle, False, False, 0)
    box.pack_start(text, True, True, 0)
    if widget is not None:
        widget.set_valign(Gtk.Align.CENTER)
        box.pack_end(widget, False, False, 0)
    r.add(box)
    return r


def button(text, callback, suggested=False, destructive=False):
    b = Gtk.Button(label=text)
    if suggested:
        b.get_style_context().add_class("suggested-action")
    if destructive:
        b.get_style_context().add_class("destructive-action")
    b.connect("clicked", lambda _b: callback())
    return b


def reveal(widget):
    """Show a container that was kept out of its parent's show_all(), with
    everything inside it. show_all() alone does nothing while no_show_all
    is set."""
    widget.set_no_show_all(False)
    widget.show_all()


def open_path(path):
    """Opens a file or folder with the desktop's default application."""
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)


def trash(path):
    """Moves to the trash, or raises. Never falls back to deleting."""
    Gio.File.new_for_path(path).trash(None)


def technical_details():
    """The launcher's pattern: raw output exists, but out of the way."""
    expander = Gtk.Expander(label=_("Technical details"))
    view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        left_margin=8, right_margin=8, top_margin=6, bottom_margin=6)
    view.set_cursor_visible(False)
    scroller = Gtk.ScrolledWindow()
    scroller.set_min_content_height(140)
    scroller.add(view)
    expander.add(scroller)
    expander.view = view
    return expander


def set_text(view, text):
    view.get_buffer().set_text(text)


def append_text(view, text):
    buf = view.get_buffer()
    buf.insert(buf.get_end_iter(), text)
    view.scroll_to_mark(buf.get_insert(), 0, False, 0, 0)
    buf.place_cursor(buf.get_end_iter())


class ProcessView(Gtk.Box):
    """Runs one command without freezing the window: a spinner, a sentence,
    and the command's output under "Technical details".

    When `follow_log` is given, what gets appended to that file while the
    command runs is shown too, and handed to `on_done`. The engine prints
    almost nothing to stdout; its progress is in the log.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.status = label()
        top.pack_start(self.spinner, False, False, 0)
        top.pack_start(self.status, True, True, 0)
        self.pack_start(top, False, False, 0)
        self.details = technical_details()
        self.pack_start(self.details, True, True, 0)
        self.proc = None
        self.running = False

    def say(self, text):
        self.status.set_text(text)

    def start(self, argv, status_text, on_done, follow_log=None, env=None):
        if self.running:
            return
        self.running = True
        self.say(status_text)
        self.spinner.start()
        append_text(self.details.view, "$ " + " ".join(GLib.shell_quote(a) for a in argv) + "\n")
        offset = os.path.getsize(follow_log) if follow_log and os.path.exists(follow_log) else 0
        output = []
        log_slice = []
        stop = threading.Event()

        pos = {"at": offset}

        def read_new():
            try:
                with open(follow_log, "rb") as f:
                    if os.fstat(f.fileno()).st_size < pos["at"]:
                        pos["at"] = 0       # the engine rotated the log at start
                    f.seek(pos["at"])
                    chunk = f.read()
                    pos["at"] = f.tell()
            except FileNotFoundError:
                return
            if chunk:
                text = chunk.decode(errors="replace")
                log_slice.append(text)
                GLib.idle_add(append_text, self.details.view, text)

        def follow():
            while not stop.wait(0.5):
                read_new()

        def work():
            try:
                self.proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    text=True, errors="replace", env=env, start_new_session=True)
                for line in self.proc.stdout:
                    output.append(line)
                    GLib.idle_add(append_text, self.details.view, line)
                code = self.proc.wait()
            except OSError as e:
                GLib.idle_add(append_text, self.details.view, f"{e}\n")
                code = 127
            stop.set()
            if follow_log:
                follower.join()
                read_new()          # whatever landed after the last poll
            GLib.idle_add(self._finish, code, "".join(output), "".join(log_slice), on_done)

        follower = threading.Thread(target=follow, daemon=True)
        if follow_log:
            follower.start()
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        """Ends the command and everything it started (rclone opens a local
        web server for the browser sign-in; that must not be left behind)."""
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _finish(self, code, output, log_slice, on_done):
        self.running = False
        self.spinner.stop()
        self.proc = None
        on_done(code, output, log_slice)
        return False


def message(parent, title, text, kind=Gtk.MessageType.ERROR):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                               buttons=Gtk.ButtonsType.CLOSE, text=title)
    dialog.format_secondary_text(text)
    dialog.run()
    dialog.destroy()


def confirm(parent, title, text, accept, destructive=False):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True,
                               message_type=Gtk.MessageType.QUESTION, text=title)
    dialog.format_secondary_text(text)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    ok = dialog.add_button(accept, Gtk.ResponseType.OK)
    ok.get_style_context().add_class("destructive-action" if destructive else "suggested-action")
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    answer = dialog.run()
    dialog.destroy()
    return answer == Gtk.ResponseType.OK
