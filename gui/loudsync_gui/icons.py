"""The signature icon: a cloud with the state's glyph cut into it, and sound
waves coming off its side when there is something to hear about.

Drawn from code rather than kept as hand-edited files, so the tray icons, the
window's state icon and the app icon can't drift apart. Fill only, no strokes:
GTK recolours the fills of a symbolic icon to match the panel, and would leave
a stroke in whatever colour it was drawn.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import math
import os

# Colours per tone. "light"/"dark" are the art direction's pairs, picked by
# the window background; "tray" sits on a panel of unknown colour and is a
# middle tone that holds 3:1 on both a dark and a light panel.
TONES = {
    "ok":      {"light": "#1b6e45", "dark": "#5fcf8f", "tray": "#2e9b5f"},
    "syncing": {"light": "#1a5bb0", "dark": "#74aeff", "tray": "#3a7fd8"},
    "paused":  {"light": "#565d6b", "dark": "#b3bac7", "tray": "#848b98"},
    "warning": {"light": "#9a4300", "dark": "#ffa566", "tray": "#c96f00"},
    "error":   {"light": "#b0241b", "dark": "#ff8f85", "tray": "#e5372e"},
}

SYMBOLIC_GREY = "#bebebe"   # the colour GTK replaces in a symbolic icon

# The cloud: three circles joined into one outline, on a 16×16 grid. Left
# lobe centre (4.5,10) r3, top (8,7.5) r4.2, right (12,10) r3. The arc end
# points are where the circles meet.
_CLOUD = ("M4.5,13 A3,3 0 0 1 3.822,7.078 A4.2,4.2 0 0 1 12.171,7.005 "
          "A3,3 0 0 1 12,13 Z")

# Glyphs, cut out of the cloud with the even-odd rule. Each one is a single
# closed outline so no part of it overlaps another (an overlap would cut the
# hole back out).
_GLYPHS = {
    "ok": "M5.1,9.4 L6.2,8.3 L7.4,9.5 L10.1,6.8 L11.2,7.9 L7.4,11.7 Z",
    "sync": ("M6.3,11.6 L6.3,8.6 L5.1,8.6 L6.8,6.4 L8.5,8.6 L7.3,8.6 L7.3,11.6 Z "
             "M8.9,6.4 L9.9,6.4 L9.9,9.4 L11.1,9.4 L9.4,11.6 L7.7,9.4 L8.9,9.4 Z"),
    "pause": ("M6.3,6.6 L7.6,6.6 L7.6,11.4 L6.3,11.4 Z "
              "M8.9,6.6 L10.2,6.6 L10.2,11.4 L8.9,11.4 Z"),
    "warning": ("M7.55,5.9 L8.95,5.9 L8.75,9.6 L7.75,9.6 Z "
                "M7.55,10.4 L8.95,10.4 L8.95,11.8 L7.55,11.8 Z"),
    "error": ("M7.55,5.9 L8.95,5.9 L8.75,9.6 L7.75,9.6 Z "
              "M7.55,10.4 L8.95,10.4 L8.95,11.8 L7.55,11.8 Z"),
    "setup": ("M7.6,6.3 L8.9,6.3 L8.9,8.35 L10.95,8.35 L10.95,9.65 L8.9,9.65 "
              "L8.9,11.7 L7.6,11.7 L7.6,9.65 L5.55,9.65 L5.55,8.35 L7.6,8.35 Z"),
    "none": "",
}


def _band(cx, cy, radius, width, half_angle):
    """One sound wave: a slice of a ring, opening to the right."""
    ro, ri = radius + width / 2, radius - width / 2
    a = math.radians(half_angle)
    pt = lambda r, s: (cx + r * math.cos(s * a), cy + r * math.sin(s * a))  # noqa: E731
    (x1, y1), (x2, y2) = pt(ro, -1), pt(ro, 1)
    (x3, y3), (x4, y4) = pt(ri, 1), pt(ri, -1)
    return (f"M{x1:.3f},{y1:.3f} A{ro:.3f},{ro:.3f} 0 0 1 {x2:.3f},{y2:.3f} "
            f"L{x3:.3f},{y3:.3f} A{ri:.3f},{ri:.3f} 0 0 0 {x4:.3f},{y4:.3f} Z")


def svg(glyph, loud, color):
    """The icon as SVG text. `loud` shrinks the cloud to the left and adds
    two waves on the right: the lookout shouting."""
    body = f'<path fill-rule="evenodd" d="{_CLOUD} {_GLYPHS[glyph]}"/>'
    if loud:
        # Scaled around its left edge so the waves get the right third.
        body = f'<g transform="translate(-0.2,1.5) scale(0.78)">{body}</g>'
        waves = "".join(
            f'<path d="{_band(10.6, 8.4, r, 1.15, 38)}"/>' for r in (2.3, 4.2))
        body += waves
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
            f'viewBox="0 0 16 16"><g fill="{color}">{body}</g></svg>')


def _arc(cx, cy, r, half_angle):
    a = math.radians(half_angle)
    x1, y1 = cx + r * math.cos(-a), cy + r * math.sin(-a)
    x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a)
    return f"M{x1:.1f},{y1:.1f} A{r},{r} 0 0 1 {x2:.1f},{y2:.1f}"


# "Noche", chosen by the operator on 27-09-2026 over "Aurora" and "Alerta":
# the lookout keeping watch at night. Calm sky and a white cloud with the
# check of a finished sync; the shout comes out of it in warm amber.
_NIGHT_STARS = ((52, 58, 2.2, .5), (84, 40, 1.4, .35), (198, 52, 1.8, .4),
                (220, 88, 1.2, .3), (40, 206, 1.4, .25))


def app_icon():
    """The application icon, 256 px: menus, the window, notifications.

    Unlike the tray icons it is full colour, with depth: it is the one place
    the brand is shown rather than a state. It still uses the same cloud and
    the same waves, so the two read as one family.
    """
    waves = "".join(
        f'<path d="{_arc(150, 131, r, 42)}" stroke="url(#w)" stroke-width="15" '
        f'stroke-linecap="round" fill="none" opacity="{o}"/>'
        for r, o in ((30, 1), (51, .85), (72, .6)))
    stars = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity="{o}"/>'
                    for x, y, r, o in _NIGHT_STARS)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<defs>
<linearGradient id="t" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22347a"/><stop offset="1" stop-color="#0a1030"/></linearGradient>
<linearGradient id="c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#c9dcff"/></linearGradient>
<linearGradient id="w" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffc24a"/><stop offset="1" stop-color="#ff5a36"/></linearGradient>
<radialGradient id="g" cx="0.72" cy="0.55" r="0.5"><stop offset="0" stop-color="#ff8a3c" stop-opacity="0.45"/><stop offset="1" stop-color="#ff8a3c" stop-opacity="0"/></radialGradient>
<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.16"/><stop offset="0.5" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="blur" x="-20%" y="-20%" width="140%" height="160%"><feGaussianBlur stdDeviation="7"/></filter>
<clipPath id="clip"><rect x="8" y="8" width="240" height="240" rx="56"/></clipPath>
</defs>
<rect x="8" y="8" width="240" height="240" rx="56" fill="url(#t)"/>
<g clip-path="url(#clip)">
<rect x="8" y="8" width="240" height="240" fill="url(#g)"/>
{stars}
<g transform="translate(15,59) scale(9.2)"><path d="{_CLOUD}" fill="#000" opacity="0.35" filter="url(#blur)" transform="translate(0.25,0.55)"/></g>
{waves}
<g transform="translate(15,50) scale(9.2)"><path d="{_CLOUD}" fill="url(#c)"/><path d="{_GLYPHS["ok"]}" fill="#1a3a8a"/></g>
</g>
<rect x="8" y="8" width="240" height="240" rx="56" fill="url(#sheen)"/>
<rect x="9" y="9" width="238" height="238" rx="55" fill="none" stroke="#fff" stroke-opacity="0.10" stroke-width="2"/>
</svg>
'''


# --- Tray names ----------------------------------------------------------------
#
# Calm states are symbolic: the panel colours them like every other icon there,
# because a healthy sync has nothing to say. Alerts are drawn in colour: the
# shout is literal.

def tray_name(headline):
    if headline.loud or headline.tone in ("warning", "error"):
        return f"loudsync-{headline.state}"
    return f"loudsync-{headline.state}-symbolic"


def tray_icons():
    """{file name: svg text} for every tray state, plus the app icon."""
    from . import describe
    files = {"loudsync.svg": app_icon()}
    for state, (glyph, tone, loud) in describe._LOOK.items():
        fake = describe.Headline(state, glyph, tone, loud, "", "")
        name = tray_name(fake)
        color = TONES[tone]["tray"] if name.endswith(state) else SYMBOLIC_GREY
        files[name + ".svg"] = svg(glyph, loud, color)
    assert len(files) == len(describe._LOOK) + 1, "two states share a tray icon name"
    return files


def write_tray_icons(directory):
    os.makedirs(directory, exist_ok=True)
    for name, text in tray_icons().items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    # Regenerate the shipped icons: python3 -m loudsync_gui.icons ../icons
    import sys
    write_tray_icons(sys.argv[1])
