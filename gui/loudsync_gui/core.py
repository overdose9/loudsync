"""What the window knows about loudsync, with no GTK in it.

The window is a view over the same files and units the command line uses. It
keeps no state of its own that the engine does not also read, so closing it,
or never installing it, changes nothing about how syncing behaves.

Everything here is plain Python so it can be tested without a display.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import _, ngettext

# --- Where things live -------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    """The same locations bin/loudsync computes, from the same variables."""

    home: str
    config_home: str
    state_home: str
    config_file: str
    engine_dir: str

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        home = env.get("HOME") or os.path.expanduser("~")
        config_base = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        state_base = env.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
        config_home = os.path.join(config_base, "loudsync")
        engine_dir = env.get("LOUDSYNC_ENGINE_DIR") or _find_engine_dir(home)
        return cls(
            home=home,
            config_home=config_home,
            state_home=os.path.join(state_base, "loudsync"),
            config_file=env.get("LOUDSYNC_CONFIG") or os.path.join(config_home, "loudsync.conf"),
            engine_dir=engine_dir,
        )

    def state(self, name):
        return os.path.join(self.state_home, name)

    @property
    def engine(self):
        return os.path.join(self.engine_dir, "loudsync")

    @property
    def rename_helper(self):
        return os.path.join(self.engine_dir, "loudsync-rename")

    @property
    def log(self):
        return self.state("loudsync.log")

    @property
    def filters_base_default(self):
        return os.path.join(self.config_home, "filters-base.txt")


def _find_engine_dir(home):
    installed = os.path.join(home, ".local", "bin")
    if os.access(os.path.join(installed, "loudsync"), os.X_OK):
        return installed
    found = shutil.which("loudsync")
    return os.path.dirname(found) if found else installed


# --- Configuration -----------------------------------------------------------
#
# The config file is sourced by bash, so bash is what reads it here too.
# Parsing it in Python would work for the shipped example and then disagree
# with the engine the first time somebody writes a line bash understands and a
# regular expression doesn't.

# Defaults, exactly as bin/loudsync sets them before sourcing the file.
DEFAULTS = {
    "LOCAL_DIR": "",
    "REMOTE": "",
    "RCLONE_BIN": "",
    "FILTERS_BASE": "",          # empty means <config_home>/filters-base.txt
    "MAX_DELETE_PERCENT": "50",
    "CONFLICT_RESOLVE": "newer",
    "KEEP_LOCAL_VERSIONS": "1",
    "MAX_REPO_DEPTH": "8",
    "FAIL_THRESHOLD": "3",
    "REMIND_EVERY": "60",
    "QUIET_SECONDS": "15",
    "MAX_QUIET_SKIPS": "5",
    "CONFLICT_RACE_SECONDS": "120",
    "TRANSFERS": "8",
    "CHECKERS": "16",
    "NOTIFY": "1",
    "LOG_MAX_MB": "50",
    "LOG_KEEP": "3",
    "WATCH_DEBOUNCE": "5",
}

TEXT_KEYS = {"LOCAL_DIR", "REMOTE", "RCLONE_BIN", "FILTERS_BASE", "CONFLICT_RESOLVE"}
INT_KEYS = set(DEFAULTS) - TEXT_KEYS

CONFLICT_POLICIES = ("newer", "older", "larger", "smaller", "path1", "path2", "none")

_READ_SCRIPT = r'''
set -euo pipefail
CONFIG_HOME="$2"
STATE_HOME="$3"
. "$1"
shift 3
for k in "$@"; do
    if [ -n "${!k+x}" ]; then printf '%s\0%s\0' "$k" "${!k}"; fi
done
'''


class ConfigError(Exception):
    pass


@dataclass
class Config:
    values: dict
    home: str

    def __getitem__(self, key):
        return self.values[key]

    def int(self, key):
        try:
            return int(self.values[key])
        except (TypeError, ValueError):
            return int(DEFAULTS[key])

    @property
    def local_dir(self):
        """LOCAL_DIR as the engine sees it: a leading ~ becomes $HOME."""
        return expand_home(self.values["LOCAL_DIR"], self.home)

    @property
    def remote_name(self):
        return self.values["REMOTE"].split(":", 1)[0]

    @property
    def remote_path(self):
        parts = self.values["REMOTE"].split(":", 1)
        return parts[1] if len(parts) == 2 else ""


def expand_home(value, home):
    # Mirrors ${LOCAL_DIR/#\~/${HOME}} in the engine, quirks included.
    return home + value[1:] if value.startswith("~") else value


def contract_home(path, home):
    """The inverse, for writing a folder the way people read it."""
    if path == home:
        return "~"
    if path.startswith(home.rstrip("/") + "/"):
        return "~" + path[len(home.rstrip("/")):]
    return path


def read_config(paths):
    if not os.path.isfile(paths.config_file):
        raise FileNotFoundError(paths.config_file)
    env = {k: v for k, v in os.environ.items() if k not in DEFAULTS}
    env["HOME"] = paths.home
    res = subprocess.run(
        ["bash", "-c", _READ_SCRIPT, "loudsync-gui", paths.config_file,
         paths.config_home, paths.state_home, *DEFAULTS],
        capture_output=True, env=env, timeout=10,
    )
    if res.returncode != 0:
        raise ConfigError(res.stderr.decode(errors="replace").strip()
                          or f"bash exited with {res.returncode}")
    values = dict(DEFAULTS)
    fields = res.stdout.decode(errors="surrogateescape").split("\0")
    for k, v in zip(fields[0::2], fields[1::2]):
        values[k] = v
    if not values["FILTERS_BASE"]:
        values["FILTERS_BASE"] = paths.filters_base_default
    return Config(values=values, home=paths.home)


def validate(updates, home):
    """Problems with a set of new values, as sentences. Empty means fine."""
    problems = []
    for key, value in updates.items():
        if key not in DEFAULTS:
            problems.append(_("Unknown setting: {key}").format(key=key))
            continue
        if "\n" in value or "\0" in value:
            problems.append(_("{key} cannot contain a line break.").format(key=key))
            continue
        if key in INT_KEYS and not value.isdigit():
            problems.append(_("{key} must be a whole number, not “{value}”.").format(key=key, value=value))
    if "LOCAL_DIR" in updates:
        folder = expand_home(updates["LOCAL_DIR"], home)
        if not folder:
            problems.append(_("Choose a folder to sync."))
        elif not os.path.isdir(folder):
            problems.append(_("The folder does not exist: {folder}").format(folder=folder))
        elif os.path.realpath(folder) in (os.path.realpath(home), "/"):
            problems.append(_("Syncing your whole home folder (or the whole disk) is not"
                              " supported. Choose a folder inside it."))
    if "REMOTE" in updates:
        name, sep, _path = updates["REMOTE"].partition(":")
        if not sep or not name:
            problems.append(_("The remote must look like name:folder, for example gdrive:LoudSync."))
    if "CONFLICT_RESOLVE" in updates and updates["CONFLICT_RESOLVE"] not in CONFLICT_POLICIES:
        problems.append(_("Unknown conflict policy: {policy}").format(policy=updates["CONFLICT_RESOLVE"]))
    if updates.get("MAX_DELETE_PERCENT", "0").isdigit() and int(updates.get("MAX_DELETE_PERCENT", "0")) > 100:
        problems.append(_("The safety brake is a percentage, so it cannot be over 100."))
    return problems


_DOUBLE_QUOTE_SAFE = re.compile(r'^[^"$`\\!]*$')


def bash_value(key, value):
    """A value written the way the shipped file writes it, and still safe.

    Double quotes match the style of the example file, but they expand $ and
    backticks, so anything carrying those falls back to single quotes. A folder
    named "$HOME" must stay a folder named "$HOME".
    """
    if key in INT_KEYS and value.isdigit():
        return value
    if _DOUBLE_QUOTE_SAFE.match(value):
        return f'"{value}"'
    return shlex.quote(value)


def _assignment_re(key):
    return re.compile(rf"^\s*{re.escape(key)}=")


def _commented_re(key):
    return re.compile(rf"^\s*#\s*{re.escape(key)}=")


def render_config(text, updates):
    """The config file with some values replaced, comments left alone.

    A key that is already assigned is rewritten in place (every assignment, so
    an earlier duplicate can't silently disagree with the last one). A key that
    only appears as a commented-out example is written right under it. Anything
    else goes at the end.
    """
    lines = text.splitlines()
    appended = []
    for key, value in updates.items():
        new_line = f"{key}={bash_value(key, value)}"
        hits = [i for i, line in enumerate(lines) if _assignment_re(key).match(line)]
        if hits:
            for i in hits:
                lines[i] = new_line
            continue
        examples = [i for i, line in enumerate(lines) if _commented_re(key).match(line)]
        if examples:
            lines.insert(examples[-1] + 1, new_line)
        else:
            appended.append(new_line)
    if appended:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Set from the loudsync window.")
        lines.extend(appended)
    return "\n".join(lines) + "\n"


def write_config(paths, updates):
    """Apply updates atomically, keep the previous file as .bak, and prove it.

    The engine sources this file every minute. A half-written file read at the
    wrong moment would be a broken run, so the new content is written beside it
    and moved into place in one step. It is then read back through bash: if what
    bash sees is not what was asked for, the old file goes back.
    """
    with open(paths.config_file, encoding="utf-8") as f:
        old = f.read()
    new = render_config(old, updates)
    mode = os.stat(paths.config_file).st_mode & 0o777
    directory = os.path.dirname(paths.config_file)
    shutil.copy2(paths.config_file, paths.config_file + ".bak")
    _atomic_write(paths.config_file, new, mode, directory)
    try:
        seen = read_config(paths)
        wrong = [k for k, v in updates.items() if seen.values.get(k) != v]
        if wrong:
            raise ConfigError("the file did not read back as written: " + ", ".join(wrong))
    except Exception:
        _atomic_write(paths.config_file, old, mode, directory)
        raise


def create_config(paths, template_text):
    os.makedirs(paths.config_home, exist_ok=True)
    _atomic_write(paths.config_file, template_text, 0o600, paths.config_home)


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_text(path, text):
    mode = 0o644
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        pass
    _atomic_write(path, text, mode, os.path.dirname(path))


def _atomic_write(path, text, mode, directory):
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".loudsync-gui-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# --- rclone ------------------------------------------------------------------


def find_rclone(config, home):
    """Same search order as the engine, which matters under systemd's PATH."""
    if config is not None and config["RCLONE_BIN"]:
        return config["RCLONE_BIN"]
    for candidate in (os.path.join(home, ".local", "bin", "rclone"),
                      "/usr/bin/rclone", "/usr/local/bin/rclone"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("rclone") or ""


def list_remotes(rclone):
    """[(name, backend)] for every configured remote."""
    res = subprocess.run([rclone, "listremotes", "--long"],
                         capture_output=True, text=True, timeout=20)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "rclone listremotes failed")
    remotes = []
    for line in res.stdout.splitlines():
        name, _sep, backend = line.partition(":")
        if name:
            remotes.append((name.strip(), backend.strip()))
    return remotes


# Backends a person can connect from the window. Each one authorises through
# the browser with rclone's own flow; everything else goes through
# `rclone config` in a terminal, which knows every question every backend asks.
PROVIDERS = (
    ("drive", "Google Drive"),
    ("dropbox", "Dropbox"),
    ("onedrive", "OneDrive"),
)


def connect_remote_argv(rclone, name, backend):
    return [rclone, "config", "create", name, backend]


REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. -]*$")


