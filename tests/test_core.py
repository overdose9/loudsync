"""Tests for gui/loudsync_gui/core.py. Run with: python3 -m unittest discover tests"""

import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gui"))

from loudsync_gui import core  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "config", "loudsync.conf.example")


class Sandbox(unittest.TestCase):
    """A fake home with its own config and state directories."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.paths = core.Paths.from_env({"HOME": self.home})
        os.makedirs(self.paths.config_home)
        os.makedirs(self.paths.state_home)
        with open(EXAMPLE, encoding="utf-8") as f:
            core.create_config(self.paths, f.read())

    def tearDown(self):
        self.tmp.cleanup()


class ConfigTests(Sandbox):
    def test_reads_the_shipped_example_through_bash(self):
        cfg = core.read_config(self.paths)
        self.assertEqual(cfg["LOCAL_DIR"], "~/Documents")
        self.assertEqual(cfg.local_dir, os.path.join(self.home, "Documents"))
        self.assertEqual(cfg["REMOTE"], "gdrive:LoudSync")
        self.assertEqual(cfg.remote_name, "gdrive")
        self.assertEqual(cfg.int("QUIET_SECONDS"), 15)
        # Commented out in the example, so the engine's default applies.
        self.assertEqual(cfg["FILTERS_BASE"], self.paths.filters_base_default)

    def test_write_replaces_in_place_and_keeps_comments(self):
        core.write_config(self.paths, {"QUIET_SECONDS": "30", "NOTIFY": "0"})
        text = core.read_text(self.paths.config_file)
        self.assertIn("QUIET_SECONDS=30\n", text)
        self.assertIn("# Don't start a sync while a file was written", text)
        self.assertEqual(text.count("QUIET_SECONDS="), 1)
        self.assertEqual(core.read_config(self.paths)["NOTIFY"], "0")
        self.assertTrue(os.path.exists(self.paths.config_file + ".bak"))

    def test_commented_example_gets_the_value_right_under_it(self):
        core.write_config(self.paths, {"FILTERS_BASE": "/tmp/f.txt"})
        lines = core.read_text(self.paths.config_file).splitlines()
        i = next(i for i, l in enumerate(lines) if l.startswith("# FILTERS_BASE="))
        self.assertEqual(lines[i + 1], 'FILTERS_BASE="/tmp/f.txt"')

    def test_values_that_bash_would_expand_survive_intact(self):
        for weird in ("~/My $HOME folder", "~/it's `here`", '~/a "quoted" name', "~/back\\slash"):
            core.write_config(self.paths, {"LOCAL_DIR": weird})
            self.assertEqual(core.read_config(self.paths)["LOCAL_DIR"], weird)

    def test_mode_is_preserved(self):
        os.chmod(self.paths.config_file, 0o600)
        core.write_config(self.paths, {"TRANSFERS": "4"})
        self.assertEqual(os.stat(self.paths.config_file).st_mode & 0o777, 0o600)

    def test_broken_config_is_reported_not_guessed(self):
        with open(self.paths.config_file, "a", encoding="utf-8") as f:
            f.write('LOCAL_DIR="unterminated\n')
        with self.assertRaises(core.ConfigError):
            core.read_config(self.paths)

    def test_unknown_key_appended_is_rejected_by_validate(self):
        self.assertTrue(core.validate({"NOPE": "1"}, self.home))

    def test_validate(self):
        docs = os.path.join(self.home, "Documents")
        os.makedirs(docs)
        self.assertEqual(core.validate({"LOCAL_DIR": "~/Documents", "REMOTE": "gdrive:X"}, self.home), [])
        self.assertTrue(core.validate({"LOCAL_DIR": "~"}, self.home))
        self.assertTrue(core.validate({"LOCAL_DIR": "~/missing"}, self.home))
        self.assertTrue(core.validate({"REMOTE": "nocolon"}, self.home))
        self.assertTrue(core.validate({"QUIET_SECONDS": "-1"}, self.home))
        self.assertTrue(core.validate({"MAX_DELETE_PERCENT": "150"}, self.home))
        self.assertTrue(core.validate({"CONFLICT_RESOLVE": "coin"}, self.home))
        self.assertTrue(core.validate({"REMOTE": "a:b\nc"}, self.home))

    def test_contract_and_expand_home(self):
        self.assertEqual(core.contract_home(self.home + "/Docs", self.home), "~/Docs")
        self.assertEqual(core.contract_home("/srv/x", self.home), "/srv/x")
        self.assertEqual(core.expand_home("~/Docs", self.home), self.home + "/Docs")


class LogTests(Sandbox):
    LOG = (
        "2026-09-27 01:30:40 | ===== START (22 repos excluded) =====\n"
        "2026/09/27 01:30:41 INFO  : rclone line, not ours\n"
        "2026-09-27 01:31:30 | ===== DONE =====\n"
        "2026-09-27 01:33:00 | Still being written to (a.md); postponing this run (1/5).\n"
        "2026-09-27 01:33:14 | ===== START (22 repos excluded) =====\n"
        "2026-09-27 01:34:04 | ===== FAILED (exit=7) =====\n"
        "2026-09-27 01:35:04 | ATTENTION: sync is stopped until a human decides: these repos left the list (renamed?): a b\n"
    )

    def write_log(self, text, name="loudsync.log"):
        with open(self.paths.state(name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_parse_keeps_only_our_lines(self):
        events = core.parse_log(self.LOG)
        self.assertEqual([e.kind for e in events],
                         ["start", "done", "postponed", "start", "failed", "attention"])

    def test_status_after_failure_and_attention(self):
        self.write_log(self.LOG)
        auto = core.Automation(core.UnitState("loaded", "active", "enabled"),
                               core.UnitState("loaded", "active", "enabled"))
        s = core.read_status(self.paths, config=core.read_config(self.paths), automation=auto)
        self.assertEqual(s.last_result, "failed")
        self.assertEqual(s.last_success, datetime(2026, 9, 27, 1, 31, 30))
        self.assertIn("repos left the list", s.needs_decision)

    def test_decision_clears_after_a_good_run(self):
        self.write_log(self.LOG + "2026-09-27 01:40:00 | ===== DONE =====\n")
        s = core.read_status(self.paths, config=None, automation=core.Automation(core.UnitState(), core.UnitState()))
        self.assertEqual(s.needs_decision, "")

    def test_preflight_error_is_surfaced(self):
        self.write_log(self.LOG.split("2026-09-27 01:33:00")[0]
                       + "2026-09-27 01:36:00 | ERROR: rclone remote 'gdrive' is not configured. Run: rclone config\n")
        s = core.read_status(self.paths, config=None, automation=core.Automation(core.UnitState(), core.UnitState()))
        self.assertIn("not configured", s.engine_error)

    def test_rotated_log_is_consulted_when_current_is_young(self):
        self.write_log("2026-09-27 01:31:30 | ===== DONE =====\n", "loudsync.log.1")
        self.write_log("2026-09-27 01:40:00 | Log rotated at 50 MB\n")
        events = core.read_log_events(self.paths)
        self.assertEqual(events[0].kind, "done")

    def test_tail_drops_the_cut_line(self):
        self.write_log("x" * 100 + "\n2026-09-27 01:31:30 | ===== DONE =====\n")
        self.assertTrue(core.tail(self.paths.log, 40).startswith("2026"))


class HeadlineTests(unittest.TestCase):
    def status(self, **kw):
        s = core.Status(configured=True, ever_synced=True,
                        automation=core.Automation(core.UnitState("loaded", "active", "enabled"),
                                                   core.UnitState("loaded", "active", "enabled")))
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def test_priorities(self):
        self.assertEqual(core.headline(self.status()), core.OK)
        self.assertEqual(core.headline(self.status(configured=False)), core.SETUP)
        self.assertEqual(core.headline(self.status(ever_synced=False)), core.SETUP)
        self.assertEqual(core.headline(self.status(engine_error="x")), core.BROKEN)
        self.assertEqual(core.headline(self.status(needs_decision="x", running=True)), core.DECISION)
        self.assertEqual(core.headline(self.status(failures=3, running=True)), core.FAILING)
        self.assertEqual(core.headline(self.status(failures=1, running=True)), core.SYNCING)
        self.assertEqual(core.headline(self.status(failures=1)), core.RETRYING)
        self.assertEqual(core.headline(self.status(), conflict_count=2), core.CONFLICTS)

    def test_paused_and_off(self):
        paused = core.Automation(core.UnitState("loaded", "inactive", "enabled"), core.UnitState())
        off = core.Automation(core.UnitState("loaded", "inactive", "disabled"), core.UnitState())
        self.assertEqual(core.headline(self.status(automation=paused)), core.PAUSED)
        self.assertEqual(core.headline(self.status(automation=off)), core.OFF)


class SystemTests(unittest.TestCase):
    def test_lock_held_reads_proc_locks(self):
        with tempfile.TemporaryDirectory() as d:
            lock = os.path.join(d, "loudsync.lock")
            open(lock, "w").close()
            st = os.stat(lock)
            key = "%02x:%02x:%d" % (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
            locks = os.path.join(d, "locks")
            with open(locks, "w") as f:
                f.write(f"1: POSIX  ADVISORY  WRITE 1135 103:02:1 0 EOF\n")
            self.assertFalse(core.lock_held(lock, locks))
            with open(locks, "a") as f:
                f.write(f"105: FLOCK  ADVISORY  WRITE 582048 {key} 0 EOF\n")
            self.assertTrue(core.lock_held(lock, locks))
            self.assertFalse(core.lock_held(os.path.join(d, "missing"), locks))

    def test_lock_held_against_a_real_flock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as d:
            lock = os.path.join(d, "loudsync.lock")
            with open(lock, "w") as f:
                self.assertFalse(core.lock_held(lock))
                fcntl.flock(f, fcntl.LOCK_EX)
                self.assertTrue(core.lock_held(lock))

    def test_parse_show(self):
        text = ("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nNextElapseUSecRealtime=\n\n"
                "LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n\n"
                "NextElapseUSecRealtime=@1790000000\nLoadState=loaded\nActiveState=active\nUnitFileState=transient\n")
        t, w, r = core.parse_show(text, 3)
        self.assertEqual((t.active, w.active), ("active", "inactive"))
        self.assertEqual(r.next_elapse, 1790000000.0)


class ConflictTests(unittest.TestCase):
    def test_find_and_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "sub"))
            os.makedirs(os.path.join(d, "node_modules"))
            for rel, text in (("sub/a.txt", "mine"), ("sub/a.txt.conflict-remote", "theirs"),
                              ("b.odt.conflict-local", "old"), ("node_modules/x.conflict-local", "")):
                with open(os.path.join(d, rel), "w") as f:
                    f.write(text)
            found = core.find_conflicts(d)
            self.assertEqual([c.rel for c in found], ["b.odt", "sub/a.txt"])
            a = found[1]
            self.assertEqual(a.copy_side, "remote")
            self.assertTrue(a.original_exists)
            self.assertFalse(found[0].original_exists)

            trashed = []
            core.resolve_conflict(a, "copy", trashed.append)
            self.assertEqual(trashed, [a.original_path])
            self.assertFalse(os.path.exists(a.copy_path))
            with open(a.original_path) as f:
                self.assertEqual(f.read(), "theirs")

            trashed.clear()
            core.resolve_conflict(found[0], "original", trashed.append)
            self.assertEqual(trashed, [found[0].copy_path])

    def test_resolving_a_vanished_conflict_fails_loudly(self):
        c = core.Conflict("/nonexistent.conflict-local", "/nonexistent", "x", "local", 0, 0)
        with self.assertRaises(FileNotFoundError):
            core.resolve_conflict(c, "original", lambda p: None)


class SmallTests(unittest.TestCase):
    def test_ago(self):
        now = datetime(2026, 9, 27, 12, 0, 0)
        self.assertEqual(core.ago(None), "never")
        self.assertEqual(core.ago(datetime(2026, 9, 27, 11, 59, 50), now), "just now")
        self.assertEqual(core.ago(datetime(2026, 9, 27, 11, 56, 0), now), "4 minutes ago")
        self.assertEqual(core.ago(datetime(2026, 9, 27, 8, 5, 0), now), "today at 08:05")
        self.assertEqual(core.ago(datetime(2026, 9, 26, 18, 2, 0), now), "yesterday at 18:02")

    def test_dry_run_copies(self):
        text = ("2026/09/27 NOTICE: a.txt: Skipped copy as --dry-run is set (size 1Ki)\n"
                "2026/09/27 NOTICE: b.txt: Skipped copy as --dry-run is set (size 2Ki)\n"
                "2026/09/27 INFO  : something else\n")
        self.assertEqual(core.dry_run_copies(text), 2)

    def test_count_repos(self):
        with tempfile.TemporaryDirectory() as d:
            for p in ("a/.git", "b/c/.git", "a/nested/.git", "node_modules/z/.git"):
                os.makedirs(os.path.join(d, p))
            # a/nested is inside a repo, which is excluded whole.
            self.assertEqual(core.count_repos(d), 2)


if __name__ == "__main__":
    unittest.main()


class SystemdCommandTests(unittest.TestCase):
    """systemctl and systemd-run replaced by recorders on PATH. Changing HOME
    does not isolate `systemctl --user`: it talks to the real user manager."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = os.path.join(self.tmp.name, "calls")
        for tool in ("systemctl", "systemd-run"):
            path = os.path.join(self.tmp.name, tool)
            with open(path, "w") as f:
                f.write(f'#!/bin/sh\necho "{tool} $*" >> "{self.calls}"\n')
            os.chmod(path, 0o755)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.tmp.name + os.pathsep + self.old_path

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        self.tmp.cleanup()

    def recorded(self):
        with open(self.calls) as f:
            return f.read().splitlines()

    def test_pause_for_an_hour_hands_the_resume_to_systemd(self):
        until = datetime(2026, 9, 27, 15, 40).timestamp()
        core.pause(until)
        calls = self.recorded()
        self.assertIn("systemctl --user stop loudsync.timer loudsync-watch.service", calls)
        run = [c for c in calls if c.startswith("systemd-run")][0]
        self.assertIn("--unit=loudsync-resume", run)
        self.assertIn("--on-calendar=2026-09-27 15:40:00", run)
        self.assertIn("RemainAfterElapse=no", run)
        self.assertTrue(run.endswith("--user start loudsync.timer loudsync-watch.service"))

    def test_pause_until_resumed_schedules_nothing(self):
        core.pause(None)
        self.assertFalse([c for c in self.recorded() if c.startswith("systemd-run")])

    def test_resume_cancels_the_pending_resume_first(self):
        core.resume()
        calls = self.recorded()
        self.assertEqual(calls[0], "systemctl --user stop loudsync-resume.timer")
        self.assertIn("systemctl --user start loudsync.timer", calls)

    def test_sync_now_skips_the_quiet_wait_at_low_priority(self):
        paths = core.Paths.from_env({"HOME": self.tmp.name, "LOUDSYNC_ENGINE_DIR": "/opt/ls"})
        core.sync_now(paths)
        run = self.recorded()[0]
        self.assertIn("-p Nice=10 -p IOSchedulingClass=idle /opt/ls/loudsync --now", run)
