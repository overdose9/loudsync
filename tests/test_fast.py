"""Tests for the fast lane (bin/loudsync-fast) and for `loudsync --if-needed`.

Run with: python3 -m unittest discover tests

The end-to-end half drives the real scripts against a real rclone, with a
local directory standing in for the cloud. Everything lives in a throwaway
home: its own config, state, cache and rclone remote (defined through the
environment, so the user's rclone.conf is never read). Nothing here calls
systemctl. It is skipped when rclone is not installed.
"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BIN = os.path.join(ROOT, "bin")
ENGINE = os.path.join(BIN, "loudsync")
FAST = os.path.join(BIN, "loudsync-fast")


def load_fast():
    loader = importlib.machinery.SourceFileLoader("loudsync_fast", FAST)
    spec = importlib.util.spec_from_loader("loudsync_fast", loader)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    loader.exec_module(module)
    return module


fast = load_fast()


def find_rclone():
    for candidate in (os.path.expanduser("~/.local/bin/rclone"),
                      "/usr/bin/rclone", "/usr/local/bin/rclone"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("rclone")


RCLONE = find_rclone()


class TimeTests(unittest.TestCase):
    def test_reads_every_shape_rclone_writes(self):
        base = fast.to_ms("2026-11-16T17:44:39Z")
        self.assertEqual(fast.to_ms("2026-11-16T17:44:39.528Z"), base + 528)
        self.assertEqual(fast.to_ms("2026-11-16T17:44:39.528081169+0000"), base + 528)
        self.assertEqual(fast.to_ms("2026-11-16T14:44:39.528081169-03:00"), base + 528)
        self.assertEqual(fast.to_ms("2026-11-16T18:44:39.5+01:00"), base + 500)

    def test_unreadable_is_none_not_zero(self):
        self.assertIsNone(fast.to_ms("yesterday"))
        self.assertIsNone(fast.to_ms(""))

    def test_same_version_needs_size_and_time(self):
        self.assertTrue(fast.same_version((10, 1000), (10, 1001), 1))
        self.assertFalse(fast.same_version((10, 1000), (11, 1000), 1))
        self.assertFalse(fast.same_version((10, 1000), (10, 1002), 1))
        self.assertFalse(fast.same_version((10, 1000), None, 1))


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "x.path2.lst")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_names_match_what_bisync_writes(self):
        self.assertEqual(
            fast.session_name("/home/u/Documentos", "gdrive:Sync-Docs"),
            "home_u_Documentos..gdrive_Sync-Docs")
        self.assertEqual(
            fast.session_name("/tmp/a/local", "prueba:/tmp/a/remote"),
            "tmp_a_local..prueba__tmp_a_remote")

    def test_reads_files_and_directories(self):
        self.write(
            "# bisync listing v1 from 2026-11-16T17:54:38.178607393+0000\n"
            'd       -1 - - 2026-11-04T20:36:09.257000000+0000 "Carro venta líquidos"\n'
            '-     9980 - - 2026-11-04T20:36:09.257000000+0000 '
            '"Carro venta líquidos/Bitácora \\"final\\".docx"\n')
        files, dirs = fast.read_listing(self.path)
        self.assertEqual(dirs, {"Carro venta líquidos"})
        self.assertEqual(
            files['Carro venta líquidos/Bitácora "final".docx'],
            (9980, fast.to_ms("2026-11-04T20:36:09.257Z")))

    def test_an_unknown_format_is_not_guessed_at(self):
        self.write('# bisync listing v2\n-  1 - - 2026-11-04T20:36:09Z "a"\n')
        self.assertIsNone(fast.read_listing(self.path))
        self.assertIsNone(fast.read_listing(self.path + ".missing"))


WRAPPER = """#!/usr/bin/env bash
# rclone, except that the test remote claims to be Google Drive and answers
# "what changed" from a fixture. Everything else is the real thing.
if [ "$1" = "listremotes" ] && [ "${2:-}" = "--long" ]; then
    echo "e2e: drive"; exit 0
fi
if [ "$1" = "backend" ] && [ "$2" = "query" ]; then
    echo "$4" >"${PROBE_FIXTURE}.query"
    [ -f "${PROBE_FIXTURE}" ] || exit 1
    cat "${PROBE_FIXTURE}"; exit 0
