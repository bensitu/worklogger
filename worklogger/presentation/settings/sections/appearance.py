"""Appearance settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QPushButton,
    QVBoxLayout,
)

from worklogger.config.constants import (
    DARK_MODE_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.config.themes import THEME_DEFINITIONS
from worklogger.infrastructure.i18n import _, available_languages
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.background import BackgroundSettings
from worklogger.presentation.settings.sections.common import (
    _card_with_form,
    _add_half_width_row,
    _language_label,
    _secondary_label,
    _switch_line,
)
from worklogger.presentation.widgets import SwitchButton
from worklogger.presentation.settings.sections.layouts import SettingsContainer, SettingsScrollPage
from worklogger.presentation.widgets.icons import set_button_icon


class AppearanceSection(SettingsScrollPage):
    control_names = (
        "background_settings",
        "custom_color_button",
        "dark_switch",
        "language_combo",
        "minimal_switch",
        "minimal_view_row",
        "mode_combo",
        "theme_combo",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = _card_with_form(_("Appearance"))
        form = card.form_layout

        self.language_combo = QComboBox()
        self.language_combo.setObjectName("language_combo")
        for language in available_languages():
            self.language_combo.addItem(_language_label(language), language)
        self.language_combo.currentIndexChanged.connect(actions.language_changed)
        _add_half_width_row(form, _("Language"), self.language_combo)
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("theme_combo")
        for definition in THEME_DEFINITIONS:
            self.theme_combo.addItem(_(definition.label), definition.key)
        self.theme_combo.currentIndexChanged.connect(actions.theme_changed)
        self.custom_color_button = QPushButton()
        self.custom_color_button.setFixedSize(40, 40)
        self.custom_color_button.setToolTip(_("Palette"))
        self.custom_color_button.setAccessibleName(_("Palette"))
        set_button_icon(self.custom_color_button, "palette")
        self.custom_color_button.setObjectName("custom_color_button")
        self.custom_color_button.hide()
        self.custom_color_button.clicked.connect(actions.choose_custom_color)
        _add_half_width_row(form, _("Theme"), self.theme_combo, accessory=self.custom_color_button)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mode_combo")
        self.mode_combo.addItem(_("Light mode"), "light")
        self.mode_combo.addItem(_("Dark mode"), "dark")
        self.mode_combo.currentIndexChanged.connect(actions.mode_changed)
        _add_half_width_row(form, _("Mode"), self.mode_combo)

        self.dark_switch = SwitchButton()
        self.dark_switch.setVisible(False)
        self.dark_switch.toggled.connect(
            lambda enabled: actions.set_bool(DARK_MODE_SETTING_KEY, enabled)
        )
        self.minimal_switch = SwitchButton()
        self.minimal_switch.setAccessibleName(_("Minimal view"))
        self.minimal_switch.toggled.connect(
            lambda enabled: actions.set_bool(MINIMAL_MODE_SETTING_KEY, enabled)
        )
        self.minimal_view_row = SettingsContainer("minimal_view_option_widget")
        minimal_layout = QVBoxLayout(self.minimal_view_row)
        minimal_layout.setContentsMargins(0, 0, 0, 0)
        minimal_layout.setSpacing(6)
        minimal_layout.addWidget(_switch_line(_("Minimal view"), self.minimal_switch))
        minimal_layout.addWidget(_secondary_label(_("View changes apply after restarting or signing in again.")))
        form.addRow(self.minimal_view_row)
        page.layout().addWidget(card)
        self.background_settings = BackgroundSettings()
        page.layout().addWidget(self.background_settings)
        page.layout().addStretch(1)
