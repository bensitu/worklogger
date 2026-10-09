"""Appearance settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from worklogger.config.constants import (
    DARK_MODE_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.infrastructure.i18n import _, available_languages
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _card_with_form,
    _language_label,
    _SettingsScrollPage,
)
from worklogger.presentation.widgets import SwitchButton
from worklogger.presentation.widgets.icons import set_button_icon


class AppearanceSection(_SettingsScrollPage):
    control_names = (
        "custom_color_button",
        "dark_switch",
        "language_combo",
        "minimal_switch",
        "mode_combo",
        "theme_combo",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = _card_with_form(_("Appearance"))
        form = card.form_layout

        self.language_combo = QComboBox()
        self.language_combo.setFixedWidth(320)
        self.language_combo.setObjectName("language_combo")
        for language in available_languages():
            self.language_combo.addItem(_language_label(language), language)
        self.language_combo.currentIndexChanged.connect(actions.language_changed)
        form.addRow(_("Language"), self.language_combo)

        theme_row = QWidget()
        theme_row.setObjectName("settings_theme_row_widget")
        theme_layout = QHBoxLayout(theme_row)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.setSpacing(10)
        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(320)
        theme_row.setFixedWidth(370)
        self.theme_combo.setObjectName("theme_combo")
        for key, label in (
            ("blue", _("Blue")),
            ("pink", _("Pink")),
            ("green", _("Green")),
            ("purple", _("Purple")),
            ("custom", _("Custom")),
        ):
            self.theme_combo.addItem(label, key)
        self.theme_combo.currentIndexChanged.connect(actions.theme_changed)
        self.custom_color_button = QPushButton()
        self.custom_color_button.setFixedSize(40, 40)
        self.custom_color_button.setToolTip(_("Palette"))
        self.custom_color_button.setAccessibleName(_("Palette"))
        set_button_icon(self.custom_color_button, "palette")
        self.custom_color_button.setObjectName("custom_color_button")
        self.custom_color_button.hide()
        self.custom_color_button.clicked.connect(actions.choose_custom_color)
        theme_layout.addWidget(self.theme_combo, 1)
        theme_layout.addWidget(self.custom_color_button)
        theme_layout.addStretch()
        form.addRow(_("Theme"), theme_row)

        self.mode_combo = QComboBox()
        self.mode_combo.setFixedWidth(320)
        self.mode_combo.setObjectName("mode_combo")
        self.mode_combo.addItem(_("Light mode"), "light")
        self.mode_combo.addItem(_("Dark mode"), "dark")
        self.mode_combo.currentIndexChanged.connect(actions.mode_changed)
        form.addRow(_("Mode"), self.mode_combo)

        self.dark_switch = SwitchButton()
        self.dark_switch.setVisible(False)
        self.dark_switch.toggled.connect(
            lambda enabled: actions.set_bool(DARK_MODE_SETTING_KEY, enabled)
        )
        self.minimal_switch = SwitchButton()
        self.minimal_switch.setEnabled(False)
        self.minimal_switch.setVisible(False)
        self.minimal_switch.toggled.connect(
            lambda enabled: actions.set_bool(MINIMAL_MODE_SETTING_KEY, enabled)
        )
        page.layout().addWidget(card)
        page.layout().addStretch(1)
