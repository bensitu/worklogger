"""Opt-in rendering checks for enabled and disabled control states."""

from dataclasses import replace
from datetime import date
from itertools import product
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDoubleSpinBox,
    QGridLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMenu, QPlainTextEdit, QRadioButton,
    QScrollBar, QSlider, QSpinBox, QStyle, QStyleOptionButton, QStyleOptionComboBox, QStyleOptionFrame,
    QStyleOptionHeader, QStyleOptionMenuItem,
    QStyleOptionSlider, QStyleOptionSpinBox, QTabBar, QTableView, QTextEdit, QTimeEdit, QTreeWidget, QTreeWidgetItem, QWidget,
)

from worklogger.presentation.theme import THEME_KEYS, ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.widgets.calendar import CalendarDayButton
from worklogger.presentation.widgets.date_picker import MonthCalendar
from worklogger.presentation.widgets.icons import IconLabel
from worklogger.presentation.widgets.report_history import ReportHistoryButton, ReportHistoryDisplayItem
from worklogger.presentation.widgets.record_summary import RecordSummaryButton
from worklogger.presentation.widgets.switch_button import SwitchButton
from worklogger.presentation.widgets.preview_list import PreviewItemDelegate


class ControlStateChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def setUp(self):
        self.old_style, self.old_palette = self.app.styleSheet(), self.app.palette()
        self.old_context = self.app.property("worklogger_theme_context")
        self.engine = ThemeEngine()

    def tearDown(self):
        self.app.setStyleSheet(self.old_style)
        self.app.setPalette(self.old_palette)
        self.app.setProperty("worklogger_theme_context", self.old_context)

    def test_hover_feedback_preserves_focus_disabled_states_and_control_geometry(self):
        controls = ((QLineEdit, QStyleOptionFrame, QStyle.PrimitiveElement.PE_PanelLineEdit),
                    (QCheckBox, QStyleOptionButton, QStyle.ControlElement.CE_CheckBox),
                    (QRadioButton, QStyleOptionButton, QStyle.ControlElement.CE_RadioButton),
                    (QHeaderView, QStyleOptionHeader, QStyle.ControlElement.CE_HeaderSection),
                    (QComboBox, QStyleOptionComboBox, QStyle.ComplexControl.CC_ComboBox),
                    (QDoubleSpinBox, QStyleOptionSpinBox, QStyle.ComplexControl.CC_SpinBox),
                    (QSlider, QStyleOptionSlider, QStyle.ComplexControl.CC_Slider),
                    (QScrollBar, QStyleOptionSlider, QStyle.ComplexControl.CC_ScrollBar),
                    (lambda: QScrollBar(Qt.Orientation.Horizontal), QStyleOptionSlider,
                     QStyle.ComplexControl.CC_ScrollBar))
        for theme, dark in product(THEME_KEYS, (False, True)):
            self.engine.apply_to(self.app, theme, dark=dark, custom_color="#168078")
            for factory, option_type, element in controls:
                field = factory(Qt.Orientation.Horizontal) if factory is QHeaderView else factory()
                if isinstance(field, QHeaderView):
                    field.setSectionsClickable(True)
                if isinstance(field, QComboBox):
                    field.addItem("Selection")
                elif isinstance(field, (QCheckBox, QRadioButton)):
                    field.setText("Option")
                if type(field) is QSlider:
                    field.setOrientation(Qt.Orientation.Horizontal)
                control_name = type(field).__name__
                if isinstance(field, QScrollBar):
                    control_name += "-" + field.orientation().name
                    if field.orientation() == Qt.Orientation.Horizontal:
                        field.resize(240, 16)
                    else:
                        field.resize(16, 200)
                else:
                    field.resize(240, 44)
                field.ensurePolished()
                def render(hovered, focused=False):
                    option = option_type()
                    field.initStyleOption(option)
                    if isinstance(field, QSlider):
                        option.subControls = QStyle.SubControl.SC_SliderGroove | QStyle.SubControl.SC_SliderHandle
                    elif isinstance(field, QScrollBar):
                        option.subControls = QStyle.SubControl.SC_All
                        slider = field.style().subControlRect(element, option, QStyle.SubControl.SC_ScrollBarSlider, field)
                        for part in (QStyle.SubControl.SC_ScrollBarAddLine, QStyle.SubControl.SC_ScrollBarSubLine):
                            button = field.style().subControlRect(element, option, part, field)
                            self.assertFalse(slider.intersects(button), (theme, dark, control_name))
                    option.state &= ~(QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_HasFocus)
                    if hovered:
                        option.state |= QStyle.StateFlag.State_MouseOver
                        if isinstance(field, QSlider):
                            option.activeSubControls = QStyle.SubControl.SC_SliderHandle
                        elif isinstance(field, QScrollBar):
                            option.activeSubControls = QStyle.SubControl.SC_ScrollBarSlider
                    if focused:
                        option.state |= QStyle.StateFlag.State_HasFocus
                    image = QImage(field.size(), QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    try:
                        if isinstance(field, QLineEdit):
                            field.style().drawPrimitive(element, option, painter, field)
                        elif isinstance(field, (QCheckBox, QRadioButton)):
                            field.style().drawControl(element, option, painter, field)
                        elif isinstance(field, QHeaderView):
                            field.style().drawControl(element, option, painter, field)
                        else:
                            field.style().drawComplexControl(element, option, painter, field)
                    finally:
                        painter.end()
                    return image
                try:
                    geometry, font = field.geometry(), field.font()
                    normal, hovered = render(False), render(True)
                    self.assertNotEqual(normal, hovered, (theme, dark, control_name))
                    self.capture(normal, f"{theme}-{dark}-{control_name}-normal")
                    self.capture(hovered, f"{theme}-{dark}-{control_name}-hover")
                    if isinstance(field, QLineEdit):
                        self.assertEqual(render(False, True), render(True, True))
                        field.setReadOnly(True)
                        self.assertEqual(render(False), render(True))
                    field.setEnabled(False)
                    self.assertEqual(render(False), render(True), (theme, dark, control_name))
                    self.assertEqual((field.geometry(), field.font()), (geometry, font))
                finally:
                    field.deleteLater()

    def test_calendar_hover_preserves_selected_dates_and_clears_on_leave_or_disable(self):
        for theme, dark in product(THEME_KEYS, (False, True)):
            colors = self.engine.apply_to(self.app, theme, dark=dark, custom_color="#168078")
            calendar = MonthCalendar()
            calendar.setSelectedDate(QDate(2026, 10, 16))
            calendar.resize(380, 300)
            calendar.show()
            self.app.processEvents()
            viewport = calendar.findChild(QTableView).viewport()
            try:
                rect = calendar._cell_rects[date(2026, 10, 17)]
                def sample(bounds):
                    image = viewport.grab().toImage().scaled(viewport.size())
                    return image.pixelColor(bounds.topLeft() + QPoint(4, 4)).name()
                point = rect.center()
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                                    Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
                self.app.sendEvent(viewport, event)
                self.app.processEvents()
                self.assertEqual(sample(rect), colors.accent_dim)
                self.assertEqual(calendar.selectedDate(), QDate(2026, 10, 16))
                self.capture(calendar, f"{theme}-{dark}-calendar-hover")
                self.app.sendEvent(viewport, QEvent(QEvent.Type.Leave))
                self.app.processEvents()
                self.assertEqual(sample(rect), colors.surface)
                calendar.setEnabled(False)
                self.app.processEvents()
                self.app.sendEvent(viewport, event)
                self.app.processEvents()
                self.assertEqual(sample(rect), colors.disabled_background)
                self.assertEqual(calendar.selectedDate(), QDate(2026, 10, 16))
                self.capture(calendar, f"{theme}-{dark}-calendar-disabled")
            finally:
                calendar.close()
                calendar.deleteLater()

    def test_input_fields_preserve_geometry_and_mute_disabled_text_and_background(self):
        factories = (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox,
                     QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTimeEdit)
        for theme, dark, compact in product(THEME_KEYS, (False, True), (False, True)):
            colors = self.engine.apply_to(self.app, theme, dark=dark, custom_color="#168078")
            panel = QWidget()
            panel.setObjectName("worklog_entry_panel_widget")
            panel.setProperty("compact", compact)
            layout = QGridLayout(panel)
            fields = []
            for row, factory in enumerate(factories):
                layout.addWidget(QLabel(factory.__name__), row, 0)
                pair = [factory(), factory()]
                for column, field in enumerate(pair, 1):
                    if isinstance(field, QComboBox):
                        field.addItems(("Selection", "Alternative"))
                    elif isinstance(field, QLineEdit):
                        field.setText("Sample text")
                    elif isinstance(field, (QTextEdit, QPlainTextEdit)):
                        field.setPlainText("Sample text")
                    field.setFixedSize(230, 64 if isinstance(field, (QTextEdit, QPlainTextEdit)) else 44)
                    layout.addWidget(field, row, column)
                pair[1].setEnabled(False)
                fields.append(pair)
            panel.show()
            self.app.processEvents()
            try:
                for enabled, disabled in fields:
                    with self.subTest(theme=theme, dark=dark, compact=compact, control=type(enabled).__name__):
                        self.assertEqual(enabled.size(), disabled.size())
                        self.assertEqual(disabled.palette().color(QPalette.ColorGroup.Disabled,
                            QPalette.ColorRole.Text).name(), colors.disabled_text)
                        image = disabled.grab().toImage().scaled(disabled.size())
                        self.assertEqual(image.pixelColor(disabled.width() // 2, 5).name(), colors.disabled_background)
                        geometry = enabled.geometry()
                        enabled.setEnabled(False)
                        self.app.processEvents()
                        self.assertEqual(enabled.geometry(), geometry)
                        self.assertEqual(enabled.palette().color(QPalette.ColorGroup.Disabled,
                            QPalette.ColorRole.Text).name(), colors.disabled_text)
                        enabled.setEnabled(True)
                        self.app.processEvents()
                        self.assertEqual(enabled.palette().color(QPalette.ColorRole.Text).name(), colors.text)
                self.capture(panel, f"{theme}-{dark}-inputs-{compact}")
                panel.setEnabled(False)
                self.app.processEvents()
                for field, _disabled in fields:
                    self.assertFalse(field.isEnabled())
                    self.assertEqual(field.palette().color(QPalette.ColorGroup.Disabled,
                        QPalette.ColorRole.Text).name(), colors.disabled_text)
            finally:
                panel.close()
                panel.deleteLater()

    def test_disabled_menu_actions_do_not_show_selection_feedback(self):
        for theme, dark in product(THEME_KEYS, (False, True)):
            colors = self.engine.apply_to(self.app, theme, dark=dark, custom_color="#168078")
            menu = QMenu()
            action = menu.addAction("Unavailable action")
            action.setEnabled(False)
            menu.ensurePolished()
            images = []
            for selected in (False, True):
                option = QStyleOptionMenuItem()
                menu.initStyleOption(option, action)
                option.rect = QRect(0, 0, 240, 40)
                if selected:
                    option.state |= QStyle.StateFlag.State_Selected
                image = QImage(option.rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(QColor(colors.surface))
                painter = QPainter(image)
                try:
                    menu.style().drawControl(QStyle.ControlElement.CE_MenuItem, option, painter, menu)
                finally:
                    painter.end()
                images.append(image)
            self.assertEqual(images[0], images[1], (theme, dark))
            menu.deleteLater()

    def test_selection_controls_and_custom_widgets_distinguish_inherited_disabled_state(self):
        from tests.presentation.test_qt_widgets import _calendar_state

        for theme, dark in product(THEME_KEYS, (False, True)):
            self.engine.apply_to(self.app, theme, dark=dark, custom_color="#168078")
            panel = QWidget()
            layout = QGridLayout(panel)
            controls = []
            for name in ("", "local_model_list_widget", "custom_entry_type_list_widget", "note_history_list_widget"):
                field = QListWidget()
                field.setObjectName(name)
                field.addItems(("Selected title\nDetails", "Another item"))
                field.setCurrentRow(0)
                if name == "note_history_list_widget":
                    field.setItemDelegate(PreviewItemDelegate(field))
                controls.append(field)
            controls[0].setProperty("management_list", True)
            tree = QTreeWidget()
            tree.setProperty("data_browser", True)
            tree.setHeaderLabels(("Column",))
            tree.addTopLevelItem(QTreeWidgetItem(("Selected item",)))
            tree.setCurrentItem(tree.topLevelItem(0))
            controls.append(tree)
            for name in ("", "management_tab_bar", "worklog_mode_selector_widget"):
                tabs = QTabBar()
                tabs.setObjectName(name)
                tabs.addTab("Selected")
                tabs.addTab("Other")
                controls.append(tabs)
            for factory in (QCheckBox, QRadioButton, SwitchButton):
                field = factory()
                field.setChecked(True)
                controls.append(field)
            controls.extend((QSlider(Qt.Orientation.Horizontal), IconLabel("settings")))
            cell = next(cell for cell in _calendar_state().cells if cell.is_selected)
            calendar_day = CalendarDayButton()
            calendar_day.set_cell(replace(cell, style=self.engine.calendar_cell_style({"selected"}, theme=theme, dark=dark)))
            month = MonthCalendar()
            month.setSelectedDate(QDate(2026, 10, 16))
            history = ReportHistoryButton(ReportHistoryDisplayItem(1, 1, "daily", date(2026, 10, 1),
                date(2026, 10, 1), "Saved report"))
            history.setObjectName("report_history_item_button")
            history.set_current(True)
            record = RecordSummaryButton("09:00 - 10:00\nRecorded work", deletable=True, actions_enabled=True)
            controls.extend((calendar_day, month, history, record))
            for row, field in enumerate(controls):
                column = (row % 2) * 2
                layout.addWidget(QLabel(field.objectName() or type(field).__name__), row // 2, column)
                layout.addWidget(field, row // 2, column + 1)
                if isinstance(field, (QListWidget, QTreeWidget)):
                    field.setFixedSize(300, 90)
            panel.show()
            self.app.processEvents()
            record.update_delete_visibility(record.mapToGlobal(QPoint(10, 10)))
            self.assertTrue(record.delete_button.isVisible())
            self.assertTrue(record.actions_button.isVisible())
            before = [field.grab().toImage() for field in controls]
            geometries = [field.geometry() for field in controls]
            self.capture(panel, f"{theme}-{dark}-selections-enabled")
            panel.setEnabled(False)
            self.app.processEvents()
            try:
                self.assertTrue(record.delete_button.isHidden())
                self.assertTrue(record.actions_button.isHidden())
                for field, image, geometry in zip(controls, before, geometries):
                    with self.subTest(theme=theme, dark=dark, control=field.objectName() or type(field).__name__):
                        self.assertFalse(field.isEnabled())
                        self.assertEqual(field.geometry(), geometry)
                        self.assertNotEqual(field.grab().toImage(), image)
                self.capture(panel, f"{theme}-{dark}-selections")
                panel.setEnabled(True)
                self.app.processEvents()
                self.assertTrue(all(field.isEnabled() for field in controls))
            finally:
                panel.close()
                panel.deleteLater()

    def capture(self, source, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            snapshot = source if isinstance(source, QImage) else source.grab()
            self.assertTrue(snapshot.save(str(target / f"{name}.png")))

    def test_switches_distinguish_keyboard_focus_from_mouse_focus(self):
        for theme, dark in product(THEME_KEYS, (False, True)):
            self.engine.apply_to(self.app, theme, dark=dark)
            panel = QWidget()
            panel.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            layout = QGridLayout(panel)
            controls = [SwitchButton(), SwitchButton(checked=True)]
            for row, control in enumerate(controls):
                layout.addWidget(control, row // 2, row % 2)
            panel.show()
            panel.activateWindow()
            self.app.processEvents()
            try:
                for index, control in enumerate(controls):
                    QTest.mouseClick(control, Qt.MouseButton.LeftButton)
                    self.app.processEvents()
                    before, geometry = control.grab().toImage(), control.geometry()
                    self.assertTrue(control.hasFocus())
                    self.capture(control, f"{theme}-{dark}-mouse-focus-{index}")
                    QTest.keyClick(control, Qt.Key.Key_Tab)
                    QTest.keyClick(self.app.focusWidget(), Qt.Key.Key_Backtab)
                    self.app.processEvents()
                    self.assertTrue(control.hasFocus())
                    self.assertNotEqual(before, control.grab().toImage(), (theme, dark, index))
                    self.assertEqual(geometry, control.geometry())
                    self.capture(control, f"{theme}-{dark}-keyboard-focus-{index}")
                    checked = control.isChecked()
                    QTest.mouseClick(control, Qt.MouseButton.LeftButton)
                    control.setChecked(checked)
                    self.app.processEvents()
                    self.assertTrue(control.hasFocus())
                    self.assertEqual(before, control.grab().toImage(), (theme, dark, index))
            finally:
                panel.close()
                panel.deleteLater()
