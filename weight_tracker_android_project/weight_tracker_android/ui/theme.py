"""Shared color tokens and Chinese font registration. Import before creating widgets."""

from pathlib import Path

from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.utils import get_color_from_hex

from services.performance import mark

from services.android_bridge import ANDROID_AVAILABLE

APP_DIR = Path(__file__).resolve().parent.parent
FONT_DIR = APP_DIR / "fonts"
_font_registration_started = __import__("time").perf_counter()
# Prefer a preinstalled Android CJK font where available. The bundled fallback
# is a 16.4 MB TTF; opening it during module import can add noticeable cold-start
# cost even on devices whose system fonts already support Chinese.
FONT_CANDIDATES = []
if ANDROID_AVAILABLE:
    FONT_CANDIDATES.extend([
        Path("/system/fonts/NotoSansCJK-Regular.ttc"),
        Path("/system/fonts/NotoSansCJKsc-Regular.otf"),
        Path("/system/fonts/NotoSansSC-Regular.otf"),
    ])
FONT_CANDIDATES.extend([FONT_DIR / "NotoSansCJKsc-Regular.ttf", FONT_DIR / "NotoSansCJKsc-Regular.otf"])

FONT_NAME = "Roboto"
FONT_REGULAR = None
for _font in FONT_CANDIDATES:
    if not _font.exists():
        continue
    try:
        LabelBase.register(
            "NotoSansSC", fn_regular=str(_font), fn_italic=str(_font),
            fn_bold=str(_font), fn_bolditalic=str(_font),
        )
        FONT_NAME = "NotoSansSC"
        FONT_REGULAR = _font
        break
    except Exception:
        continue

mark("font_registration_complete", _font_registration_started,
     selected_font=FONT_NAME, source=FONT_REGULAR or "system-default")

# Apply the selected font to all common Kivy controls before the UI is built.
Builder.load_string(f'''
<Label>:
    font_name: "{FONT_NAME}"
<Button>:
    font_name: "{FONT_NAME}"
<TextInput>:
    font_name: "{FONT_NAME}"
<Spinner>:
    font_name: "{FONT_NAME}"
<SpinnerOption>:
    font_name: "{FONT_NAME}"
<Popup>:
    title_font: "{FONT_NAME}"
''')

# Fitness theme: one coral primary accent, mint only for completed workouts/success states.
BG = get_color_from_hex("#101016")
CARD = get_color_from_hex("#1B1A22")
CARD_ALT = get_color_from_hex("#25232D")
CARD_DARK = get_color_from_hex("#17161D")
SURFACE = get_color_from_hex("#2D2B36")
SURFACE_DOWN = get_color_from_hex("#3A3744")
PRIMARY = get_color_from_hex("#FF626B")
PRIMARY_DARK = get_color_from_hex("#E94E5B")
TEXT = get_color_from_hex("#F7F5FA")
MUTED = get_color_from_hex("#A39EAF")
GREEN = get_color_from_hex("#B8F28B")
GREEN_DARK = get_color_from_hex("#364A32")
# Compatibility alias used by existing feature code; kept in the coral family.
PURPLE = get_color_from_hex("#FF858C")
LINE_COLOR = get_color_from_hex("#383541")
WHITE = get_color_from_hex("#FFFFFF")
FIELD_BG = get_color_from_hex("#272530")
DISABLED_SURFACE = get_color_from_hex("#211F28")

# Shared component measurements (dp). Keep these tokens in one place so that
# later visual adjustments do not require hunting through every screen.
PAGE_GUTTER = 12
SECTION_GAP = 10
CARD_RADIUS = 18
CONTROL_RADIUS = 14
TILE_RADIUS = 10
MIN_TAP_HEIGHT = 44
