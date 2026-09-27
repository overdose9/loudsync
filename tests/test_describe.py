"""Tests for gui/loudsync_gui/describe.py."""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gui"))

from loudsync_gui import core, describe  # noqa: E402

NOW = datetime(2026, 9, 27, 12, 0, 0)
ON = core.Automation(core.UnitState("loaded", "active", "enabled"),
                     core.UnitState("loaded", "active", "enabled"))


def status(**kw):
    s = core.Status(configured=True, ever_synced=True, automation=ON,
                    last_success=datetime(2026, 9, 27, 11, 58, 0))
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class HeadlineTests(unittest.TestCase):
    def test_ok_is_backed_by_a_time(self):
        h = describe.headline_for(status(), now=NOW)
        self.assertEqual((h.title, h.tone, h.loud), ("Up to date", "ok", False))
        self.assertEqual(h.detail, "Last synced 2 minutes ago")

    def test_ok_without_a_recorded_run_says_so(self):
        h = describe.headline_for(status(last_success=None), now=NOW)
        self.assertIn("No finished sync", h.detail)

    def test_failing_shouts(self):
        h = describe.headline_for(status(failures=4), now=NOW)
        self.assertEqual(h.title, "Sync is failing")
        self.assertTrue(h.loud)
        self.assertIn("4 failed attempts in a row", h.detail)

    def test_paused_until(self):
        until = datetime(2026, 9, 27, 15, 40).timestamp()
        paused = core.Automation(core.UnitState("loaded", "inactive", "enabled"),
                                 core.UnitState(), resume_at=until)
        h = describe.headline_for(status(automation=paused), now=NOW)
        self.assertEqual(h.title, "Paused until 15:40")

    def test_conflicts_plural(self):
        self.assertEqual(describe.headline_for(status(), 1, now=NOW).title, "1 file needs a decision")
        self.assertEqual(describe.headline_for(status(), 3, now=NOW).title, "3 files need a decision")

    def test_broken_shows_the_engine_words(self):
        h = describe.headline_for(status(engine_error="local folder does not exist: /x"), now=NOW)
        self.assertEqual(h.detail, "local folder does not exist: /x")


class ActivityTests(unittest.TestCase):
    def test_postponements_fold_and_order_is_newest_first(self):
        text = "".join(f"2026-09-27 01:30:{i:02d} | Still being written to (a); postponing this run ({i}/5).\n"
                       for i in range(1, 4))
        text += "2026-09-27 01:31:00 | ===== DONE =====\n"
        text += "2026-09-27 01:32:00 | ===== CONFLICT (2 file(s), 1 needing a decision) =====\n"
        items = describe.activity(core.parse_log(text))
        self.assertEqual([i.text for i in items],
                         ["Conflict: 2 file(s), 1 needing a decision", "Synced",
                          "Postponed 3 times: files were still being written"])


class ConflictLineTests(unittest.TestCase):
    def test_origin_follows_the_suffix(self):
        t = datetime(2026, 9, 27, 11, 40).timestamp()
        c = core.Conflict("/f.conflict-remote", "/f", "f", "remote", t - 30, 47 * 1024, t, 48 * 1024)
        current, other, note = describe.conflict_lines(c, 120, now=NOW)
        self.assertTrue(current.startswith("Current: from this computer"))
        self.assertTrue(other.startswith("Other copy: from the remote"))
        self.assertIn("30 seconds apart", note)

    def test_far_apart_has_no_race_note(self):
        t = datetime(2026, 9, 27, 11, 40).timestamp()
        c = core.Conflict("/f.conflict-local", "/f", "f", "local", t - 7200, 1, t, 1)
        self.assertEqual(describe.conflict_lines(c, 120, now=NOW)[2], "")



class IconFilesTests(unittest.TestCase):
    def test_shipped_icons_match_the_generator(self):
        from loudsync_gui import icons
        here = os.path.join(os.path.dirname(__file__), "..", "gui", "icons")
        for name, text in icons.tray_icons().items():
            with open(os.path.join(here, name), encoding="utf-8") as f:
                self.assertEqual(f.read(), text, f"{name} is stale: run python3 -m loudsync_gui.icons icons in gui/")


if __name__ == "__main__":
    unittest.main()
