"""Require explicit focus before wheel input can change form values."""

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QWidget


class _FocusedWheelFilter(QObject):
    @staticmethod
    def configure(widget):
        if isinstance(widget, (QComboBox, QAbstractSpinBox)) and widget.focusPolicy() == Qt.FocusPolicy.WheelFocus:
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Polish:
            self.configure(watched)
        elif event.type() == QEvent.Type.Wheel:
            control = watched
            if isinstance(control, QLineEdit):
                control = control.parentWidget()
            if isinstance(control, (QComboBox, QAbstractSpinBox)) and not control.hasFocus():
                event.ignore()
                ancestor = control
                while not ancestor.isWindow():
                    ancestor = ancestor.parentWidget()
                    if not isinstance(ancestor, QWidget):
                        break
                    if isinstance(ancestor, QAbstractScrollArea):
                        viewport = ancestor.viewport()
                        forwarded = QWheelEvent(viewport.mapFromGlobal(event.globalPosition()), event.globalPosition(),
                            event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                            event.phase(), event.inverted(), event.source(), event.pointingDevice())
                        QCoreApplication.sendEvent(viewport, forwarded)
                        event.setAccepted(forwarded.isAccepted())
                        break
                return True
        return False


def install_input_behavior(application: QApplication) -> None:
    if getattr(application, "_worklogger_input_behavior", None) is not None:
        return
    behavior = _FocusedWheelFilter(application)
    application._worklogger_input_behavior = behavior
    application.installEventFilter(behavior)
    for widget in application.allWidgets():
        behavior.configure(widget)