# --- Engine state ------------------------------------------------------------


@dataclass
class LogEvent:
    when: datetime
    text: str
    kind: str


_OWN_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \| (.*)$")


def classify(text):
    if text.startswith("===== START"):
        return "start"
    if text.startswith("===== DONE"):
        return "done"
    if text.startswith("===== FAILED"):
        return "failed"
    if text.startswith("===== CONFLICT ("):
        return "conflict"
    if text.startswith("===== CONFLICT"):
        return "conflict-detail"
    if text.startswith("ATTENTION:"):
        return "attention"
    if text.startswith("ERROR:"):
        return "error"
    if text.startswith("Still being written to"):
        return "postponed"
    if text.startswith("Notified:"):
        return "notified"
    return "info"


def parse_log(text):
    """loudsync's own lines. rclone writes into the same file in its own format;
    those are left to the full log."""
    events = []
    for line in text.splitlines():
        m = _OWN_LINE.match(line)
        if not m:
            continue
        try:
            when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        events.append(LogEvent(when=when, text=m.group(2), kind=classify(m.group(2))))
    return events


def tail(path, max_bytes):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except FileNotFoundError:
        return ""
    text = data.decode(errors="replace")
    if size > max_bytes:
        # The first line is almost certainly cut in half.
        text = text.split("\n", 1)[-1]
    return text


