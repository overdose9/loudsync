# loudsync — desktop app design brief (v1)

Derived from `direccion-de-arte.md`. That document governs; this one is its condensed
input for screen generation.

## Product

loudsync is a Linux desktop app that backs up and two-way syncs one local folder with a
cloud drive (Google Drive, Dropbox, OneDrive…). It excludes git repositories and secret
files automatically, and it is loud when something breaks.

**Concept:** backs up and syncs your files with the certainty of a lookout who shouts
when something fails.

**Three words:** certain (every claim is backed by a timestamp or a real run; unknowns
are stated as unknown), calm (the normal state is one sentence and a time, nothing
else), frank and actionable (every problem says what happened, what it costs, and comes
with its button).

## Platform constraints (important)

- This is a **native Linux desktop window (GTK3)**, around 820×560 px, not a website.
  Mockups set layout, hierarchy and copy only.
- Surfaces, text colour, fonts and corner radii come from the user's system theme.
  Design in a **neutral dark theme** (window background #212121, list rows #2c2c2c,
  text #ffffff, accent blue #3281ea), system sans-serif font.
- Brand colour appears **only for sync state**: ok #5fcf8f, syncing #74aeff,
  paused #b3bac7, warning #ffa566, error #ff8f85 (dark-theme variants).
- Standard desktop widgets only: header bar, sidebar list, buttons, switches, spin
  buttons, dropdowns, list rows, expanders, info bars. No hero images, no marketing
  sections, no cards with drop shadows, no gradients.

## Layout

- Header bar with the window title "loudsync" and, on the right, a small spinner while
  syncing.
- Left sidebar (≈180 px) with five pages: Status, Conflicts (with a count when > 0),
  Activity, Settings, Filters.
- Content area on the right, max width ≈560 px, left-aligned, generous spacing on a
  6 px grid (6/12/18/24/36).
- Answer first, detail underneath: every page opens with one sentence that answers the
  question that brought you there. Technical output lives in a collapsed
  "Technical details" expander.

## Signature

The app icon is a cloud with three sound-wave arcs coming out of its side. In the status
page the state icon is 64 px: the cloud with the state glyph inside (check, sync arrows,
pause bars, warning triangle, error circle, gear for setup). The sound waves appear only
in alert states.

## Voice

English. Second person, short sentences, concrete verbs. Never minimise ("Sync is
failing", not "Something went wrong"); never alarm without cause.