fi
exec "%s" "$@"
"""


class Sandbox:
    """A real folder pair in a throwaway home, synced by the real scripts."""

    def setUp(self):
        # Short on purpose: bisync names its listings after both paths, and
        # a deep temp directory overflows the file name limit.
        self.home = tempfile.mkdtemp(prefix="ls-", dir="/tmp")
        self.local = os.path.join(self.home, "L")
        self.remote_dir = os.path.join(self.home, "R")
        self.config_home = os.path.join(self.home, "config", "loudsync")
        self.state = os.path.join(self.home, "state", "loudsync")
        for d in (self.local, self.remote_dir, self.config_home, self.state):
            os.makedirs(d)
        # A remote of type "local" rather than an alias: bisync names its
        # listings after the alias's target, not after the alias.
        self.remote = "e2e:" + self.remote_dir
        self.fixture = os.path.join(self.home, "probe.json")
        self.wrapper = os.path.join(self.home, "rclone-as-drive")
        with open(self.wrapper, "w", encoding="utf-8") as f:
            f.write(WRAPPER % RCLONE)
        os.chmod(self.wrapper, os.stat(self.wrapper).st_mode | stat.S_IXUSR)

        self.filters_base = os.path.join(self.config_home, "filters-base.txt")
        shutil.copy(os.path.join(ROOT, "config", "filters-base.txt"), self.filters_base)
        self.conf = os.path.join(self.config_home, "loudsync.conf")
        self.write_conf(RCLONE)

        self.env = {
            "HOME": self.home,
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "XDG_CONFIG_HOME": os.path.join(self.home, "config"),
            "XDG_STATE_HOME": os.path.join(self.home, "state"),
            "XDG_CACHE_HOME": os.path.join(self.home, "cache"),
            "RCLONE_CONFIG": os.path.join(self.home, "rclone.conf"),
            "RCLONE_CONFIG_E2E_TYPE": "local",
            "PROBE_FIXTURE": self.fixture,
            "LANG": "C.UTF-8",
        }
        open(self.env["RCLONE_CONFIG"], "w").close()

        self.put("notas.txt", "uno\n")
        self.put("carpeta/informe.txt", "dos\n")
        self.engine("--resync")
        self.engine()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers --

    def write_conf(self, rclone, extra=""):
        with open(self.conf, "w", encoding="utf-8") as f:
            f.write(f'LOCAL_DIR="{self.local}"\nREMOTE="{self.remote}"\n'
                    f'RCLONE_BIN="{rclone}"\nNOTIFY=0\nQUIET_SECONDS=0\n{extra}')

    def put(self, rel, text, age=30):
        """Write a local file whose mtime is `age` seconds old, so it reads as
        settled, and never equal to the mtime it had before."""
        path = os.path.join(self.local, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self._tick = getattr(self, "_tick", 0) + 1
        when = time.time() - age + self._tick
        os.utime(path, (when, when))
        return path

    def remote_text(self, rel):
        try:
            with open(os.path.join(self.remote_dir, rel), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def engine(self, *args, ok=True):
        res = subprocess.run([ENGINE, *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(res.returncode, 0, self.log())
        return res

    def up(self, changed=(), gone=(), rclone=None, expect=None):
        lists = []
        for name, paths in (("changed", changed), ("gone", gone)):
            path = os.path.join(self.home, name + ".txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("".join(os.path.join(self.local, p) + "\n" for p in paths))
            lists.append(path)
        res = subprocess.run(
            [sys.executable, "-B", FAST, "up", rclone or RCLONE, self.local, self.remote,
             "--state-dir", self.state,
             "--filters", os.path.join(self.state, "filters-generated.txt"),
             "--filters-base", self.filters_base,
             "--changed", lists[0], "--gone", lists[1]],
            env=self.env, capture_output=True, text=True)
        if expect is not None:
            self.assertEqual(res.returncode, expect, res.stderr + self.log())
        return res.returncode

    def probe(self):
        return subprocess.run(
            [sys.executable, "-B", FAST, "probe", self.wrapper, self.local, self.remote,
             "--state-dir", self.state],
            env=self.env, capture_output=True, text=True).returncode

    def log(self):
        try:
            with open(os.path.join(self.state, "loudsync.log"), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def listing(self, side):
        return fast.read_listing(os.path.join(
            self.env["XDG_CACHE_HOME"], "rclone", "bisync",
            fast.session_name(self.local, self.remote) + f".{side}.lst"))

    def last_pass(self):
        """Everything the most recent full pass logged."""
        return self.log().rsplit("===== START", 1)[-1]

    def conflict_copies(self):
        found = []
        for base in (self.local, self.remote_dir):
            for _dir, _dirs, files in os.walk(base):
                found += [f for f in files if ".conflict-" in f]
        return found



@unittest.skipUnless(RCLONE, "rclone is not installed")
class EndToEnd(Sandbox, unittest.TestCase):

    # -- the fast lane --

    def test_an_edited_file_is_uploaded_without_a_full_pass(self):
        self.put("notas.txt", "uno, editado\n")
        self.up(changed=["notas.txt"], expect=fast.UP_OK)
        self.assertEqual(self.remote_text("notas.txt"), "uno, editado\n")
        size = os.path.getsize(os.path.join(self.local, "notas.txt"))
        for side in ("path1", "path2"):
            files, _dirs = self.listing(side)
            self.assertEqual(files["notas.txt"][0], size)
        self.assertIn("FAST | uploaded 1 file(s)", self.log())

    def test_a_second_edit_goes_up_too(self):
        """The first upload was written into the listing, so the remote copy
        still reads as the one last seen."""
        self.put("notas.txt", "primera\n")
        self.up(changed=["notas.txt"], expect=fast.UP_OK)
        self.put("notas.txt", "segunda\n")
        self.up(changed=["notas.txt"], expect=fast.UP_OK)
        self.assertEqual(self.remote_text("notas.txt"), "segunda\n")

    def test_a_new_file_in_a_new_folder_is_uploaded(self):
        self.put("nueva/idea.md", "hola\n")
        self.up(changed=["nueva/idea.md"], expect=fast.UP_OK)
        self.assertEqual(self.remote_text("nueva/idea.md"), "hola\n")

    def test_nothing_is_sent_when_nothing_changed(self):
        self.up(changed=["notas.txt"], expect=fast.UP_OK)
        self.assertNotIn("FAST | uploaded", self.log())

    def test_the_full_pass_accepts_what_the_fast_lane_sent(self):
        """To bisync, a file the fast lane sent is a file already in sync:
        not a change on either side, let alone on both."""
        self.put("notas.txt", "editado\n")
        self.put("otro.txt", "nuevo\n")
        self.put("carpeta/nueva/honda/tres.txt", "tres\n")
        self.up(changed=["notas.txt", "otro.txt", "carpeta/nueva/honda/tres.txt"],
                expect=fast.UP_OK)
        self.engine()
        self.assertIn("No changes found", self.last_pass())
        self.assertNotIn("changed in both paths", self.last_pass())
        self.assertEqual(self.conflict_copies(), [])
        self.assertEqual(self.remote_text("otro.txt"), "nuevo\n")

    def test_a_file_edited_again_before_the_full_pass_is_not_a_conflict(self):
        """What happened on the author's machine the day this was installed
        (16-11-2026): the fast lane uploaded a file, the file was saved
        again, and the full pass that followed found it changed on both
        sides compared with a listing nobody had updated. It kept the newer
        one and announced a divergence between a document and itself."""
        self.put("notas.txt", "primer guardado\n")
        self.up(changed=["notas.txt"], expect=fast.UP_OK)
        self.put("notas.txt", "segundo guardado, más largo\n")
        self.engine()
        self.assertNotIn("changed in both paths", self.last_pass())
        self.assertNotIn("===== CONFLICT", self.log())
        self.assertEqual(self.conflict_copies(), [])
        self.assertEqual(self.remote_text("notas.txt"), "segundo guardado, más largo\n")

    def test_recording_an_upload_leaves_the_rest_of_the_listing_alone(self):
        before = {}
        for side in ("path1", "path2"):
            with open(os.path.join(
                    self.env["XDG_CACHE_HOME"], "rclone", "bisync",
                    fast.session_name(self.local, self.remote) + f".{side}.lst"),
                    encoding="utf-8") as f:
                before[side] = f.read().splitlines()
        self.put("b-nuevo.txt", "x\n")
        self.up(changed=["b-nuevo.txt"], expect=fast.UP_OK)
        for side in ("path1", "path2"):
            with open(os.path.join(
                    self.env["XDG_CACHE_HOME"], "rclone", "bisync",
                    fast.session_name(self.local, self.remote) + f".{side}.lst"),
                    encoding="utf-8") as f:
                after = f.read().splitlines()
            added = [line for line in after if line not in before[side]]
            self.assertEqual(len(added), 1, added)
            self.assertTrue(added[0].endswith('"b-nuevo.txt"'))
            self.assertEqual([line for line in after if line in before[side]], before[side])
            paths = [line.split('"', 1)[1] for line in after[1:]]
            self.assertEqual(paths, sorted(paths))

    def test_a_dry_run_says_what_it_would_send_and_sends_nothing(self):
        self.put("notas.txt", "editado\n")
        listfile = os.path.join(self.home, "changed.txt")
        with open(listfile, "w", encoding="utf-8") as f:
            f.write(os.path.join(self.local, "notas.txt") + "\n")
        res = subprocess.run(
            [sys.executable, "-B", FAST, "up", RCLONE, self.local, self.remote,
             "--state-dir", self.state, "--dry-run",
             "--filters", os.path.join(self.state, "filters-generated.txt"),
             "--filters-base", self.filters_base, "--changed", listfile],
            env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, fast.UP_OK, res.stderr)
        self.assertIn("would upload 1 file(s): notas.txt", res.stdout)
        self.assertEqual(self.remote_text("notas.txt"), "uno\n")
        self.assertEqual(self.listing("path2")[0]["notas.txt"][0], len("uno\n"))
        self.assertNotIn("FAST", self.log())

    # -- what it must never do --

    def test_a_secret_is_never_uploaded(self):
        self.put(".env", "TOKEN=x\n")
        self.put("proyecto/id_rsa", "clave\n")
        self.up(changed=[".env", "proyecto/id_rsa"], expect=fast.UP_OK)
        self.assertIsNone(self.remote_text(".env"))
        self.assertIsNone(self.remote_text("proyecto/id_rsa"))

    def test_a_repo_cloned_since_the_last_pass_is_never_uploaded(self):
        """It is not in the generated filters yet; the .git beside it is
        the evidence."""
        os.makedirs(os.path.join(self.local, "repo", ".git"))
        self.put("repo/src/main.py", "print()\n")
        self.up(changed=["repo/src/main.py"], expect=fast.UP_OK)
        self.assertIsNone(self.remote_text("repo/src/main.py"))

    def test_a_file_the_remote_changed_too_is_left_for_the_full_pass(self):
        with open(os.path.join(self.remote_dir, "notas.txt"), "w", encoding="utf-8") as f:
            f.write("editado en otra máquina\n")
        self.put("notas.txt", "editado acá\n")
        self.up(changed=["notas.txt"], expect=fast.UP_NEEDS_FULL)
        self.assertEqual(self.remote_text("notas.txt"), "editado en otra máquina\n")
        # ...and the full pass then treats it as the conflict it is.
        self.engine()
        self.assertEqual(len(set(self.conflict_copies())), 1)

    def test_a_new_file_that_already_exists_remotely_is_left_alone(self):
        with open(os.path.join(self.remote_dir, "choque.txt"), "w", encoding="utf-8") as f:
            f.write("de otra máquina\n")
        self.put("choque.txt", "de acá\n")
        self.up(changed=["choque.txt"], expect=fast.UP_NEEDS_FULL)
        self.assertEqual(self.remote_text("choque.txt"), "de otra máquina\n")

    def test_deleting_a_synced_file_asks_for_a_full_pass(self):
        os.unlink(os.path.join(self.local, "notas.txt"))
        self.up(gone=["notas.txt"], expect=fast.UP_NEEDS_FULL)
        self.assertEqual(self.remote_text("notas.txt"), "uno\n")

    def test_deleting_a_file_that_never_synced_asks_for_nothing(self):
        """The temporary file of an atomic save: created, renamed away."""
        self.up(gone=["notas.txt.tmp123"], expect=fast.UP_OK)

    def test_an_edited_filter_file_stands_the_lane_down(self):
        with open(self.filters_base, "a", encoding="utf-8") as f:
            f.write("- *.txt\n")
        self.put("notas.txt", "editado\n")
        self.up(changed=["notas.txt"], expect=fast.UP_NEEDS_FULL)
        self.assertEqual(self.remote_text("notas.txt"), "uno\n")
        self.assertIn("standing down", self.log())

    def test_a_failing_sync_stands_the_lane_down(self):
        with open(os.path.join(self.state, "consecutive-failures"), "w") as f:
            f.write("2\n")
        self.put("notas.txt", "editado\n")
        self.up(changed=["notas.txt"], expect=fast.UP_NEEDS_FULL)
        self.assertEqual(self.remote_text("notas.txt"), "uno\n")

    def test_it_waits_while_a_sync_holds_the_lock(self):
        with open(os.path.join(self.state, "loudsync.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.put("notas.txt", "editado\n")
            self.up(changed=["notas.txt"], expect=fast.UP_BUSY)
        self.assertEqual(self.remote_text("notas.txt"), "uno\n")

    def test_a_bulk_change_is_left_to_the_full_pass(self):
        names = [f"lote/{i}.txt" for i in range(30)]
        for name in names:
            self.put(name, "x\n")
        self.up(changed=names, expect=fast.UP_NEEDS_FULL)
        self.assertIsNone(self.remote_text("lote/0.txt"))

    # -- the probe, and --if-needed --

    def hit(self, name, size, modified, file_id="id1"):
        return {"id": file_id, "name": name, "size": str(size),
                "modifiedTime": modified, "createdTime": modified,
                "mimeType": "text/plain", "parents": ["p"]}

    def set_hits(self, hits):
        with open(self.fixture, "w", encoding="utf-8") as f:
            json.dump(hits, f)

    def test_probe_is_quiet_when_the_remote_is(self):
        self.set_hits([])
        self.assertEqual(self.probe(), fast.PROBE_NOTHING)

    def test_probe_reads_rclones_null_as_no_results(self):
        with open(self.fixture, "w", encoding="utf-8") as f:
            f.write("null\n")
        self.assertEqual(self.probe(), fast.PROBE_NOTHING)
        self.assertNotIn("failed unexpectedly", self.log())

    def test_probe_asks_since_the_last_good_pass_started(self):
        self.set_hits([])
        self.probe()
        with open(self.fixture + ".query", encoding="utf-8") as f:
            query = f.read()
        with open(os.path.join(self.state, "last-run-start"), encoding="utf-8") as f:
            started = int(f.read())
        since = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.gmtime(started - fast.PROBE_MARGIN_SECONDS))
        self.assertIn(f"modifiedTime > '{since}'", query)
        self.assertIn("trashed = false", query)

    def test_probe_ignores_what_the_sync_already_knows(self):
        files, _dirs = self.listing("path2")
        size, ms = files["notas.txt"]
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) \
            + f".{ms % 1000:03d}Z"
        self.set_hits([self.hit("notas.txt", size, stamp)])
        self.assertEqual(self.probe(), fast.PROBE_NOTHING)

    def test_probe_reports_a_file_it_cannot_explain(self):
        self.set_hits([self.hit("de-otra-maquina.txt", 99, "2026-11-16T17:44:39.528Z")])
        self.assertEqual(self.probe(), fast.PROBE_CHANGED)
        # Still unexplained until a full pass has run since.
        self.assertEqual(self.probe(), fast.PROBE_CHANGED)

    def test_probe_stops_reporting_once_a_pass_has_looked(self):
        """A change outside the synced folder matches nothing, ever. One pass
        over it is enough."""
        self.set_hits([self.hit("fuera-de-la-carpeta.txt", 99, "2026-11-16T17:44:39.528Z")])
        self.assertEqual(self.probe(), fast.PROBE_CHANGED)
        with open(os.path.join(self.state, "last-run-start"), "w") as f:
            f.write(str(int(time.time()) + 5))
        self.assertEqual(self.probe(), fast.PROBE_NOTHING)
        # The same file modified again is news again.
        self.set_hits([self.hit("fuera-de-la-carpeta.txt", 99, "2026-11-16T18:00:00.000Z")])
        self.assertEqual(self.probe(), fast.PROBE_CHANGED)

    def test_probe_without_an_answer_is_not_a_no(self):
        if os.path.exists(self.fixture):
            os.unlink(self.fixture)
        self.assertEqual(self.probe(), fast.PROBE_ERROR)

    def test_a_crash_never_reads_as_a_quiet_remote(self):
        """Python exits 1 on an uncaught error. No answer may share that
        code, and a broken state directory must end in a full pass."""
        self.assertNotIn(1, (fast.PROBE_NOTHING, fast.PROBE_UNSUPPORTED,
                             fast.PROBE_ERROR, fast.UP_NEEDS_FULL, fast.UP_BUSY))
        with open(os.path.join(self.state, "remote-info.json"), "w") as f:
            f.write("{}")
        os.chmod(self.state, 0o500)
        try:
            self.assertEqual(self.probe(), fast.PROBE_ERROR)
        finally:
            os.chmod(self.state, 0o700)
        self.write_conf(self.wrapper)
        self.set_hits([])
        before = self.passes()
        broken = dict(self.env, PYTHONPATH="/nonexistent", PROBE_FIXTURE="/nonexistent/x")
        subprocess.run([ENGINE, "--if-needed"], env=broken, capture_output=True)
        self.assertEqual(self.passes(), before)   # 22: no information, no pass

    def test_probe_declines_a_backend_it_does_not_know(self):
        res = subprocess.run(
            [sys.executable, "-B", FAST, "probe", RCLONE, self.local, self.remote,
             "--state-dir", self.state], env=self.env, capture_output=True)
        self.assertEqual(res.returncode, fast.PROBE_UNSUPPORTED)

    def passes(self):
        return self.log().count("===== START")

    def test_if_needed_skips_the_pass_when_nothing_changed(self):
        self.write_conf(self.wrapper)
        self.set_hits([])
        before = self.passes()
        self.engine("--if-needed")
        self.assertEqual(self.passes(), before)

    def test_if_needed_runs_when_the_remote_changed(self):
        self.write_conf(self.wrapper)
        self.set_hits([self.hit("de-otra-maquina.txt", 99, "2026-11-16T17:44:39.528Z")])
        before = self.passes()
        self.engine("--if-needed")
        self.assertEqual(self.passes(), before + 1)

    def test_if_needed_runs_when_asked_and_clears_the_request(self):
        self.write_conf(self.wrapper)
        self.set_hits([])
        marker = os.path.join(self.state, "sync-requested")
        open(marker, "w").close()
        before = self.passes()
        self.engine("--if-needed")
        self.assertEqual(self.passes(), before + 1)
        self.assertFalse(os.path.exists(marker))

    def test_if_needed_runs_once_the_interval_is_up(self):
        self.write_conf(self.wrapper, "FULL_SYNC_SECONDS=1\n")
        self.set_hits([])
        time.sleep(2)
        before = self.passes()
        self.engine("--if-needed")
        self.assertEqual(self.passes(), before + 1)

    def test_if_needed_always_runs_on_a_backend_without_a_probe(self):
        """Exactly what the timer did before the probe existed."""
        before = self.passes()
        self.engine("--if-needed")
        self.assertEqual(self.passes(), before + 1)

    def test_a_plain_run_always_syncs(self):
        self.write_conf(self.wrapper)
        self.set_hits([])
        before = self.passes()
        self.engine()
        self.assertEqual(self.passes(), before + 1)


FAKE_SYSTEMCTL = """#!/usr/bin/env bash
# Stands in for systemd: "start loudsync.service" runs the engine the way the
# unit would, in the background. The real systemctl is never reached.
echo "$*" >>"${HOME}/systemctl.calls"
case " $* " in
    *" start "*) "%s" --if-needed >/dev/null 2>&1 & ;;