def read_log_events(paths, max_bytes=512 * 1024):
    """Recent events, oldest first. Reaches into the rotated log when the
    current one is too young to say when the last run was."""
    current = tail(paths.log, max_bytes)
    events = parse_log(current)
    if not any(e.kind in ("done", "failed") for e in events):
        events = parse_log(tail(paths.log + ".1", max_bytes)) + events
    return events


def lock_held(lock_path, proc_locks="/proc/locks"):
    """Whether a run holds the engine's lock, without taking it.

    Taking it to find out, even for a moment, would make a run that starts in
    that moment skip itself. The log can't answer either: a run that was killed
    leaves a START with no DONE forever.
    """
    try:
        st = os.stat(lock_path)
    except FileNotFoundError:
        return False
    key = "%02x:%02x:%d" % (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    try:
        with open(proc_locks, encoding="ascii", errors="replace") as f:
            for line in f:
                fields = line.split()
                if "FLOCK" in fields and key in fields and "->" not in fields:
                    return True
    except OSError:
        pass
    return False


def read_int(path):
    try:
        with open(path, encoding="ascii") as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def read_lines(path):
    return [line for line in read_text(path).splitlines() if line.strip()]


# --- systemd -----------------------------------------------------------------

TIMER = "loudsync.timer"
WATCHER = "loudsync-watch.service"
RESUME = "loudsync-resume"          # transient timer that ends a pause
AUTOMATION_UNITS = (TIMER, WATCHER)


@dataclass
class UnitState:
    load: str = ""
    active: str = ""
    file_state: str = ""
    next_elapse: float = 0.0        # epoch seconds, 0 if none


@dataclass
class Automation:
    timer: UnitState
    watcher: UnitState
    resume_at: float = 0.0

    @property
    def installed(self):
        return self.timer.load == "loaded"

    @property
    def enabled(self):
        return self.timer.file_state == "enabled"

    @property
    def running(self):
        return self.timer.active == "active"

    @property
    def paused(self):
        # Turned on at login but stopped now: that is a pause, and it ends by
        # itself at the next login at the latest.
        return self.installed and self.enabled and not self.running

    @property
    def instant_uploads(self):
        return self.watcher.active == "active"


def systemctl(*args, check=False):
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True, timeout=30, check=check)


