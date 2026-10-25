"""Shared settings section controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets import CardFrame, SwitchButton
from worklogger.presentation.widgets.numeric_input import apply_numeric_input_padding
from worklogger.presentation.settings.sections.layouts import (
    FIELD_SPACING, SECTION_SPACING, HalfWidthFieldRow, SettingsActionGroup, SettingsContainer,
)


def _card_with_form(title: str) -> CardFrame:
    card = _action_card(title)
    form = _settings_form()
    card.content_layout.addLayout(form)
    card.form_layout = form
    return card


def _settings_form() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(FIELD_SPACING)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    return form


def _action_card(title: str, description: str = "") -> CardFrame:
    card = CardFrame(object_name="settings_content_frame")
    card.content_layout.addWidget(_section_title(title))
    if description:
        card.content_layout.addWidget(_secondary_label(description))
    return card


def _add_action_buttons(
    card: CardFrame | SettingsContainer, *buttons: QPushButton, columns: int = 1
) -> None:
    card.content_layout.addWidget(SettingsActionGroup(buttons, columns=columns))


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settings_section_title_label")
    label.setProperty("role", "section_heading")
    label.setWordWrap(True)
    return label


def _secondary_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settings_secondary_label")
    label.setProperty("role", "secondary")
    label.setWordWrap(True)
    return label


def _control_line(label: str, control: QWidget) -> QWidget:
    row = SettingsContainer("settings_control_row_widget")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SECTION_SPACING)
    text = QLabel(label)
    text.setWordWrap(True)
    text.setBuddy(control)
    layout.addWidget(text, 1)
    layout.addWidget(control)
    return row


def _switch_line(label: str, switch: SwitchButton) -> QWidget:
    return _control_line(label, switch)


def _hours_input(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setKeyboardTracking(False)
    apply_numeric_input_padding(spin)
    spin.setDecimals(2)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setMinimumWidth(120)
    spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return spin


def _add_half_width_row(form: QFormLayout, label: str, field: QWidget, *, accessory: QWidget | None = None) -> QWidget:
    row = HalfWidthFieldRow(field, accessory)
    form.addRow(label, row)
    form.labelForField(row).setBuddy(field)
    return row


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
