"""Colour and CSS. The theme owns everything except the state colours.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402

from . import icons  # noqa: E402

_CSS = """
@define-color loudsync_ok {ok};
@define-color loudsync_syncing {syncing};
@define-color loudsync_paused {paused};
@define-color loudsync_warning {warning};
@define-color loudsync_error {error};

.loudsync-alert {{
    border-left: 3px solid @loudsync_error;
    border-radius: 4px;
    padding: 12px 16px;
    background-color: alpha(@theme_fg_color, 0.05);
}}
.loudsync-alert.warning {{ border-left-color: @loudsync_warning; }}

.loudsync-badge {{
    border-radius: 9px;
    padding: 0 7px;
    background-color: @loudsync_warning;
    color: {badge_text};
    font-weight: bold;
}}

.loudsync-dot-ok {{ color: @loudsync_ok; }}
.loudsync-dot-syncing {{ color: @loudsync_syncing; }}
.loudsync-dot-paused {{ color: @loudsync_paused; }}
.loudsync-dot-warning {{ color: @loudsync_warning; }}
.loudsync-dot-error {{ color: @loudsync_error; }}

.loudsync-section {{
    font-weight: bold;
    font-size: smaller;
}}
.loudsync-step {{ padding: 6px 12px; }}
.loudsync-step-number {{ font-weight: bold; font-size: large; }}
.loudsync-sidebar row {{ padding: 8px 12px; }}
list.loudsync-rows row {{ padding: 10px 12px; }}
"""


def _luminance(rgba):
    def channel(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(rgba.red) + 0.7152 * channel(rgba.green) + 0.0722 * channel(rgba.blue)


class Style:
    """Picks the light or dark state colours from the theme's own background,
    and follows the theme when it changes."""

    def __init__(self):
        self.provider = Gtk.CssProvider()
        self.variant = "dark"
        self.listeners = []
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings = Gtk.Settings.get_default()
        for prop in ("gtk-theme-name", "gtk-application-prefer-dark-theme"):
            settings.connect(f"notify::{prop}", lambda *_a: self.apply())
        self.apply()

    def apply(self):
        probe = Gtk.Window()
        found, bg = probe.get_style_context().lookup_color("theme_bg_color")
        probe.destroy()
        self.variant = "dark" if (not found or _luminance(bg) < 0.4) else "light"
        colors = {tone: v[self.variant] for tone, v in icons.TONES.items()}
        badge_text = "#1d1d1d" if self.variant == "dark" else "#ffffff"
        self.provider.load_from_data(_CSS.format(badge_text=badge_text, **colors).encode())
        for callback in list(self.listeners):
            callback()

    def color(self, tone):
        return icons.TONES[tone][self.variant]

    def state_surface(self, headline, size, widget):
        """The window's big state icon, sharp on HiDPI screens."""
        scale = widget.get_scale_factor()
        text = icons.svg(headline.glyph, headline.loud, self.color(headline.tone))
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.set_size(size * scale, size * scale)
        loader.write(text.encode())
        loader.close()
        return Gdk.cairo_surface_create_from_pixbuf(loader.get_pixbuf(), scale, None)
