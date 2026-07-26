#!/usr/bin/env bash
#
# Installs loudsync for the current user. No root, no sudo, nothing outside
# your home directory.
#
#   ./install.sh              install or upgrade
#   ./install.sh --uninstall  remove everything except your data and logs
#
# Copyright (C) 2026 Sebastián Flores
# Licensed under the GNU General Public License v3.0 or later.

set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BINDIR="${HOME}/.local/bin"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}/loudsync"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}/loudsync"
UNITDIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"

UNITS=(loudsync.service loudsync.timer loudsync-watch.service)

say()  { printf '  %s\n' "$*"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- Uninstall --------------------------------------------------------------

if [ "${1:-}" = "--uninstall" ]; then
    head_ "Removing loudsync"
    systemctl --user disable --now loudsync.timer loudsync-watch.service 2>/dev/null || true
    for u in "${UNITS[@]}"; do
        rm -f "${UNITDIR}/${u}" && say "removed ${u}"
    done
    systemctl --user daemon-reload
    rm -f "${BINDIR}/loudsync" "${BINDIR}/loudsync-watch" "${BINDIR}/loudsync-rename"
    say "removed binaries from ${BINDIR}"
    echo
    say "Your config is still at ${CONFIG_HOME}"
    say "Your logs and versions are still at ${STATE_HOME}"
    say "Nothing was deleted from your synced folder or your remote."
    exit 0
fi

# --- Dependencies -----------------------------------------------------------

head_ "Checking dependencies"

MISSING=0

if command -v rclone >/dev/null 2>&1 || [ -x "${HOME}/.local/bin/rclone" ]; then
    say "rclone: found"
else
    say "rclone: MISSING — install it from https://rclone.org/install/"
    say "        (a user-space install works fine: it is a single binary)"
    MISSING=1
fi

if command -v python3 >/dev/null 2>&1; then
    say "python3: found"
else
    say "python3: MISSING — needed by --propagate-rename"
    MISSING=1
fi

if command -v inotifywait >/dev/null 2>&1; then
    say "inotify-tools: found"
else
    say "inotify-tools: not found (optional)"
    say "        Without it, local changes wait for the one-minute timer"
    say "        instead of syncing within seconds. Install with your package"
    say "        manager, e.g. apt install inotify-tools"
fi

if command -v notify-send >/dev/null 2>&1; then
    say "notify-send: found"
else
    say "notify-send: not found (optional) — no desktop alerts without it"
fi

if [ "${MISSING}" -eq 1 ]; then
    echo
    say "Install the missing pieces above and run this again."
    exit 1
fi

# --- Files ------------------------------------------------------------------

head_ "Installing"

mkdir -p "${BINDIR}" "${CONFIG_HOME}" "${STATE_HOME}" "${UNITDIR}"

for f in loudsync loudsync-watch loudsync-rename; do
    install -m 755 "${SRC}/bin/${f}" "${BINDIR}/${f}"
    say "${BINDIR}/${f}"
done

# The filter file is yours to edit, so never overwrite an existing one.
if [ -f "${CONFIG_HOME}/filters-base.txt" ]; then
    say "kept your existing filters-base.txt"
    if ! cmp -s "${SRC}/config/filters-base.txt" "${CONFIG_HOME}/filters-base.txt"; then
        cp "${SRC}/config/filters-base.txt" "${CONFIG_HOME}/filters-base.txt.new"
        say "new defaults saved as filters-base.txt.new — diff them if you like"
    fi
else
    install -m 644 "${SRC}/config/filters-base.txt" "${CONFIG_HOME}/filters-base.txt"
    say "${CONFIG_HOME}/filters-base.txt"
fi

NEW_CONFIG=0
if [ -f "${CONFIG_HOME}/loudsync.conf" ]; then
    say "kept your existing loudsync.conf"
else
    install -m 600 "${SRC}/config/loudsync.conf.example" "${CONFIG_HOME}/loudsync.conf"
    say "${CONFIG_HOME}/loudsync.conf  (edit this before starting)"
    NEW_CONFIG=1
fi

for u in "${UNITS[@]}"; do
    sed "s|@BINDIR@|${BINDIR}|g" "${SRC}/systemd/${u}" >"${UNITDIR}/${u}"
    say "${UNITDIR}/${u}"
done

systemctl --user daemon-reload

# --- What to do next --------------------------------------------------------

head_ "Next steps"

if ! printf '%s' ":${PATH}:" | grep -q ":${BINDIR}:"; then
    say "WARNING: ${BINDIR} is not on your PATH."
    say "  Add this to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo
fi

if [ "${NEW_CONFIG}" -eq 1 ]; then
    say "1. Set up your remote, if you haven't:   rclone config"
    say "2. Edit ${CONFIG_HOME}/loudsync.conf"
    say "   (at minimum LOCAL_DIR and REMOTE)"
    say "3. Review ${CONFIG_HOME}/filters-base.txt"
    say "4. First run, which builds the sync state:"
    say "     loudsync --resync"
    say "5. Once that succeeds, turn on the automation:"
    say "     systemctl --user enable --now loudsync.timer loudsync-watch.service"
else
    say "Upgraded. Restart the services to pick up the new version:"
    say "  systemctl --user restart loudsync-watch.service"
fi

echo
say "Check state any time with:  loudsync --status"
echo