def parse_show(text, count):
    """Blocks of `systemctl show` output, one per unit, in the order asked."""
    blocks = [b for b in text.strip("\n").split("\n\n")]
    states = []
    for block in blocks:
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        elapse = props.get("NextElapseUSecRealtime", "")
        states.append(UnitState(
            load=props.get("LoadState", ""),
            active=props.get("ActiveState", ""),
            file_state=props.get("UnitFileState", ""),
            next_elapse=float(elapse[1:]) if elapse.startswith("@") else 0.0,
        ))
    while len(states) < count:
        states.append(UnitState())
    return states[:count]


def read_automation():
    units = (TIMER, WATCHER, RESUME + ".timer")
    try:
        res = systemctl("show", "--timestamp=unix",
                        "-p", "LoadState", "-p", "ActiveState", "-p", "UnitFileState",
                        "-p", "NextElapseUSecRealtime", *units)
        timer, watcher, resume = parse_show(res.stdout, len(units))
    except (OSError, subprocess.SubprocessError):
        timer, watcher, resume = UnitState(), UnitState(), UnitState()
    resume_at = resume.next_elapse if resume.active == "active" else 0.0
    return Automation(timer=timer, watcher=watcher, resume_at=resume_at)


def _cancel_resume():
    # Stopping a transient unit unloads it, so the name is free next time.
    systemctl("stop", RESUME + ".timer")
    systemctl("reset-failed", RESUME + ".timer", RESUME + ".service")


