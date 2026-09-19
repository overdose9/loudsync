# loudsync

**Two-way folder sync that knows what a git repo is, refuses to upload your
secrets, and shouts when it breaks.**

Built on [rclone](https://rclone.org), so it works with Google Drive, Dropbox,
OneDrive, S3, Nextcloud and the 70-odd other backends rclone supports.

---

## Why this exists

The author's previous backup job was dead for a month before anyone noticed. It
pointed at a binary that had never been installed, and it failed quietly every
single night. A backup that fails silently is worse than no backup at all,
because it sells you confidence you haven't earned.

So the first rule here is: **be loud**. If syncing stops, you find out from a
desktop notification within three minutes, and the message tells you what to do
about it.

The other two rules come from what actually goes wrong when you point a sync
tool at a folder where you do real work.

## What makes it different

**1. Git repositories are excluded automatically.**

Every run scans for `.git` directories and excludes those trees. Nothing to
configure, nothing to remember — clone a new repo and it's excluded on the next
run.

This matters more than it sounds. Two-way syncing a `.git/` directory corrupts
the index and the object store when both sides write, or when an upload is cut
off halfway. And `node_modules/` will happily eat your storage quota and your
API rate limit. Your repos already have a backup: the remote you push to.

**2. Secrets are excluded before the first upload, not after the incident.**

The shipped filter file blocks `.env` files, private keys, certificates,
service-account JSON, `.netrc`, `.pgpass`, VPN configs and database dumps.
There's also an `_secrets/` escape-hatch folder that never leaves the machine.

Note the honest limitation: **this filters by file name, not by content.** A
password pasted inside a `.docx` still gets uploaded. The filters buy you the
common cases, not absolution. What you store in your files is exclusively your
responsibility.

**3. It fails loudly, and safely.**

- Desktop notification after 3 consecutive failures, then one reminder an hour,
  so a real problem never becomes background noise.
- An all-clear notification when it recovers — an alarm with no all-clear
  trains people to ignore alarms.
- Being offline doesn't count as a failure. It's a laptop.
- A safety brake aborts the run if it would delete more than half of either
  side.
- **Conflicts are announced.** See below — this is the case where being quiet
  costs the most.

## Conflicts are not silent

A sync tool resolving a conflict quietly is the same failure as a backup dying
quietly, one level up. rclone handles it competently: it keeps the newer
version, renames the loser, copies it across, and exits 0. Nothing you will
ever see. The first you hear of it is a file with a strange suffix in your
folder, days later, next to a copy of your document that is missing the last
paragraph you wrote.

So every conflict is written to the log with the file, which side won, by how
much, and where the other version is — and it raises a desktop notification.

It also says which kind of conflict it is, because the two kinds need
completely different things from you:

**One file racing itself.** You saved while a run was in flight. The run
records in its listing the version it *saw*, then uploads the version it
*reads* a second later, so on the next pass both sides look changed although
only one machine ever touched the file. The winner is decided by a gap of
seconds — effectively a coin toss. Nothing is lost, but the copy left behind is
noise, and noise you don't understand is how you learn to ignore notifications.

**A real divergence.** Two machines, or one machine and a stale copy. Only you
can say which version counts.

loudsync tells them apart on evidence rather than a guess: it remembers which
files were still being written while the previous run was uploading them, and
it reads the time gap between the two versions. It also counts only conflicts
that actually happened: rclone flags a file as "changed in both paths" before
comparing the two versions, and when they turn out identical it renames
nothing. Only a renamed loser is reported. A race gets a plain
notification. A divergence gets a critical one, and `loudsync --status` lists
every conflict copy still sitting in your folder waiting for a decision.

Prevention comes first, though: **a run does not start while the folder is
being written to.** If any file that would be synced changed in the last
`QUIET_SECONDS` (15 by default), the run is postponed — and never more than
`MAX_QUIET_SKIPS` times in a row, because something writing constantly must not
be able to stop your backups. `loudsync --now` skips the wait.

That reduces the race, it doesn't abolish it: a save landing after a run starts
still races. What it removes is the common case, which is the run that fires
while you are typing.

## Status

**v0.4.0 — early.** Daily-driven by the author on Linux Mint against Google
Drive, roughly 800 files. It has not been tested at large scale, across many
providers, or by anyone else yet.

This tool moves your data in both directions. Read what the safety brakes do
before you point it at something irreplaceable, and keep a backup that isn't
this.

## Requirements

| | |
|---|---|
| `rclone` | required — a single binary, a user-space install is fine |
| `bash`, `python3` | required |
| `systemd` (user session) | required for the automation |
| `inotify-tools` | optional — without it, uploads wait for the timer |
| `notify-send` | optional — no desktop alerts without it |

## Install

```sh
git clone https://github.com/overdose9/loudsync.git
cd loudsync
./install.sh
```

Everything lands under your home directory. No root, no sudo, nothing touched
system-wide.

Then:

```sh
rclone config                  # set up your remote, if you haven't
$EDITOR ~/.config/loudsync/loudsync.conf
loudsync --resync              # first run: builds the sync state
systemctl --user enable --now loudsync.timer loudsync-watch.service
```

To remove it: `./install.sh --uninstall`. Your config, logs and data stay.

## Configure

`~/.config/loudsync/loudsync.conf`. Only two settings are required:

```sh
LOCAL_DIR="~/Documents"
REMOTE="gdrive:LoudSync"
```

Everything else has a sensible default —
see [`config/loudsync.conf.example`](config/loudsync.conf.example), which
documents each option and why it's set the way it is.

Extra exclusions go in `~/.config/loudsync/filters-base.txt`, using
[rclone filter syntax](https://rclone.org/filtering/). Git repos are handled
separately and merged in automatically, so never list a repo there.

## Use

```sh
loudsync                     # one run (this is what systemd calls)
loudsync --status            # where things stand, and any conflict left to settle
loudsync --dry-run           # show what would happen, change nothing
loudsync --now               # don't wait for the folder to go quiet
loudsync --resync            # rebuild sync state
loudsync --propagate-rename  # you renamed a folder that contains a repo
```

Any other flag is passed straight through to `rclone bisync`.

Logs: `~/.local/state/loudsync/loudsync.log`, rotated once it passes
`LOG_MAX_MB` (50 by default), with the previous generations kept next to it
as `loudsync.log.1`, `.2`, `.3`.

## How it works

Two triggers, because they solve different halves of the problem:

- **A watcher** (`inotify`) fires a few seconds after you change a local file,
  which is what makes uploads feel instant. Bursts are debounced, so saving 20
  files is one sync.
- **A one-minute timer** pulls changes down from the remote. Most providers
  don't notify third-party clients, so the only way to know is to ask.

Both run through the same lock, so they can never overlap. The timer is
`Persistent=true`: if the machine was off, it syncs on boot rather than waiting
for its turn.

Under the hood it's `rclone bisync` with conflict resolution set to
newest-wins. The loser is kept alongside the winner with a `.conflict-local` or
`.conflict-remote` suffix rather than being thrown away, and you get told about
it.

Files overwritten by a change coming *down* from the remote are copied to
`~/.local/state/loudsync/versions/<date>/` first. That's the one case your
provider's own version history doesn't cover: the file that got overwritten is
your local one. The remote side is deliberately not versioned, since most
providers already keep revisions and a trash bin.

## The rename problem

This is the sharp edge, and it's worth understanding before it bites you.

`rclone bisync` doesn't understand renames. It sees N deletions on one side and
N creations on the other. Usually that resolves fine on its own.

But renaming a folder that *contains a git repo* changes the generated
exclusion list, and bisync stores a hash of its filter file and aborts when it
changes — a different filter could make it read an exclusion as a mass
deletion.

Running `--resync` at that point is the wrong move: it pulls the old-named
folder back down from the remote and leaves you holding both copies.

So loudsync does it in the right order, by itself. It compares both sides,
matches files by MD5 and size, and **only when the match is exactly one to
one** does it treat the pair as a rename. It renames on the remote server-side
(no data transfer), writes a script that reverses exactly what it did, and only
then reconciles. Anything ambiguous is reported and left alone. You get a
notification saying what moved and where the undo script is.

It stops and asks for you in two cases: when the plan is larger than 50 moves,
and when one side lists no files at all — that isn't a rename, it's a broken
mount or an expired token. Then you run `loudsync --propagate-rename`, which is
the same machinery with the plan printed and a confirmation prompt.

This used to always stop and wait for a human. That was the wrong trade. What
the stop avoided is a nuisance: `--resync` unions both sides, so a file you
deleted on purpose since the last run can come back. That now gets counted in
the notification, so it can't pass unnoticed. What the stop cost is unbounded:
a backup sitting dead until somebody happens to read a notification, which is
the exact failure this tool exists to prevent.

Note the limitation this buys. loudsync follows your local folder. If a rename
was a mistake — yours, or another tool's — it reaches the remote within
seconds, and the remote will match the mistake. The undo script reverses it
exactly and the notification says where it is, but nothing here second-guesses
the move itself. What you do on your own machine and your own remote is your
responsibility; this tool makes the two agree, it doesn't judge which one is
right.

New repos need none of this: if the exclusion list only *grew*, loudsync
reconciles without even comparing, because excluding a folder deletes nothing
on the other side.

## What it deliberately does not do

- **No GUI.** Not yet. Possibly later.
- **No one-way / backup-only mode.** It's a two-way sync.
- **No remote-side versioning.** Your provider already does that; duplicating
  it burns quota and grows a dated folder nobody prunes.
- **No blind resync when a path disappears.** The rename gets propagated to the
  remote first, or you end up with duplicated folders.
- **No content scanning for secrets.** Filenames only. See the honest
  limitation above.

## Troubleshooting

**"the sync stopped and needs a decision"** — you renamed or moved a folder
containing a repo, and the resulting plan was too large to apply unattended (or
one side listed nothing at all). Run `loudsync --propagate-rename` in a
terminal to see the plan and approve it. Smaller renames are handled without
you; the log shows what was moved.

**"a file changed on both sides"** — open both copies: the winner, and the one
next to it ending in `.conflict-local` or `.conflict-remote`. The log says
which side won and by how much. If the gap was seconds, it is almost certainly
the same file saved while a sync was running, and the copy is redundant. Delete
whichever one you don't want; `loudsync --status` lists the ones still pending.

**"Sync blocked by files you don't own"** — someone uploaded files straight
into the shared remote folder, so they belong to that account, and no other
account can delete or trash them: the provider answers 403 and bisync aborts
on every run. It happens the moment you delete or move the local folder that
held them. `loudsync --status` lists the files. Remove them from the folder in
your provider's web interface (they stay in their owner's drive), or ask the
owner to delete them; the next run then finishes on its own, no `--resync`
needed. To find such files before they bite, with Google Drive:
`rclone lsjson -R --files-only -M --drive-metadata-permissions read <remote>`
and look at `Metadata.owner`.

**Syncs are being postponed** — something is writing into the folder
continuously. The log names the file. If it's something you don't need synced
at all (a database, a log, a cache), exclude it in `filters-base.txt`; the
exclusion also stops it from postponing runs. `QUIET_SECONDS=0` disables the
wait entirely.

**Nothing is being uploaded within seconds** — the watcher likely isn't
running, or `inotify-tools` isn't installed. Check with
`systemctl --user status loudsync-watch.service`.

**Something isn't syncing at all** — check whether a filter catches it before
suspecting the sync: `grep -n <name> ~/.config/loudsync/filters-base.txt`, and
remember that anything inside a git repo is excluded by design.

**Everything looks wrong** — `loudsync --resync` rebuilds the sync state
without deleting anything. If you renamed something, use `--propagate-rename`
instead.

## Contributing

Issues and pull requests are welcome. This is a small tool with strong opinions
about safety; changes that make it quieter or more clever about deleting things
are the ones most likely to be turned down.

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
