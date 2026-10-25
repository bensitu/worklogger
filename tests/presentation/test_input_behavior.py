"""Focused wheel editing and uninterrupted scrolling around form controls."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QTime, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QLineEdit,
    QScrollArea, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from tests.presentation.qt_support import dispose_test_windows
from worklogger.presentation.input_behavior import install_input_behavior
from worklogger.presentation.theme import configure_application_style


class InputBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_input_behavior(cls.app)

    def setUp(self):
        self.addCleanup(dispose_test_windows)
        self.window = QScrollArea()
        self.window.setWidgetResizable(True)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.other = QLineEdit()
        self.layout.addWidget(self.other)
        self.window.setWidget(content)

    def show_inputs(self, *fields):
        for field in fields:
            self.layout.addWidget(field)
        self.layout.addSpacing(1200)
        self.window.resize(500, 450)
        self.window.show()
        self.other.setFocus()
        self.app.processEvents()

    @staticmethod
    def wheel(widget, delta=-120):
        position = QPointF(8, 8)
        event = QWheelEvent(position, widget.mapToGlobal(position), QPoint(), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)

    def test_hovering_controls_scrolls_the_page_without_changing_values_or_focus(self):
        fields = []
        for editable in (False, True):
            combo = QComboBox()
            combo.setEditable(editable)
            combo.addItems(["First", "Second", "Third"])
            combo.setCurrentIndex(1)
            fields.append((combo, combo.currentIndex, combo.currentIndexChanged))
        for field in (QSpinBox(), QDoubleSpinBox()):
            field.setValue(10)
            fields.append((field, field.value, field.valueChanged))
        time = QTimeEdit(QTime(12, 30))
        day = QDateEdit()
        fields.extend(((time, time.time, time.timeChanged), (day, day.date, day.dateChanged)))
        self.show_inputs(*(field for field, _read, _signal in fields))
        install_input_behavior(self.app)
        for field, read, signal in fields:
            with self.subTest(control=type(field).__name__, editable=isinstance(field, QComboBox) and field.isEditable()):
                self.assertEqual(field.focusPolicy(), Qt.FocusPolicy.StrongFocus)
                initial = read()
                changed = QSignalSpy(signal)
                for target in (field, field.findChild(QLineEdit)):
                    if target is None:
                        continue
                    self.window.verticalScrollBar().setValue(0)
                    self.wheel(target)
                    self.assertEqual(read(), initial)
                    self.assertEqual(changed.count(), 0)
                    self.assertGreater(self.window.verticalScrollBar().value(), 0)
                    self.assertIs(self.app.focusWidget(), self.other)
                field.setEnabled(False)
                self.window.verticalScrollBar().setValue(0)
                self.wheel(field)
                self.assertEqual(read(), initial)
                self.assertGreater(self.window.verticalScrollBar().value(), 0)
                field.setEnabled(True)
        self.window.verticalScrollBar().setValue(0)
        combo = fields[0][0]
        QTest.wheelEvent(self.window.windowHandle(), combo.mapTo(self.window, QPoint(8, 8)), QPoint(0, -120))
        self.assertEqual(combo.currentIndex(), 1)
        self.assertIs(self.app.focusWidget(), self.other)

    def test_focused_controls_keep_wheel_keyboard_and_tab_editing(self):
        combo, spin = QComboBox(), QSpinBox()
        combo.addItems(["First", "Second", "Third"])
        combo.setCurrentIndex(1)
        spin.setValue(10)
        self.show_inputs(combo, spin)
        QTest.keyClick(self.other, Qt.Key.Key_Tab)
        self.assertTrue(combo.hasFocus())
        self.wheel(combo, 120)
        self.assertEqual(combo.currentIndex(), 0)
        QTest.keyClick(combo, Qt.Key.Key_Down)
        self.assertEqual(combo.currentIndex(), 1)
        QTest.mouseClick(spin.findChild(QLineEdit), Qt.MouseButton.LeftButton)
        self.assertTrue(spin.hasFocus())
        self.wheel(spin, 120)
        self.assertEqual(spin.value(), 11)
        QTest.keyClick(spin, Qt.Key.Key_Up)
        self.assertEqual(spin.value(), 12)
        self.assertEqual(self.window.verticalScrollBar().value(), 0)

    def test_open_dropdown_lists_remain_scrollable(self):
        combo = QComboBox()
        combo.addItems([f"Option {index}" for index in range(100)])
        combo.setMaxVisibleItems(5)
        self.show_inputs(combo)
        combo.showPopup()
        self.app.processEvents()
        view = combo.view()
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        self.wheel(view.viewport())
        self.assertGreater(view.verticalScrollBar().value(), 0)
        combo.hidePopup()

    def test_dialog_wheel_input_does_not_scroll_the_owner_window(self):
        self.show_inputs()
        dialog = QDialog(self.window)
        layout = QVBoxLayout(dialog)
        editor, spin = QLineEdit(), QSpinBox()
        spin.setValue(10)
        layout.addWidget(editor)
        layout.addWidget(spin)
        dialog.show()
        editor.setFocus()
        self.app.processEvents()
        self.wheel(spin)
        self.assertEqual(spin.value(), 10)
        self.assertEqual(self.window.verticalScrollBar().value(), 0)
        dialog.close()