esac
exit 0
"""


@unittest.skipUnless(RCLONE and shutil.which("inotifywait"),
                     "needs rclone and inotify-tools")
class WatcherEndToEnd(Sandbox, unittest.TestCase):
    """The watcher itself, running, with a stand-in for systemd."""

    def setUp(self):
        super().setUp()
        self.write_conf(self.wrapper, "WATCH_DEBOUNCE=1\nREMOTE_POLL_SECONDS=1\n"
                                      "FULL_SYNC_SECONDS=3600\n")
        self.set_hits([])
        fakebin = os.path.join(self.home, "fakebin")
        os.makedirs(fakebin)
        fake = os.path.join(fakebin, "systemctl")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_SYSTEMCTL % ENGINE)
        os.chmod(fake, 0o755)
        env = dict(self.env, PATH=fakebin + os.pathsep + self.env["PATH"])
        self.watcher = subprocess.Popen(
            [os.path.join(BIN, "loudsync-watch")], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        time.sleep(1.5)   # inotifywait needs a moment to set its watches

    def tearDown(self):
        try:
            os.killpg(self.watcher.pid, 15)
            self.watcher.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.5)   # let a pass started by the stand-in finish
        super().tearDown()

    def set_hits(self, hits):
        with open(self.fixture, "w", encoding="utf-8") as f:
            json.dump(hits, f)

    def wait_for(self, condition, seconds=25):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(0.25)
        return False

    def passes(self):
        return self.log().count("===== START")

    def save(self, rel, text):
        with open(os.path.join(self.local, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def test_a_saved_file_reaches_the_remote_without_a_full_pass(self):
        before = self.passes()
        self.save("notas.txt", "guardado recién\n")
        self.assertTrue(self.wait_for(
            lambda: self.remote_text("notas.txt") == "guardado recién\n"), self.log())
        self.assertEqual(self.passes(), before)

    def test_an_atomic_save_does_not_cost_a_full_pass(self):
        """Write to a temporary name, rename over the original: what most
        editors and office suites do."""
        before = self.passes()
        self.save("notas.txt.part", "versión nueva\n")
        os.replace(os.path.join(self.local, "notas.txt.part"),
                   os.path.join(self.local, "notas.txt"))
        self.assertTrue(self.wait_for(
            lambda: self.remote_text("notas.txt") == "versión nueva\n"), self.log())
        time.sleep(3)
        self.assertEqual(self.passes(), before)

    def test_a_deleted_file_is_deleted_remotely_by_a_full_pass(self):
        before = self.passes()
        os.unlink(os.path.join(self.local, "notas.txt"))
        self.assertTrue(self.wait_for(
            lambda: self.remote_text("notas.txt") is None), self.log())
        self.assertGreater(self.passes(), before)

    def test_a_remote_change_is_pulled_down(self):
        with open(os.path.join(self.remote_dir, "de-otra.txt"), "w", encoding="utf-8") as f:
            f.write("llegó\n")
        self.set_hits([{"id": "x1", "name": "de-otra.txt", "size": "7",
                        "modifiedTime": "2026-11-16T17:44:39.528Z"}])
        local_copy = os.path.join(self.local, "de-otra.txt")
        self.assertTrue(self.wait_for(lambda: os.path.exists(local_copy)), self.log())
        # ...and the files that pass wrote locally are not sent back up as
        # if somebody had edited them.
        time.sleep(4)
        self.assertNotIn("FAST | uploaded", self.log())

    def test_a_file_written_nonstop_does_not_hold_back_its_neighbour(self):
        stop = time.time() + 8
        self.save("carpeta/informe.txt", "el que importa\n")
        arrived = None
        while time.time() < stop:
            self.save("ruidoso.log", str(time.time()))
            if arrived is None and self.remote_text("carpeta/informe.txt") == "el que importa\n":
                arrived = time.time()
            time.sleep(0.2)
        self.assertIsNotNone(arrived, self.log())

    def test_a_hostile_file_name_is_only_a_file_name(self):
        name = "$(touch pwned) `touch pwned` a]b[c \"d\".txt"
        self.save(name, "inofensivo\n")
        self.assertTrue(self.wait_for(
            lambda: self.remote_text(name) == "inofensivo\n"), self.log())
        for where in (self.home, self.local, ROOT, os.getcwd()):
            self.assertFalse(os.path.exists(os.path.join(where, "pwned")))


if __name__ == "__main__":
    unittest.main()
