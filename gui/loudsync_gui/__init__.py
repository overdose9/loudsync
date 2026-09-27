"""loudsync's desktop interface: a tray icon and a window over the engine.

Copyright (C) 2026 Sebastián Flores
Licensed under the GNU General Public License v3.0 or later.
"""

import gettext
import os

APP_ID = "io.github.overdose9.loudsync"

# Every string a person reads goes through gettext, so a translation is one
# .mo file under locale/, not a rewrite.
_translation = gettext.translation(
    "loudsync", localedir=os.path.join(os.path.dirname(__file__), "locale"), fallback=True)
_ = _translation.gettext
ngettext = _translation.ngettext