def pause(until=None):
    """Stop the timer and the watcher. A run already going finishes first.

    `until` (epoch seconds) hands the resume to systemd rather than to this
    window, so the pause ends on time even if the window is closed by then.
    """
    _cancel_resume()
    res = systemctl("stop", *AUTOMATION_UNITS)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "could not stop the sync units")
    if until:
        stamp = datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M:%S")
        cmd = ["systemd-run", "--user", "--quiet", "--collect",
               f"--unit={RESUME}", f"--on-calendar={stamp}",
               "--timer-property=AccuracySec=10s",
               "--timer-property=RemainAfterElapse=no",
               shutil.which("systemctl") or "/usr/bin/systemctl",
               "--user", "start", *AUTOMATION_UNITS]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            # Paused with no way back on its own is exactly the silent state
            # this tool exists to prevent. Undo the pause instead.
            resume()
            raise RuntimeError(res.stderr.strip() or "could not schedule the resume")


def hold_automation():
    """Stop the timer and the watcher for a moment of setup, quietly: on a
    machine where they were never installed there is nothing to stop."""
    _cancel_resume()
    systemctl("stop", *AUTOMATION_UNITS)


def resume():
    _cancel_resume()
    res = systemctl("start", TIMER)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "could not start the timer")
    # The watcher needs inotify-tools. Without it the timer still covers both
    # directions, so its failure is shown, not raised.
    systemctl("start", WATCHER)


def set_automation(enabled):
    _cancel_resume()
    verb = "enable" if enabled else "disable"
    res = systemctl(verb, "--now", *AUTOMATION_UNITS)
    if res.returncode != 0 and enabled:
        # Same reasoning as resume(): the timer alone is enough to be on.
        res = systemctl(verb, "--now", TIMER)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"systemctl {verb} failed")


def restart_watcher():
    """The watcher reads the config once, at start."""
    systemctl("try-restart", WATCHER)


def sync_now(paths):
    """One run, now, skipping the wait for the folder to go quiet.

    Started through systemd rather than as a child of this window: closing the
    window must not kill a sync halfway, and the run gets the same low priority
    as the timer's.
    """
    cmd = ["systemd-run", "--user", "--quiet", "--collect",
           f"--unit=loudsync-now-{int(time.time())}",
           "-p", "Nice=10", "-p", "IOSchedulingClass=idle",
           paths.engine, "--now"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "could not start a sync")


# --- Conflicts ---------------------------------------------------------------

CONFLICT_SUFFIXES = (".conflict-local", ".conflict-remote")
_PRUNE = {".git", "node_modules"}   # the same two `loudsync --status` skips


@dataclass
class Conflict:
    copy_path: str
    original_path: str
    rel: str
    copy_side: str                  # "local" or "remote": where the copy came from
    copy_mtime: float
    copy_size: int
    original_mtime: float = 0.0     # 0 when the original is gone
    original_size: int = 0

    @property
    def original_exists(self):
        return self.original_mtime > 0


def find_conflicts(local_dir, limit=2000):
    found = []
    for root, dirs, files in os.walk(local_dir):
        dirs[:] = [d for d in dirs if d not in _PRUNE]
        for name in files:
            side = next((s for s in CONFLICT_SUFFIXES if name.endswith(s)), None)
            if side is None:
                continue
            copy_path = os.path.join(root, name)
            original = copy_path[: -len(side)]
            try:
                cst = os.stat(copy_path)
            except FileNotFoundError:
                continue
            c = Conflict(
                copy_path=copy_path,
                original_path=original,
                rel=os.path.relpath(original, local_dir),
                copy_side=side.rsplit("-", 1)[1],
                copy_mtime=cst.st_mtime,
                copy_size=cst.st_size,
            )
            try:
                ost = os.stat(original)
                c.original_mtime, c.original_size = ost.st_mtime, ost.st_size
            except FileNotFoundError:
                pass
            found.append(c)
            if len(found) >= limit:
                return found
    found.sort(key=lambda c: c.rel.lower())
    return found


