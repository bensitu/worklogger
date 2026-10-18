"""Shared lists and delegates for titles with bounded secondary text."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QApplication, QListWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem


class PreviewItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, *, soft_selection=False, detail_lines=1):
        super().__init__(parent)
        self._soft_selection = soft_selection
        self._detail_lines = detail_lines

    def sizeHint(self, option, index):
        if self._soft_selection:
            lines = min(self._detail_lines, str(index.data(Qt.ItemDataRole.DisplayRole) or "").count("\n"))
            height = QFontMetrics(option.font).height()
            return QSize(190, (lines + 1) * height + lines * 6 + 24)
        return QSize(190, max(64, 2 * QFontMetrics(option.font).height() + 28))

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        title, _separator, preview = str(index.data(Qt.ItemDataRole.DisplayRole) or "").partition("\n")
        styled.text = ""
        if self._soft_selection:
            styled.state &= ~QStyle.StateFlag.State_HasFocus
        style = styled.widget.style() if styled.widget else QApplication.style()
        painter.save()
        painter.setClipRect(styled.rect)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        group = (QPalette.ColorGroup.Normal if styled.state & QStyle.StateFlag.State_Enabled
                 else QPalette.ColorGroup.Disabled)
        color = styled.palette.color(group, QPalette.ColorRole.HighlightedText
                                     if selected and not self._soft_selection else QPalette.ColorRole.Text)
        font = QFont(styled.font)
        font.setWeight(QFont.Weight.DemiBold if self._soft_selection else QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        text_rect = styled.rect.adjusted(12, 10, -12, -10)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRect(text_rect.x(), text_rect.y(), text_rect.width(), metrics.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(title, Qt.TextElideMode.ElideRight, text_rect.width()))
        font.setBold(False)
        painter.setFont(font)
        if not selected or self._soft_selection:
            color.setAlphaF(0.72)
        painter.setPen(color)
        detail_metrics = QFontMetrics(font)
        details = preview.split("\n")[:self._detail_lines] if self._soft_selection else (preview,)
        for line, text in enumerate(details):
            preview_rect = QRect(text_rect.x(), text_rect.y() + metrics.height() + 6
                                 + line * (detail_metrics.height() + 6),
                                 text_rect.width(), detail_metrics.height())
            painter.drawText(preview_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             detail_metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width()))
        painter.restore()


class PreviewListWidget(QListWidget):
    def __init__(self, parent=None, *, soft_selection=False, framed=False, detail_lines=1, spacing=4):
        super().__init__(parent)
        self.setItemDelegate(PreviewItemDelegate(self, soft_selection=soft_selection, detail_lines=detail_lines))
        self.setSpacing(spacing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if framed or soft_selection:
            self.setProperty("list_style", "preview")
        self.setProperty("selection_style", "subtle" if soft_selection else "accent")
