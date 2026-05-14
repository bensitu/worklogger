"""Simple combined bar/line analytics chart widget."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.infrastructure.i18n import _


class ComboChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bundle = ChartDataBundle((), (), frozenset(), (), ())
        self._mode = "bar"
        self.setObjectName("combo_chart")
        self.setMinimumHeight(220)

    def set_data(self, bundle: ChartDataBundle, *, mode: str = "bar") -> None:
        self._bundle = bundle
        self._mode = mode if mode in {"bar", "line"} else "bar"
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -28)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QPen(QColor("#b8c0cc"), 1))
        painter.drawRect(rect)
        if not self._bundle.bar_data:
            painter.setPen(QColor("#667085"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("No data"))
            return
        values = [float(value) for _label, value in self._bundle.bar_data]
        leave_values = [
            float(value)
            for _label, value in self._bundle.leave_hours_data
        ]
        maximum = max(values + leave_values + [1.0])
        step = rect.width() / max(len(values), 1)
        points: list[tuple[float, float]] = []
        for index, ((label, value), _raw) in enumerate(zip(self._bundle.bar_data, values)):
            center_x = rect.left() + step * index + step / 2
            bar_height = rect.height() * (float(value) / maximum)
            top = rect.bottom() - bar_height
            if self._mode == "bar":
                color = QColor("#2f80ed")
                if index in self._bundle.leave_indices:
                    color = QColor("#17a589")
                painter.fillRect(
                    QRectF(center_x - step * 0.28, top, step * 0.56, bar_height),
                    color,
                )
            points.append((center_x, top))
            leave = (
                self._bundle.leave_line_data[index]
                if index < len(self._bundle.leave_line_data)
                else None
            )
            if leave is not None:
                leave_y = rect.bottom() - rect.height() * (float(leave) / maximum)
                painter.setPen(QPen(QColor("#d35400"), 2))
                painter.drawLine(
                    int(center_x - step * 0.3),
                    int(leave_y),
                    int(center_x + step * 0.3),
                    int(leave_y),
                )
            painter.setPen(QColor("#344054"))
            painter.drawText(
                QRectF(rect.left() + step * index, rect.bottom() + 4, step, 18),
                Qt.AlignmentFlag.AlignCenter,
                str(label),
            )
        if self._mode == "line":
            painter.setPen(QPen(QColor("#2f80ed"), 3))
            for first, second in zip(points, points[1:]):
                painter.drawLine(int(first[0]), int(first[1]), int(second[0]), int(second[1]))
            painter.setBrush(QColor("#2f80ed"))
            for x_coord, y_coord in points:
                painter.drawEllipse(int(x_coord) - 3, int(y_coord) - 3, 6, 6)