def resolve_conflict(conflict, keep, trash):
    """Settle one conflict. `keep` is "original" or "copy".

    The version you don't keep goes to the trash, never straight to deletion:
    this is the one decision in the whole tool that a human makes by hand, and
    a misclick should cost a trip to the trash, not a file. The sync then
    carries the result to the other side like any other edit.
    """
    if not os.path.exists(conflict.copy_path):
        raise FileNotFoundError(conflict.copy_path)
    if keep == "original":
        trash(conflict.copy_path)
    elif keep == "copy":
        if os.path.exists(conflict.original_path):
            trash(conflict.original_path)
        os.rename(conflict.copy_path, conflict.original_path)
    else:
        raise ValueError(keep)


# --- The overall picture -----------------------------------------------------


@dataclass
class Status:
    configured: bool = False
    config_error: str = ""
    ever_synced: bool = False
    running: bool = False
    failures: int = 0
    fail_threshold: int = 3
    fail_cause: str = ""
    quiet_skips: int = 0
    repos: list = field(default_factory=list)
    last_success: datetime = None
    last_failure: datetime = None
    last_result: str = ""           # "done", "failed" or ""
    engine_error: str = ""          # the engine refused to start at all
    needs_decision: str = ""
    automation: Automation = None
    events: list = field(default_factory=list)


def read_status(paths, config=None, config_error="", events=None, automation=None):
    s = Status()
    s.configured = config is not None
    s.config_error = config_error
    s.ever_synced = os.path.exists(paths.state("filters-base.md5"))
    s.running = lock_held(paths.state("loudsync.lock"))
    s.failures = read_int(paths.state("consecutive-failures"))
    s.fail_threshold = config.int("FAIL_THRESHOLD") if config else 3
    s.fail_cause = read_text(paths.state("last-failure-cause")).strip() if s.failures else ""
    s.quiet_skips = read_int(paths.state("quiet-skips"))
    s.repos = read_lines(paths.state("repos-previous.txt"))
    s.events = read_log_events(paths) if events is None else events
    s.automation = read_automation() if automation is None else automation

    last_outcome = None
    for i, e in enumerate(s.events):
        if e.kind == "done":
            s.last_success = e.when
            last_outcome = i
        elif e.kind == "failed":
            s.last_failure = e.when
            last_outcome = i
    if last_outcome is not None:
        s.last_result = s.events[last_outcome].kind

    # Anything the engine said after its last outcome is still current.
    after = s.events[last_outcome + 1:] if last_outcome is not None else s.events
    for e in after:
        if e.kind == "attention":
            s.needs_decision = e.text.split(": ", 1)[-1]
        elif e.kind == "error":
            # Preflight errors (a missing remote, a missing folder) end the run
            # before the failure counter is touched, so nothing else would show
            # them. Only the latest one matters.
            s.engine_error = e.text[len("ERROR: "):]
    return s


# Headline states, most urgent first. The window and the tray icon both show
# the first one that applies; lower ones are still visible on the status page.
SETUP = "setup"
BROKEN = "broken"          # the engine can't even start
DECISION = "decision"      # stopped until a human approves a plan
FAILING = "failing"        # failed past the alert threshold
SYNCING = "syncing"
PAUSED = "paused"
RETRYING = "retrying"      # failed, but below the threshold
CONFLICTS = "conflicts"
OFF = "off"                # automation disabled
OK = "ok"


