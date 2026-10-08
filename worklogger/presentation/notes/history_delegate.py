"""Readable, width-constrained date and preview rows for the note history."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem


class NoteHistoryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(190, max(64, 2 * QFontMetrics(option.font).height() + 28))

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        title, _separator, preview = str(index.data(Qt.ItemDataRole.DisplayRole) or "").partition("\n")
        styled.text = ""
        style = styled.widget.style() if styled.widget else QApplication.style()
        painter.save()
        painter.setClipRect(styled.rect)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        color = styled.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        font = QFont(styled.font)
        font.setBold(True)
        metrics = QFontMetrics(font)
        text_rect = styled.rect.adjusted(12, 10, -12, -10)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRect(text_rect.x(), text_rect.y(), text_rect.width(), metrics.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(title, Qt.TextElideMode.ElideRight, text_rect.width()))
        font.setBold(False)
        painter.setFont(font)
        if not selected:
            color.setAlphaF(0.72)
        painter.setPen(color)
        preview_rect = QRect(text_rect.x(), text_rect.y() + metrics.height() + 6,
                             text_rect.width(), QFontMetrics(font).height())
        painter.drawText(preview_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(font).elidedText(preview, Qt.TextElideMode.ElideRight, text_rect.width()))
        painter.restore()
