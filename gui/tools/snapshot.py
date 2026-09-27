#!/usr/bin/env python3
"""Render every page in every state to PNG, from fake state, off screen.

A design review tool: the art direction says every state is designed, not just
the happy one, and this is how to look at all of them without breaking a sync
to see its failure page. Nothing here touches systemd, the real config or the
real log: it all runs inside a throwaway home directory.

    python3 gui/tools/snapshot.py OUTPUT_DIR
"""

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "gui"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from loudsync_gui import core, describe  # noqa: E402
from loudsync_gui.style import Style  # noqa: E402

NOW = datetime.now()
ON = core.Automation(core.UnitState("loaded", "active", "enabled"),
                     core.UnitState("loaded", "active", "enabled"))
PAUSED = core.Automation(core.UnitState("loaded", "inactive", "enabled"),
                         core.UnitState("loaded", "inactive", "enabled"),
                         resume_at=(NOW + timedelta(hours=1)).timestamp())
FOREIGN = ("3 file(s) on the remote belong to another account, so this one cannot delete them "
           "(403 insufficientFilePermissions):\n  Shared/a.pdf\n  Shared/b.pdf\n  Shared/c.pdf\n"
           "The sync will fail on every run until they are out of the synced tree: remove them "
           "from the folder in your provider's web interface, or ask their owner to delete them.")


def sandbox():
    home = tempfile.mkdtemp(prefix="loudsync-snapshot-")
    docs = os.path.join(home, "Documents")
    os.makedirs(os.path.join(docs, "Finance"))
    os.makedirs(os.path.join(docs, "Projects", "lookout"))
    fake_rclone = os.path.join(home, "rclone")
    with open(fake_rclone, "w") as f:
        f.write("#!/bin/sh\necho 'gdrive:           drive'\n")
    os.chmod(fake_rclone, 0o755)
    paths = core.Paths.from_env({"HOME": home, "LOUDSYNC_ENGINE_DIR": os.path.join(ROOT, "bin")})
    os.makedirs(paths.config_home)
    os.makedirs(paths.state_home)
    with open(os.path.join(ROOT, "config", "loudsync.conf.example")) as f:
        core.create_config(paths, f.read())
    core.write_config(paths, {"RCLONE_BIN": fake_rclone})
    with open(os.path.join(ROOT, "config", "filters-base.txt")) as f:
        core.write_text(paths.filters_base_default, f.read())
    lines = []
    t = NOW - timedelta(hours=3)
    for i in range(12):
        t += timedelta(minutes=13)
        stamp = t.strftime("%Y-%m-%d %H:%M:%S")
        if i == 4:
            for j in range(3):
                lines.append(f"{stamp} | Still being written to (notes.md); postponing this run ({j + 1}/5).")
        lines.append(f"{stamp} | ===== START (22 repos excluded) =====")
        lines.append(f"{stamp} | ===== DONE =====")
        if i == 7:
            lines.append(f"{stamp} | ===== CONFLICT (1 file(s), 0 needing a decision) =====")
    core.write_text(paths.log, "\n".join(lines) + "\n")
    core.write_text(paths.state("repos-previous.txt"),
                    "\n".join(f"Projects/repo-{i:02d}" for i in range(22)) + "\n")
    return paths, docs


def fake_conflicts(docs):
    now = time.time()
    out = []
    for rel, side, t_orig, t_copy, s1, s2 in (
            ("Finance/budget-2026.ods", "remote", now - 1200, now - 9000, 48 * 1024, 47 * 1024),
            ("Projects/lookout/notes.md", "local", now - 86000, now - 86040, 3100, 3000)):
        orig = os.path.join(docs, rel)
        out.append(core.Conflict(orig + ".conflict-" + side, orig, rel, side, t_copy, s2, t_orig, s1))
    return out


class FakeApp:
    def __init__(self, paths):
        self.paths = paths
        self.config = core.read_config(paths)
        self.config_error = ""
        self.style = Style()
        self.tray = None
        self.conflicts = []
        self.status = None
        self.headline = None

    def set(self, conflicts=(), **kw):
        s = core.read_status(self.paths, self.config, automation=ON)
        s.ever_synced = True
        for k, v in kw.items():
            setattr(s, k, v)
        self.status = s
        self.conflicts = list(conflicts)
        self.headline = describe.headline_for(s, len(self.conflicts))

    def __getattr__(self, name):
        return lambda *a, **k: None     # every action is a no-op here


class FakeWindow:
    def show_page(self, _name):
        pass


def render(widget, path, width=640, height=620):
    off = Gtk.OffscreenWindow()
    off.set_size_request(width, height)
    off.add(widget)
    off.show_all()
    return off


def pump():
    for _i in range(5):
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.05)


def save(off, path):
    pump()
    off.get_pixbuf().savev(path, "png", [], [])
    print(path)


def main(out):
    os.makedirs(out, exist_ok=True)
    paths, docs = sandbox()
    app = FakeApp(paths)
    from loudsync_gui.conflicts import ConflictsPage
    from loudsync_gui.settings import FiltersPage, SettingsPage
    from loudsync_gui.window import ActivityPage, StatusPage

    states = {
        "status-ok": dict(),
        "status-syncing": dict(running=True),
        "status-paused": dict(automation=PAUSED),
        "status-failing": dict(failures=4, fail_cause=FOREIGN),
        "status-failing-unknown": dict(failures=4),
        "status-decision": dict(needs_decision="these repos left the list (renamed?): Projects/old-name"),
        "status-broken": dict(engine_error="rclone remote 'gdrive' is not configured. Run: rclone config"),
        "status-conflicts": dict(conflicts=fake_conflicts(docs)),
        "status-setup": dict(ever_synced=False),
    }
    for name, kw in states.items():
        app.set(**kw)
        page = StatusPage(app, FakeWindow())
        off = render(page.widget, None)
        page.update()
        save(off, os.path.join(out, name + ".png"))

    app.set(conflicts=fake_conflicts(docs))
    for name, cls in (("conflicts", ConflictsPage), ("activity", ActivityPage)):
        page = cls(app)
        off = render(page.widget, None)
        page.update()
        save(off, os.path.join(out, name + ".png"))
    app.set(conflicts=())
    page = ConflictsPage(app)
    off = render(page.widget, None)
    page.update()
    save(off, os.path.join(out, "conflicts-empty.png"))

    for name, cls in (("settings", SettingsPage), ("filters", FiltersPage)):
        page = cls(app, FakeWindow())
        off = render(page.widget, None, height=900)
        page.update()
        save(off, os.path.join(out, name + ".png"))

    from loudsync_gui.wizard import Wizard
    wizard = Wizard(app)
    body = wizard.body
    wizard.remove(body)
    off = render(body, None, width=720, height=520)
    for i in range(3):
        wizard.index = i
        wizard._show()
        save(off, os.path.join(out, f"wizard-{i + 1}.png"))
        if i == 0:
            wizard.folder.set_filename(docs)
            wizard._folder_changed()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "snapshots")
