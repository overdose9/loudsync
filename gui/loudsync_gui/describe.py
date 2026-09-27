"""What each state says, in words. No GTK, so every sentence can be tested.

The rule from the art direction: a claim needs evidence. "Up to date" comes
from a run that finished, with its time; when something is not known, the
sentence says so instead of defaulting to good news.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

from dataclasses import dataclass
from datetime import datetime

from . import _, core, ngettext

# Which glyph, which colour role, and whether the cloud shouts.
_LOOK = {
    core.SETUP: ("setup", "syncing", False),
    core.BROKEN: ("error", "error", True),
    core.DECISION: ("error", "error", True),
    core.FAILING: ("error", "error", True),
    core.SYNCING: ("sync", "syncing", False),
    core.PAUSED: ("pause", "paused", False),
    core.RETRYING: ("warning", "warning", False),
    core.CONFLICTS: ("warning", "warning", True),
    core.OFF: ("pause", "paused", False),
    core.OK: ("ok", "ok", False),
}


@dataclass
class Headline:
    state: str
    glyph: str
    tone: str
    loud: bool
    title: str
    detail: str

    @property
    def tooltip(self):
        return f"{self.title} · {self.detail}" if self.detail else self.title


def last_synced(status, now=None):
    if status.last_success is None:
        return _("No finished sync is recorded in the log yet.")
    return _("Last synced {when}").format(when=core.ago(status.last_success, now))


def clock(epoch, now=None):
    """15:40 today, or 'Tue 15:40' further out."""
    when = datetime.fromtimestamp(epoch)
    now = now or datetime.now()
    if when.date() == now.date():
        return f"{when:%H:%M}"
    return f"{when:%a %H:%M}"


def headline_for(status, conflict_count=0, now=None):
    state = core.headline(status, conflict_count)
    glyph, tone, loud = _LOOK[state]

    if state == core.SETUP:
        title = _("Let's set up loudsync")
        detail = _("Nothing has been synced yet.")
    elif state == core.BROKEN:
        title = _("loudsync can't start")
        detail = status.config_error or status.engine_error
    elif state == core.DECISION:
        title = _("Sync is stopped: it needs your decision")
        detail = _("Nothing was deleted. The plan is waiting for you.")
    elif state == core.FAILING:
        title = _("Sync is failing")
        detail = ngettext("{n} failed attempt in a row", "{n} failed attempts in a row",
                          status.failures).format(n=status.failures)
        if status.last_success:
            detail += " · " + _("last good sync {when}").format(when=core.ago(status.last_success, now))
    elif state == core.SYNCING:
        title = _("Syncing…")
        detail = last_synced(status, now)
    elif state == core.PAUSED:
        resume_at = status.automation.resume_at
        if resume_at:
            title = _("Paused until {time}").format(time=clock(resume_at, now))
            detail = _("It resumes by itself at that time.")
        else:
            title = _("Paused")
            detail = _("It resumes when you say so, or at your next login at the latest.")
    elif state == core.RETRYING:
        title = _("The last attempt failed")
        detail = ngettext(
            "Retrying every minute. You'll get an alert after {n} failure in a row.",
            "Retrying every minute. You'll get an alert after {n} failures in a row.",
            status.fail_threshold).format(n=status.fail_threshold)
    elif state == core.CONFLICTS:
        title = ngettext("{n} file needs a decision", "{n} files need a decision",
                         conflict_count).format(n=conflict_count)
        detail = last_synced(status, now)
    elif state == core.OFF:
        title = _("Automatic sync is off")
        detail = _("Nothing syncs until you turn it on.")
    else:
        title = _("Up to date")
        detail = last_synced(status, now)
    return Headline(state, glyph, tone, loud, title, detail)


# --- Activity ----------------------------------------------------------------


@dataclass
class ActivityItem:
    when: datetime
    tone: str
    text: str


# Engine lines worth a row of their own. The rest (per-file conflict details,
# rename plans, rclone's chatter) stays in the full log.
_NOTABLE_INFO = (
    "Recovered after",
    "No network",
    "Reconciled automatically",
    "The folder has been busy",
    "Newly excluded repos",
    "Log rotated",
)


def activity(events, limit=200):
    """Newest first. Consecutive postponements fold into one row: a folder
    under constant writes produces dozens of them, and a list where one fact
    fills the screen hides the facts around it."""
    items = []
    postponed = []

    def flush():
        if not postponed:
            return
        n = len(postponed)
        text = ngettext("Postponed: a file was still being written",
                        "Postponed {n} times: files were still being written", n).format(n=n)
        items.append(ActivityItem(postponed[-1].when, "warning", text))
        postponed.clear()

    for e in events:
        if e.kind == "postponed":
            postponed.append(e)
            continue
        flush()
        if e.kind == "done":
            items.append(ActivityItem(e.when, "ok", _("Synced")))
        elif e.kind == "failed":
            items.append(ActivityItem(e.when, "error", _("Sync failed")))
        elif e.kind == "conflict":
            summary = e.text.strip("= ").replace("CONFLICT", "").strip(" ()")
            items.append(ActivityItem(e.when, "warning", _("Conflict: {summary}").format(summary=summary)))
        elif e.kind == "attention":
            items.append(ActivityItem(e.when, "error", e.text.split(": ", 1)[-1]))
        elif e.kind == "error":
            items.append(ActivityItem(e.when, "error", e.text[len("ERROR: "):]))
        elif e.kind == "notified":
            items.append(ActivityItem(e.when, "syncing", e.text[len("Notified: "):]))
        elif e.kind == "info" and e.text.startswith(_NOTABLE_INFO):
            items.append(ActivityItem(e.when, "syncing", e.text))
    flush()
    items.reverse()
    return items[:limit]


# --- Conflicts ---------------------------------------------------------------


def conflict_lines(c, race_seconds, now=None):
    """Two lines describing the two versions, and an optional note.

    The file under the original name is the one that won. The copy carries
    the suffix of the side it came from, so the winner came from the other.
    """
    theirs = _("from the remote") if c.copy_side == "remote" else _("from this computer")
    ours = _("from this computer") if c.copy_side == "remote" else _("from the remote")
    copy_when = core.ago(datetime.fromtimestamp(c.copy_mtime), now)
    if c.original_exists:
        orig_when = core.ago(datetime.fromtimestamp(c.original_mtime), now)
        current = _("Current: {origin} · edited {when} · {size}").format(
            origin=ours, when=orig_when, size=core.human_size(c.original_size))
    else:
        current = _("Current: the file under the original name is gone")
    other = _("Other copy: {origin} · edited {when} · {size}").format(
        origin=theirs, when=copy_when, size=core.human_size(c.copy_size))
    note = ""
    gap = abs(c.original_mtime - c.copy_mtime)
    if c.original_exists and gap < race_seconds:
        apart = (ngettext("{n} second", "{n} seconds", int(gap)).format(n=int(gap)) if gap < 60
                 else ngettext("{n} minute", "{n} minutes", int(gap // 60)).format(n=int(gap // 60)))
        note = _("Only {gap} apart: probably one file saved while a sync was running.").format(gap=apart)
    return current, other, note
