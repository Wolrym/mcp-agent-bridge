"""Design tokens: the one place the colours of the app are defined.

theme.qss refers to them as @name (gui.app substitutes the values when it
loads the sheet), and the widgets that paint themselves - switches, icons,
the backdrop glow, the window buttons - read them from here. Change a
colour once and both sides follow.

The look in three rules:
  * graphite surfaces, layered by lightness: shell < panel < controls;
  * controls catch the light from above - their top edge is brighter
    than the bottom one, which reads as a soft bevel instead of a flat box;
  * the orange of the icon is an accent, not a fill: the selected page in
    the sidebar, the focus ring of a text field. Nothing large is orange.
"""
from __future__ import annotations

COLORS = {
    # surfaces
    "shell": "#111113",          # title bar + sidebar
    "panel": "#0b0b0d",          # the content panel
    "edge": "#27272b",           # window border
    "panel_edge": "#1c1c1f",     # content panel border
    "surface": "#0f0f11",        # group cards
    "line": "#1e1e21",           # card borders
    "divider": "#19191c",        # rows inside a card
    "hover": "#19191c",
    "selected": "#222225",
    "selected_hi": "#313135",
    # text
    "text_strong": "#f5f5f6",
    "text": "#e4e4e7",
    "text_2": "#b6b6bc",
    "muted": "#8b8b92",
    "faint": "#5c5c63",
    # secondary buttons
    "btn_top": "#232326",
    "btn_bottom": "#1c1c1f",
    "btn_edge": "#2a2a2e",
    "btn_hi": "#424247",
    "btn_lo": "#1f1f22",
    "btn_top_hover": "#2a2a2e",
    "btn_bottom_hover": "#222225",
    "btn_hi_hover": "#535359",
    "btn_disabled": "#151517",
    "btn_disabled_edge": "#1f1f22",
    # primary buttons
    "prim_top": "#fafafa",
    "prim_bottom": "#e6e6e9",
    "prim_edge": "#d6d6da",
    "prim_hi": "#ffffff",
    "prim_lo": "#bdbdc3",
    "prim_text": "#111113",
    "prim_disabled": "#2b2b2f",
    "prim_disabled_text": "#75757c",
    # inputs
    "input": "#0e0e10",
    "input_edge": "#26262a",
    "input_hi": "#323237",
    "input_lo": "#1f1f22",
    "selection": "#3a3a40",
    "log": "#0c0c0e",
    # segmented control
    "seg_bg": "#131315",
    "seg_sel": "#26262a",
    "seg_sel_hi": "#404046",
    # accent
    "accent": "#e2612f",
    "accent_ring": "#a8502f",
    # status tones
    "success": "#4ade80",
    "success_text": "#9be8b6",
    "success_bg": "#0e1a13",
    "success_edge": "#1b3424",
    "warning": "#fbbf24",
    "warning_text": "#f5d27a",
    "warning_bg": "#1c170b",
    "warning_edge": "#382c11",
    "danger": "#f87171",
    "danger_text": "#f6a5a5",
    "danger_bg": "#1e1011",
    "danger_edge": "#3b1c1e",
    "danger_hover": "#2a1416",
    "neutral": "#6f6f77",
    "neutral_text": "#a1a1aa",
    "neutral_bg": "#151517",
    "neutral_edge": "#25252a",
    # window close button (hover)
    "win_close": "#c4372b",
    "win_close_hi": "#d4594e",
    # status pills
    "pill_bg": "#141416",
    "pill_edge": "#232327",
    "pill_hi": "#323237",
}

# The glow behind the top of the content panel: RGB, peak alpha (0-255).
GLOW_RGB = (226, 97, 47)
GLOW_ALPHA = 22

TONE_DOT = {
    "neutral": COLORS["neutral"],
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "danger": COLORS["danger"],
}


def apply(sheet: str) -> str:
    """Replace every @name in a stylesheet with its colour."""
    import re

    return re.sub(r"@([a-z_0-9]+)", lambda m: COLORS.get(m.group(1), m.group(0)), sheet)
