"""Window-modal first-use guidance anchored to the recording area."""

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QToolButton, QVBoxLayout, QWidget)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.widgets.icons import IconLabel, set_button_icon


class GettingStartedDialog(QDialog):
    guide_requested = Signal()

    def __init__(self, target, parent):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self._target = target
        self.spotlight_rect = QRectF()
        self._pointer = QPainterPath()
        self.setObjectName("getting_started_dialog")
        self.setWindowTitle(_("Getting started"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.card = QFrame(self)
        self.card.setObjectName("getting_started_card_frame")
        root = QVBoxLayout(self.card)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(16)
        heading = QHBoxLayout()
        self._heading_layout = heading
        heading.addWidget(IconLabel("clock"))
        eyebrow = QLabel(_("Getting started"))
        eyebrow.setProperty("role", "secondary")
        heading.addWidget(eyebrow, 1)
        self.close_button = QToolButton()
        self.close_button.setObjectName("getting_started_close_button")
        self.close_button.setToolTip(_("Close"))
        self.close_button.setAccessibleName(_("Close"))
        self.close_button.setFixedSize(28, 28)
        self.close_button.setProperty("variant", "ghost")
        set_button_icon(self.close_button, "x")
        self.close_button.clicked.connect(self.reject)
        heading.addWidget(self.close_button)
        root.addLayout(heading)
        self.content = QWidget()
        self.content.setObjectName("getting_started_content_widget")
        content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(16)
        title = QLabel(_("Start with your first record"))
        title.setProperty("role", "title")
        title.setWordWrap(True)
        content.addWidget(title)
        for message in (_("Finished work? Enter a start and end time."),
                        _("Working now? Use Auto Record."),
                        _("Add a classification and a short description.")):
            label = QLabel(message)
            label.setWordWrap(True)
            content.addWidget(label)
        hint = QLabel(_("Choose Start recording to close this guide and begin."))
        hint.setProperty("role", "secondary")
        hint.setWordWrap(True)
        content.addWidget(hint)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("getting_started_scroll_area")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.record_button = QPushButton(_("Start recording"))
        self.record_button.setProperty("variant", "primary")
        self.dismiss_button = QPushButton(_("Maybe later"))
        for button, icon in ((self.record_button, "chevron-right"), (self.dismiss_button, "x")):
            button.setProperty("dialog_action", True)
            button.setAutoDefault(False)
            set_button_icon(button, icon)
            actions.addWidget(button)
        self.record_button.clicked.connect(self.accept)
        self.dismiss_button.clicked.connect(self.reject)
        root.addLayout(actions)
        self.guide_button = QPushButton(_("User guide"))
        self.guide_button.setProperty("variant", "ghost")
        self.guide_button.setAutoDefault(False)
        set_button_icon(self.guide_button, "file-text")
        self.guide_button.clicked.connect(self.guide_requested)
        root.addWidget(self.guide_button, 0, Qt.AlignmentFlag.AlignLeft)
        QWidget.setTabOrder(self.record_button, self.dismiss_button)
        QWidget.setTabOrder(self.dismiss_button, self.guide_button)
        QWidget.setTabOrder(self.guide_button, self.close_button)
        parent.installEventFilter(self)
        target.installEventFilter(self)

    def sync_geometry(self):
        owner = self.parentWidget()
        self.setGeometry(QRect(owner.mapToGlobal(QPoint()), owner.size()))
        margin, gap = 20, 18
        bounds = self.rect().adjusted(margin, margin, -margin, -margin)
        target = QRect(self._target.mapToGlobal(QPoint()) - self.pos(), self._target.size())
        target = target.adjusted(-4, -4, 4, 4).intersected(self.rect().adjusted(4, 4, -4, -4))
        available = target.left() - gap - margin
        side = available >= 330 and not target.isEmpty()
        width = min(440, available if side else bounds.width())
        self.card.resize(width, self.card.height())
        self.card.layout().activate()
        frame = self.card.contentsMargins()
        content_height = self.content.layout().heightForWidth(max(1, width - 48 - frame.left() - frame.right()))
        fixed = (self.card.layout().contentsMargins().top() + self.card.layout().contentsMargins().bottom()
                 + self.card.layout().spacing() * 3 + self._heading_layout.sizeHint().height()
                 + self.record_button.sizeHint().height() + self.guide_button.sizeHint().height()
                 + frame.top() + frame.bottom() + 4)
        height = min(bounds.height(), max(320, content_height + fixed))
        x = target.left() - gap - width if side else (self.width() - width) // 2
        y = max(bounds.top(), min(target.top() + 64 if side else (self.height() - height) // 2,
                                 bounds.bottom() - height + 1))
        self.card.setGeometry(x, y, width, height)
        self.card.layout().activate()
        self.spotlight_rect = QRectF(target) if side else QRectF()
        self._pointer = QPainterPath()
        if side:
            anchor = min(self.card.geometry().center().y(), target.bottom() - 16)
            self._pointer.moveTo(self.card.geometry().right(), anchor - 9)
            self._pointer.lineTo(self.card.geometry().right() + 10, anchor)
            self._pointer.lineTo(self.card.geometry().right(), anchor + 9)
            self._pointer.closeSubpath()
        self.update()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            if self.isVisible():
                QTimer.singleShot(0, self, self.sync_geometry)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_geometry()
        self.record_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "card") and event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            QTimer.singleShot(0, self, self.sync_geometry)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not self.spotlight_rect.isEmpty():
            cutout = QPainterPath()
            cutout.addRoundedRect(self.spotlight_rect, 6, 6)
            shade = shade.subtracted(cutout)
        painter.fillPath(shade, QColor(0, 0, 0, 135))
        colors = current_colors()
        if not self.spotlight_rect.isEmpty():
            painter.setPen(QPen(QColor(colors.accent), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.spotlight_rect, 6, 6)
        painter.fillPath(self._pointer, QColor(colors.surface))
        painter.end()
