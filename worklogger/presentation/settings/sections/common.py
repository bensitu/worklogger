"""Shared settings section controls."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from worklogger.config.constants import (
    ENABLE_MENU_BAR_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
)
from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets import CardFrame, SwitchButton


class _SettingsScrollPage(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("settings_scroll_widget")
        self.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.content_widget.setObjectName("settings_scroll_content_widget")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(16)
        self.setWidget(self.content_widget)

    def layout(self) -> QVBoxLayout:
        return self.content_layout


def _card_with_form(title: str) -> CardFrame:
    card = CardFrame(object_name="settings_content_frame")
    form = _settings_form()
    card.content_layout.addLayout(form)
    card.form_layout = form
    return card


def _settings_form() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(8)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    return form


def _action_card(title: str, description: str) -> CardFrame:
    card = CardFrame(object_name="settings_content_frame")
    card.content_layout.addWidget(_section_title(title))
    if description:
        card.content_layout.addWidget(_secondary_label(description))
    return card


def _add_action_buttons(
    card: CardFrame, *buttons: QPushButton, columns: int = 1
) -> None:
    row = QGridLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    for index, button in enumerate(buttons):
        row.addWidget(button, index // columns, index % columns)
        row.setColumnStretch(index % columns, 1)
    card.content_layout.addLayout(row)


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settings_section_title_label")
    return label


def _secondary_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settings_secondary_label")
    label.setProperty("role", "secondary")
    label.setWordWrap(True)
    return label


def _switch_line(label: str, switch: SwitchButton) -> QWidget:
    row = QWidget()
    row.setObjectName("settings_switch_row_widget")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    text = QLabel(label)
    text.setWordWrap(True)
    layout.addWidget(text, 1)
    layout.addStretch(1)
    layout.addWidget(switch)
    return row


def _switch_row(switch: SwitchButton) -> QWidget:
    row = QWidget()
    row.setObjectName("settings_switch_row_widget")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(switch)
    layout.addStretch(1)
    return row


def _hours_input(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(2)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setMinimumWidth(120)
    spin.setFixedWidth(320)
    return spin


def _readonly_line_edit(object_name: str) -> QLineEdit:
    line_edit = QLineEdit()
    line_edit.setObjectName(object_name)
    line_edit.setReadOnly(True)
    return line_edit


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("settings_separator_frame")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


def _text_line_edit(object_name: str) -> QLineEdit:
    line_edit = QLineEdit()
    line_edit.setObjectName(object_name)
    return line_edit


def _connect_text(line_edit: QLineEdit, callback: object) -> None:
    line_edit.editingFinished.connect(callback)


def _language_label(language: str) -> str:
    labels = {
        "en_US": _("English", language="en_US"),
        "ja_JP": _("Japanese", language="ja_JP"),
        "ko_KR": _("Korean", language="ko_KR"),
        "zh_CN": _("Simplified Chinese", language="zh_CN"),
        "zh_TW": _("Traditional Chinese", language="zh_TW"),
    }
    return labels.get(language, language)


def _residency_setting_key() -> str | None:
    if sys.platform.startswith("win"):
        return ENABLE_TRAY_SETTING_KEY
    if sys.platform == "darwin":
        return ENABLE_MENU_BAR_SETTING_KEY
    return None