def headline(status, conflict_count=0):
    if not status.configured or not status.ever_synced:
        return SETUP
    if status.config_error or status.engine_error:
        return BROKEN
    if status.needs_decision:
        return DECISION
    if status.failures >= status.fail_threshold:
        return FAILING
    if status.running:
        return SYNCING
    a = status.automation
    if a is not None and a.paused:
        return PAUSED
    if status.failures > 0:
        return RETRYING
    if conflict_count:
        return CONFLICTS
    if a is not None and not a.running:
        return OFF
    return OK


def ago(when, now=None):
    """'just now', '4 minutes ago', 'yesterday at 18:02', '12 Sep at 09:15'."""
    if when is None:
        return _("never")
    now = now or datetime.now()
    seconds = (now - when).total_seconds()
    if seconds < 45:
        return _("just now")
    if seconds < 3600:
        minutes = max(1, round(seconds / 60))
        return ngettext("{n} minute ago", "{n} minutes ago", minutes).format(n=minutes)
    if when.date() == now.date():
        return _("today at {time}").format(time=f"{when:%H:%M}")
    if (now.date() - when.date()).days == 1:
        return _("yesterday at {time}").format(time=f"{when:%H:%M}")
    return _("{day} {month} at {time}").format(day=when.day, month=f"{when:%b}", time=f"{when:%H:%M}")


def human_size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def count_repos(local_dir, max_depth=8):
    """How many git repos a first run would exclude, for the setup assistant."""
    count = 0
    base = local_dir.rstrip("/").count("/")
    for root, dirs, _files in os.walk(local_dir):
        if ".git" in dirs:
            count += 1
            dirs[:] = []
            continue
        if root.count("/") - base >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d != "node_modules"]
    return count


def dry_run_copies(log_slice):
    """Files a dry run said it would copy, counted from its log lines."""
    return sum(1 for line in log_slice.splitlines()
               if "Skipped copy as --dry-run is set" in line)


def recent_errors(paths, limit=40):
    """The last rclone ERROR lines and loudsync's own failure lines, for the
    "Technical details" of a failure the engine couldn't name."""
    lines = [line for line in tail(paths.log, 256 * 1024).splitlines()
             if " ERROR " in line or "ERROR :" in line or "===== FAILED" in line]
    return lines[-limit:]


def engine_version(paths):
    """The VERSION line of the installed engine, read rather than assumed."""
    m = re.search(r'^VERSION="([^"]+)"', read_text(paths.engine), re.MULTILINE)
    return m.group(1) if m else ""


# --- Files that ship with loudsync -------------------------------------------


def template(name, paths, here=os.path.dirname(os.path.abspath(__file__))):
    """A shipped file (the example config, the default filters), from the
    source tree when running from a checkout, or from where install.sh put it."""
    for candidate in (os.path.join(here, "..", "..", "config", name),
                      os.path.join(paths.home, ".local", "share", "loudsync", name)):
        if os.path.isfile(candidate):
            return os.path.normpath(candidate)
    return ""


# --- Starting with the session -----------------------------------------------


def autostart_file(paths, env=None):
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or os.path.join(paths.home, ".config")
    return os.path.join(base, "autostart", "loudsync-gui.desktop")


def autostart_enabled(paths, env=None):
    """XDG autostart: present and not Hidden=true means it starts at login."""
    text = read_text(autostart_file(paths, env))
    if not text:
        return False
    hidden = re.search(r"^Hidden\s*=\s*true\s*$", text, re.MULTILINE | re.IGNORECASE)
    return hidden is None


def set_autostart(paths, enabled, exec_path, env=None):
    """Turned off by writing Hidden=true, which is how the XDG spec says a
    user disables an autostart entry, rather than deleting it: install.sh then
    knows the choice was made and leaves it alone on the next upgrade."""
    path = autostart_file(paths, env)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text(path, "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=loudsync",
        "Comment=Tray icon for loudsync: shows whether your files are syncing",
        f"Exec={shlex.quote(exec_path)} --background",
        "Icon=loudsync",
        "Terminal=false",
        "X-GNOME-Autostart-enabled=" + ("true" if enabled else "false"),
        "Hidden=" + ("false" if enabled else "true"),
        "",
    ]))
