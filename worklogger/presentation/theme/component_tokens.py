"""Shared control metrics and material-dependent component colors."""

from types import MappingProxyType

from worklogger.presentation.theme.materials import material_profile
from worklogger.presentation.theme.models import ColorPalette

CONTROL_METRICS = MappingProxyType({
    "control_radius": "8px",
    "panel_radius": "8px",
    "item_radius": "4px",
    "control_min_height": "28px",
    "control_padding_vertical": "5px",
})


def component_tokens(colors: ColorPalette) -> dict[str, str]:
    glass = material_profile(colors.material).translucent
    fill = _rgba(colors.input_background, 200) if glass else colors.surface
    border = _rgba(colors.border_strong, 115) if glass else colors.border
    hover = _rgba(colors.button_hover, 225) if glass else colors.button_hover
    return {
        **CONTROL_METRICS,
        "page_fill": "transparent" if glass else colors.surface,
        "canvas_fill": "transparent" if glass else colors.background,
        "card_fill": "transparent" if glass else colors.card,
        "card_hover_fill": "transparent" if glass else colors.card_hover,
        "panel_border": border,
        "sidebar_fill": "transparent" if glass else colors.sidebar_background,
        "navigation_fill": "transparent" if glass else colors.surface,
        "navigation_hover_fill": hover if glass else colors.surface_alt,
        "navigation_active_fill": colors.accent_dim if glass else colors.sidebar_active_background,
        "button_fill": fill,
        "button_border": border if glass else colors.border_strong,
        "button_hover_fill": hover,
        "input_fill": fill if glass else colors.input_background,
        "field_border": border if glass else colors.input_border,
        "readonly_fill": fill if glass else colors.surface_alt,
        "row_fill": fill,
        "row_border": border,
        "row_hover_fill": hover if glass else colors.card_hover,
        "record_selected_fill": colors.accent_dim if glass else colors.card_hover,
        "table_fill": colors.input_background if glass else colors.surface,
        "table_border": border,
        "header_fill": colors.input_background if glass else colors.surface_alt,
        "tab_fill": fill if glass else colors.surface,
        "tab_pane_fill": "transparent" if glass else colors.background,
        "tab_hover_fill": hover if glass else colors.card_hover,
        "editor_fill": fill if glass else colors.surface,
        "editor_pane_fill": "transparent" if glass else colors.surface,
    }


def _rgba(color: str, alpha: int) -> str:
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {alpha})"
