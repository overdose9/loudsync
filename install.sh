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
DATADIR="${XDG_DATA_HOME:-${HOME}/.local/share}"
SHAREDIR="${DATADIR}/loudsync"
APPDIR="${DATADIR}/applications"
ICONDIR="${DATADIR}/icons/hicolor/scalable/apps"
AUTOSTART="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/loudsync-gui.desktop"

UNITS=(loudsync.service loudsync.timer loudsync-watch.service)

say()  { printf '  %s\n' "$*"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# Menus and docks look icons up through a cache when the icon directory has
# one, and don't see a new icon until it is rebuilt.
refresh_desktop_caches() {
    if [ -f "${DATADIR}/icons/hicolor/icon-theme.cache" ] && command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t -q "${DATADIR}/icons/hicolor" || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q "${APPDIR}" 2>/dev/null || true
    fi
}

# --- Uninstall --------------------------------------------------------------

if [ "${1:-}" = "--uninstall" ]; then
    head_ "Removing loudsync"
    systemctl --user disable --now loudsync.timer loudsync-watch.service 2>/dev/null || true
    for u in "${UNITS[@]}"; do
        rm -f "${UNITDIR}/${u}" && say "removed ${u}"
    done
    systemctl --user daemon-reload
    rm -f "${BINDIR}/loudsync" "${BINDIR}/loudsync-watch" "${BINDIR}/loudsync-rename" \
          "${BINDIR}/loudsync-fast" "${BINDIR}/loudsync-gui"
    say "removed binaries from ${BINDIR}"
    rm -rf "${SHAREDIR}"
    rm -f "${APPDIR}/loudsync.desktop" "${ICONDIR}"/loudsync.svg "${ICONDIR}"/loudsync-*.svg "${AUTOSTART}"
    refresh_desktop_caches
    say "removed the desktop interface, its menu entry and its login autostart"
    say "(if its tray icon is still showing, choose Quit in its menu)"
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
    say "python3: MISSING — needed by the fast lane and by --propagate-rename"
    MISSING=1
fi

if command -v inotifywait >/dev/null 2>&1; then
    say "inotify-tools: found"
else
    say "inotify-tools: not found (optional)"
    say "        Without it, a file you save waits for the next full pass"
    say "        instead of uploading within seconds. Install with your package"
    say "        manager, e.g. apt install inotify-tools"
fi

if command -v notify-send >/dev/null 2>&1; then
    say "notify-send: found"
else
    say "notify-send: not found (optional) — no desktop alerts without it"
fi

# The desktop interface is optional: the sync runs under systemd without it.
HAVE_GUI=0
if python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' \
        >/dev/null 2>&1; then
    HAVE_GUI=1
    say "GTK 3 for Python: found (desktop interface)"
else
    say "GTK 3 for Python: not found (optional) — no tray icon or window without it"
    say "        e.g. apt install python3-gi gir1.2-gtk-3.0"
fi

if [ "${MISSING}" -eq 1 ]; then
    echo
    say "Install the missing pieces above and run this again."
    exit 1
fi

# --- Files ------------------------------------------------------------------

head_ "Installing"

mkdir -p "${BINDIR}" "${CONFIG_HOME}" "${STATE_HOME}" "${UNITDIR}"

for f in loudsync loudsync-watch loudsync-rename loudsync-fast loudsync-gui; do
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

# The desktop interface, and the shipped templates its setup assistant copies
# from. Replaced whole on every install, so a module removed upstream doesn't
# linger and get imported.
rm -rf "${SHAREDIR}/gui"
mkdir -p "${SHAREDIR}/gui/loudsync_gui" "${SHAREDIR}/gui/icons" "${APPDIR}" "${ICONDIR}"
install -m 644 "${SRC}"/gui/loudsync_gui/*.py "${SHAREDIR}/gui/loudsync_gui/"
install -m 644 "${SRC}"/gui/icons/*.svg "${SHAREDIR}/gui/icons/"
install -m 644 "${SRC}/config/loudsync.conf.example" "${SRC}/config/filters-base.txt" "${SHAREDIR}/"
# All of them in the icon theme, not just the app icon: the panel only draws
# a symbolic tray icon when it can find it by name.
install -m 644 "${SRC}"/gui/icons/*.svg "${ICONDIR}/"
sed "s|@BINDIR@|${BINDIR}|g" "${SRC}/gui/loudsync.desktop" >"${APPDIR}/loudsync.desktop"
say "${APPDIR}/loudsync.desktop"
refresh_desktop_caches

# Start the tray icon with the session, unless you already decided: an
# existing entry, on or off, is yours and is left alone.
if [ "${HAVE_GUI}" -eq 1 ] && [ ! -e "${AUTOSTART}" ]; then
    mkdir -p "$(dirname "${AUTOSTART}")"
    cat >"${AUTOSTART}" <<AUTOSTART_EOF
[Desktop Entry]
Type=Application
Name=loudsync
Comment=Tray icon for loudsync: shows whether your files are syncing
Exec=${BINDIR}/loudsync-gui --background
Icon=loudsync
Terminal=false
X-GNOME-Autostart-enabled=true
Hidden=false
AUTOSTART_EOF
    say "${AUTOSTART}  (tray icon at login; turn it off in its Settings)"
fi

# --- What to do next --------------------------------------------------------

head_ "Next steps"

if ! printf '%s' ":${PATH}:" | grep -q ":${BINDIR}:"; then
    say "WARNING: ${BINDIR} is not on your PATH."
    say "  Add this to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo
fi

if [ "${NEW_CONFIG}" -eq 1 ] && [ "${HAVE_GUI}" -eq 1 ]; then
    say "Open loudsync from your applications menu (or run: loudsync-gui)."
    say "Its setup assistant picks the folder, connects your cloud account,"
    say "previews the first sync and turns on the automation."
    echo
    say "Prefer the terminal? These are the same steps:"
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
    say "  systemctl --user restart loudsync.timer loudsync-watch.service"
fi

echo
say "Check state any time with:  loudsync --status"
echo
