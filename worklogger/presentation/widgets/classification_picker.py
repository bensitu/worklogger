"""Anchored classification selection with an isolated, validated draft."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from worklogger.domain.projects.models import WorkContext
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import CustomEntryType, CustomWorkMode, EntryCategory, EntryType, WorkMode, WorkModeValue
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.entry_type_options import add_entry_type_option, add_work_mode_option
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.work_context_picker import WorkContextPicker


class ClassificationButton(QPushButton):
    """Fixed-height summary that retains complete accessible text when elided."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("classification_button")
        self.setProperty("variant", "outline")
        self.setAccessibleName(_("Classification"))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self._lines = ()
        set_button_icon(self, "chevron-down")
        self.set_summary("")

    def set_summary(self, primary, secondary=""):
        self._lines = tuple(line for line in (primary, secondary) if line)
        text = "\n".join(self._lines)
        self.setToolTip(text)
        self.setAccessibleDescription(text)
        self._fit_text()

    def _fit_text(self):
        metrics = self.fontMetrics()
        self.setFixedHeight(2 * metrics.lineSpacing() + 4)
        available = max(0, self.width() - self.iconSize().width() - 48)
        self.setText("\n".join(metrics.elidedText(line, Qt.TextElideMode.ElideRight, available)
                               for line in self._lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, "_lines"):
            self._fit_text()


class ClassificationPicker(QFrame):
    selection_applied = Signal(object)

    def __init__(self, parent=None, *, validator: Callable[
            [str, WorkModeValue | None, WorkContext],
            Result[tuple[EntryType | CustomEntryType, WorkModeValue | None, WorkContext]]]):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("classification_popup_frame")
        self.setAccessibleName(_("Classification"))
        self._validator = validator
        self._anchor = None
        self._watched = []
        self._definitions = {}
        self._accepting = False
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        heading = QLabel(_("Classification"))
        heading.setProperty("role", "heading")
        root.addWidget(heading)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_widget = QWidget()
        self.content_widget.setObjectName("classification_picker_content_widget")
        content = QVBoxLayout(self.content_widget)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(8)
        self.section_tabs = QTabWidget()
        self.section_tabs.setObjectName("classification_section_tab_widget")
        self.section_tabs.tabBar().setProperty("tab_style", "underline")
        self.section_tabs.tabBar().setExpanding(True)
        self.section_tabs.setDocumentMode(True)
        work = QWidget()
        work.setObjectName("classification_work_page_widget")
        work_layout = QVBoxLayout(work)
        work_layout.setContentsMargins(0, 8, 0, 0)
        work_layout.setSpacing(8)
        self.period_type_combo = self._combo("period_type_combo")
        self._add_field(work_layout, _("Period type"), self.period_type_combo)
        self.work_metadata = QWidget()
        self.work_metadata.setObjectName("classification_work_metadata_widget")
        metadata = QVBoxLayout(self.work_metadata)
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(8)
        self.work_mode_combo = self._combo("work_mode_combo")
        for mode in (None, *WorkMode):
            add_work_mode_option(self.work_mode_combo, mode)
        self._add_field(metadata, _("Work arrangement"), self.work_mode_combo)
        self.context_picker = WorkContextPicker(vertical=True)
        metadata.addWidget(self.context_picker)
        work_layout.addWidget(self.work_metadata)
        self.legacy_label = self._message(_("Legacy classification"))
        work_layout.addWidget(self.legacy_label)
        self.auto_help_label = self._message(_("Enter leave in Manual Input."))
        work_layout.addWidget(self.auto_help_label)
        work_layout.addStretch()
        leave = QWidget()
        leave.setObjectName("classification_leave_page_widget")
        leave_layout = QVBoxLayout(leave)
        leave_layout.setContentsMargins(0, 8, 0, 0)
        self.leave_type_combo = self._combo("leave_type_combo")
        self._add_field(leave_layout, _("Leave type"), self.leave_type_combo)
        leave_layout.addStretch()
        self.section_tabs.addTab(work, _("Work"))
        self.section_tabs.addTab(leave, _("Leave"))
        content.addWidget(self.section_tabs)
        scroll.setWidget(self.content_widget)
        root.addWidget(scroll, 1)
        self.error_label = self._message("")
        self.error_label.setObjectName("classification_error_label")
        self.error_label.setProperty("role", "error")
        self.error_label.hide()
        root.addWidget(self.error_label)
        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_button = QPushButton(_("Cancel"))
        self.cancel_button.setObjectName("classification_cancel_button")
        self.apply_button = QPushButton(_("Apply"))
        self.apply_button.setObjectName("classification_apply_button")
        self.apply_button.setProperty("variant", "primary")
        set_button_icon(self.apply_button, "check")
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.apply_button)
        root.addLayout(footer)
        self.cancel_button.clicked.connect(self.hide)
        self.apply_button.clicked.connect(self._apply)
        self.period_type_combo.currentIndexChanged.connect(self._period_changed)
        self.section_tabs.currentChanged.connect(self._selection_changed)
        self.leave_type_combo.currentIndexChanged.connect(self._selection_changed)
        self.work_mode_combo.currentIndexChanged.connect(self._selection_changed)
        self.context_picker.changed.connect(self._selection_changed)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self.hide)

    @staticmethod
    def _combo(name):
        combo = QComboBox()
        combo.setObjectName(name)
        combo.setMinimumWidth(0)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        return combo

    @staticmethod
    def _message(text):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setProperty("role", "secondary")
        return label

    @staticmethod
    def _add_field(layout, text, combo):
        column = QVBoxLayout()
        column.setSpacing(3)
        caption = QLabel(text)
        caption.setBuddy(combo)
        caption.setWordWrap(True)
        combo.setAccessibleName(text)
        column.addWidget(caption)
        column.addWidget(combo)
        layout.addLayout(column)

    def open_for(self, anchor, *, definition, work_mode, context, custom_types=(), custom_modes=(),
                 inventory=((), {}), recent=(), automatic=False, projects_available=True,
                 context_available=True, recent_context_visible=True, preserve_work_mode=True):
        self.hide()
        self._anchor = anchor
        self._definitions = {item.value: item for item in (
            EntryType.NORMAL, EntryType.MEETING, EntryType.TRAINING, EntryType.OTHER,
            EntryType.BREAK, EntryType.PAID_LEAVE, EntryType.COMP_LEAVE, EntryType.SICK_LEAVE,
            *(item for item in custom_types if not item.archived),
        )}
        # The selected historical snapshot takes precedence over today's catalog.
        self._definitions[definition.value] = definition
        self.period_type_combo.clear()
        self.leave_type_combo.clear()
        for category in (EntryCategory.WORK, EntryCategory.BREAK, EntryCategory.LEAVE):
            combo = self.leave_type_combo if category == EntryCategory.LEAVE else self.period_type_combo
            if category == EntryCategory.BREAK:
                combo.insertSeparator(combo.count())
            for item in self._definitions.values():
                if item.category != category:
                    continue
                add_entry_type_option(combo, item)
        self.period_type_combo.setCurrentIndex(max(0, self.period_type_combo.findData(definition.value)))
        self.leave_type_combo.setCurrentIndex(max(0, self.leave_type_combo.findData(definition.value)))
        modes = {item.value: item for item in (*WorkMode, *(item for item in custom_modes if not item.archived))}
        if work_mode is not None and (preserve_work_mode or not isinstance(work_mode, CustomWorkMode)):
            modes[work_mode.value] = work_mode
        self.work_mode_combo.clear()
        add_work_mode_option(self.work_mode_combo, None)
        for mode in modes.values():
            add_work_mode_option(self.work_mode_combo, mode)
        selected_mode = modes.get(work_mode.value) if work_mode is not None else None
        selected_key = selected_mode.value if selected_mode is not None else None
        self.work_mode_combo.setCurrentIndex(next((index for index in range(self.work_mode_combo.count())
            if getattr(self.work_mode_combo.itemData(index), "value", self.work_mode_combo.itemData(index)) == selected_key), 0))
        self.context_picker.set_context(WorkContext())
        self.context_picker.set_inventory(*inventory)
        self.context_picker.set_context(context)
        self.context_picker.set_recent(recent)
        self.context_picker.recent_button.setVisible(recent_context_visible)
        self.context_picker.setVisible(projects_available)
        self.context_picker.setEnabled(context_available)
        self.section_tabs.setTabEnabled(1, not automatic)
        self.section_tabs.setTabToolTip(1, _("Enter leave in Manual Input.") if automatic else "")
        self.section_tabs.setCurrentIndex(1 if definition.category == EntryCategory.LEAVE and not automatic else 0)
        self.auto_help_label.setVisible(automatic)
        self.error_label.hide()
        self._period_changed()
        self.ensurePolished()
        for widget in self.findChildren(QWidget):
            widget.ensurePolished()
        self._position_popup()
        ancestor = anchor
        while ancestor is not None:
            ancestor.installEventFilter(self)
            self._watched.append(ancestor)
            ancestor = ancestor.parentWidget()
        self.show()
        self._position_popup()
        (self.leave_type_combo if self.section_tabs.currentIndex() == 1 else self.period_type_combo).setFocus(
            Qt.FocusReason.PopupFocusReason)

    def _period_changed(self, *_args):
        definition = self._definitions.get(self.period_type_combo.currentData())
        self.work_metadata.setVisible(definition is not None and definition.category == EntryCategory.WORK)
        self.legacy_label.setVisible(isinstance(definition, EntryType) and definition.is_legacy)
        self._selection_changed()

    def _selection_changed(self, *_args):
        self.error_label.hide()
        for combo in (self.period_type_combo, self.leave_type_combo, self.work_mode_combo):
            combo.setToolTip(combo.currentText())

    def _apply(self):
        if not self.isVisible() or self._accepting:
            return
        combo = self.leave_type_combo if self.section_tabs.currentIndex() == 1 else self.period_type_combo
        definition = self._definitions.get(combo.currentData())
        if definition is None:
            return
        work = definition.category == EntryCategory.WORK
        result = self._validator(definition.value, self.work_mode_combo.currentData() if work else None,
                                 self.context_picker.context() if work else WorkContext())
        if result.ok and self._type_identity(result.value[0]) != self._type_identity(definition):
            result = Result.failure(ValidationError("entry_type_unavailable", "entry_type_unavailable"))
        selected_mode = self.work_mode_combo.currentData()
        if (work and result.ok and isinstance(selected_mode, CustomWorkMode)
                and (getattr(result.value[1], "value", None), getattr(result.value[1], "label", None)) != (selected_mode.value, selected_mode.label)):
            result = Result.failure(ValidationError("work_mode_unavailable", "work_mode_unavailable"))
        if not result.ok:
            self.error_label.setText(display_error_message(result.error))
            self.error_label.show()
            self.error_label.setAccessibleName(self.error_label.text())
            return
        self._accepting = True
        try:
            self.selection_applied.emit(result.value)
            self.hide()
        finally:
            self._accepting = False

    @staticmethod
    def _type_identity(definition):
        return (definition.value, definition.category,
                definition.label if isinstance(definition, CustomEntryType) else "")

    def _position_popup(self):
        anchor = self._anchor
        point = anchor.mapToGlobal(QPoint(anchor.width() // 2, anchor.height() // 2))
        screen = QGuiApplication.screenAt(point) or anchor.screen()
        bounds = screen.availableGeometry()
        width = min(360, bounds.width())
        height = min(max(390, self.content_widget.sizeHint().height() + 112), bounds.height())
        self.resize(width, height)
        bottom = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height()))
        x = max(bounds.left(), min(bottom.x() - width, bounds.right() - width + 1))
        y = bottom.y() + 4
        if y + height > bounds.bottom() + 1:
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - height - 4
        self.move(x, max(bounds.top(), min(y, bounds.bottom() - height + 1)))

    def eventFilter(self, watched, event):
        if self.isVisible() and event.type() in (
            QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.Move, QEvent.Type.Resize,
            QEvent.Type.EnabledChange, QEvent.Type.StyleChange,
            QEvent.Type.LanguageChange,
        ):
            self.hide()
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        for widget in self._watched:
            widget.removeEventFilter(self)
        self._watched.clear()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply()
            event.accept()
        else:
            super().keyPressEvent(event)
