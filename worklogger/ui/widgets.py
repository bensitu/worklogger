"""Reusable custom Qt widgets."""

import math

from PySide6.QtWidgets import (
    QGridLayout, QLabel, QLineEdit, QSizePolicy, QSlider, QWidget,
)
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPen,
)

from config.constants import (
    COMBO_CHART_VALUE_LABEL_GAP,
    COMBO_CHART_VALUE_LABEL_LIGHTNESS_THRESHOLD,
    COMBO_CHART_VALUE_LABEL_PADDING_X,
    COMBO_CHART_VALUE_LABEL_PADDING_Y,
    COMBO_CHART_VALUE_LABEL_RADIUS,
)
from config.themes import (
    COLOR_WIDGET_DEFAULT_COLOR,
    COLOR_WHEEL_BORDER_COLOR,
    COLOR_WHEEL_MARKER_INNER_COLOR,
    COLOR_WHEEL_MARKER_OUTER_COLOR,
    COMBO_CHART_DOT_BORDER_COLOR,
    SWITCH_THUMB_COLOR,
    combo_chart_palette,
    normalize_hex_color,
    switch_default_colors,
)
from utils.i18n import _


class SwitchButton(QWidget):
    """Animated toggle switch that replaces QCheckBox in settings."""

    toggled = Signal(bool)

    _W, _H = 42, 24

    def __init__(
        self,
        checked: bool = False,
        color_on: str | None = None,
        color_off: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        default_on, default_off = switch_default_colors()
        self._checked = checked
        self._color_on = QColor(color_on or default_on)
        self._color_off = QColor(color_off or default_off)
        self._travel = float(self._W - self._H)
        self._pos = self._travel if checked else 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def isChecked(self) -> bool:
        return self._checked

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.update()

    def setChecked(self, val: bool) -> None:
        if val == self._checked:
            return
        self._checked = val
        self._anim_timer.start()
        self.toggled.emit(val)

    def mousePressEvent(self, event):
        if not self.isEnabled():
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def _tick(self):
        target = self._travel if self._checked else 0.0
        diff = target - self._pos
        if abs(diff) < 0.8:
            self._pos = target
            self._anim_timer.stop()
        else:
            self._pos += diff * 0.30
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._W, self._H

        # Blend track color between off/on states during the thumb animation.
        t = max(0.0, min(1.0, self._pos / self._travel)
                ) if self._travel else (1.0 if self._checked else 0.0)
        on, off = self._color_on, self._color_off
        track_c = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        thumb_c = QColor(SWITCH_THUMB_COLOR)
        border_c = None
        if not self.isEnabled():
            dark = self.palette().window().color().lightness() < 128
            track_c = QColor("#4c5363" if dark else "#d9dfef")
            thumb_c = QColor("#8d94a3" if dark else "#f5f7fb")
            border_c = QColor("#626a7d" if dark else "#aab1c5")
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(track_c))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        if border_c is not None:
            p.setPen(QPen(border_c, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)
            p.setPen(Qt.NoPen)

        pad = 3
        td = h - pad * 2
        tx = self._pos + pad
        p.setBrush(QBrush(thumb_c))
        p.drawEllipse(QRectF(tx, pad, td, td))
        p.end()


class ColorCircle(QWidget):
    """Circular hue/saturation picker drawn with QPainter."""

    selected_color_changed = Signal(str)

    def __init__(self, color: str = COLOR_WIDGET_DEFAULT_COLOR, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._sat = 0.0
        self._value = 1.0
        self._image_cache: tuple[int, float, QImage] | None = None
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self.set_color(color)

    def color(self) -> str:
        return QColor.fromHsvF(self._hue, self._sat, self._value).name()

    def set_color(self, color: str, emit: bool = False) -> None:
        qcolor = QColor(normalize_hex_color(color))
        hue, sat, val, _alpha = qcolor.getHsvF()
        if hue >= 0:
            self._hue = hue
        self._sat = max(0.0, min(1.0, sat))
        self._value = max(0.0, min(1.0, val))
        self._image_cache = None
        self.update()
        if emit:
            self.selected_color_changed.emit(self.color())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._update_from_pos(event.position())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._update_from_pos(event.position())
        super().mouseMoveEvent(event)

    def _wheel_rect(self) -> QRectF:
        side = max(20.0, min(self.width(), self.height()) - 14.0)
        return QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )

    def _update_from_pos(self, pos: QPointF) -> None:
        rect = self._wheel_rect()
        center = rect.center()
        dx = pos.x() - center.x()
        dy = center.y() - pos.y()
        radius = rect.width() / 2
        dist = math.hypot(dx, dy)
        if radius <= 0:
            return
        self._sat = max(0.0, min(1.0, dist / radius))
        if dist > 0:
            self._hue = (math.degrees(math.atan2(dy, dx)) % 360.0) / 360.0
        self.update()
        self.selected_color_changed.emit(self.color())

    def _wheel_image(self, size: int) -> QImage:
        cached = self._image_cache
        if cached and cached[0] == size and abs(cached[1] - self._value) < 0.001:
            return cached[2]
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        center = (size - 1) / 2
        radius = max(1.0, center)
        for y in range(size):
            for x in range(size):
                dx = x - center
                dy = center - y
                dist = math.hypot(dx, dy)
                if dist <= radius:
                    hue = (math.degrees(math.atan2(dy, dx)) % 360.0) / 360.0
                    sat = max(0.0, min(1.0, dist / radius))
                    image.setPixelColor(x, y, QColor.fromHsvF(hue, sat, self._value))
        self._image_cache = (size, self._value, image)
        return image

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self._wheel_rect()
        size = max(20, int(rect.width()))
        p.drawImage(rect, self._wheel_image(size))
        p.setPen(QPen(QColor(COLOR_WHEEL_BORDER_COLOR), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)

        radius = rect.width() / 2
        center = rect.center()
        angle = self._hue * math.tau
        marker = QPointF(
            center.x() + math.cos(angle) * self._sat * radius,
            center.y() - math.sin(angle) * self._sat * radius,
        )
        marker_rect = QRectF(marker.x() - 6, marker.y() - 6, 12, 12)
        p.setPen(QPen(QColor(COLOR_WHEEL_MARKER_OUTER_COLOR), 2))
        p.setBrush(QBrush(QColor(self.color())))
        p.drawEllipse(marker_rect)
        p.setPen(QPen(QColor(COLOR_WHEEL_MARKER_INNER_COLOR), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(marker_rect)
        p.end()


class ColorPickerSliders(QWidget):
    """RGB and HEX controls for a custom accent color."""

    selected_color_changed = Signal(str)

    def __init__(self, color: str = COLOR_WIDGET_DEFAULT_COLOR, parent=None):
        super().__init__(parent)
        self._updating = False
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self._sliders: dict[str, QSlider] = {}
        for row, key in enumerate(("R", "G", "B")):
            label = QLabel(key)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.valueChanged.connect(self._from_sliders)
            value_label = QLabel("000")
            value_label.setObjectName("muted")
            value_label.setFixedWidth(28)
            self._sliders[key] = slider
            setattr(self, f"_{key.lower()}_value", value_label)
            layout.addWidget(label, row, 0)
            layout.addWidget(slider, row, 1)
            layout.addWidget(value_label, row, 2)

        layout.addWidget(QLabel(_("HEX")), 3, 0)
        self._hex = QLineEdit()
        self._hex.setMaxLength(7)
        self._hex.editingFinished.connect(self._from_hex)
        layout.addWidget(self._hex, 3, 1, 1, 2)
        self.set_color(color)

    def color(self) -> str:
        return normalize_hex_color(self._hex.text())

    def set_color(self, color: str, emit: bool = False) -> None:
        qcolor = QColor(normalize_hex_color(color))
        self._updating = True
        try:
            values = {"R": qcolor.red(), "G": qcolor.green(), "B": qcolor.blue()}
            for key, val in values.items():
                self._sliders[key].setValue(val)
                getattr(self, f"_{key.lower()}_value").setText(f"{val:03d}")
            self._hex.setText(qcolor.name())
        finally:
            self._updating = False
        if emit:
            self.selected_color_changed.emit(self.color())

    def _from_sliders(self) -> None:
        if self._updating:
            return
        color = QColor(
            self._sliders["R"].value(),
            self._sliders["G"].value(),
            self._sliders["B"].value(),
        ).name()
        self.set_color(color)
        self.selected_color_changed.emit(color)

    def _from_hex(self) -> None:
        if self._updating:
            return
        color = normalize_hex_color(self._hex.text())
        self.set_color(color)
        self.selected_color_changed.emit(color)


class ComboChart(QWidget):
    """Bar and line chart drawn with QPainter."""

    def __init__(
        self,
        bar_items: list,
        ref: float,
        dark: bool,
        accent: str,
        line_items: list | None = None,
        line_ref: float | None = None,
        leave_indices: set[int] | None = None,
        leave_items: list | None = None,
        mode: str = "bar",
        show_leave_markers: bool = False,
        unit: str = "h",
        no_data: str = "No data",
        bar_label: str = "Work hours",
        line_label: str = "Average",
        leave_label: str = "Leave",
        parent=None,
    ):
        super().__init__(parent)
        self._bar_items = list(bar_items)
        self._line_items = list(line_items if line_items is not None else bar_items)
        self._ref = ref
        self._line_ref = ref if line_ref is None else line_ref
        self._leave_indices = set(leave_indices or set())
        self._leave_items = list(leave_items or [])
        self._mode = mode if mode in {"bar", "line", "combo"} else "bar"
        self._show_leave_markers = show_leave_markers
        self._unit = unit
        self._no_data = no_data
        self._acc = accent
        self._bar_label = bar_label
        self._line_label = line_label
        self._leave_label = leave_label
        palette = combo_chart_palette(dark)
        self._c_line = palette["line"]
        self._c_leave = palette["leave"]
        self._dashed_lines: list[tuple[list[float | None], QColor, Qt.PenStyle, str]] = []
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._c_txt = palette["text"]
        self._c_mut = palette["muted"]
        self._c_grid = palette["grid"]
        self._c_ref = palette["reference"]
        self._c_ot = palette["overtime"]
        self._c_ref_bg = palette["reference_background"]

    def set_mode(self, mode: str) -> None:
        if mode not in {"bar", "line", "combo"} or mode == self._mode:
            return
        self._mode = mode
        self.update()

    def set_show_leave_markers(self, enabled: bool) -> None:
        if enabled == self._show_leave_markers:
            return
        self._show_leave_markers = enabled
        self.update()

    def set_data(
        self,
        bar_items: list,
        line_items: list | None = None,
        leave_indices: set[int] | None = None,
        leave_items: list | None = None,
    ) -> None:
        self._bar_items = list(bar_items)
        self._line_items = list(line_items if line_items is not None else bar_items)
        self._leave_indices = set(leave_indices or set())
        if leave_items is not None:
            self._leave_items = list(leave_items)
        self.update()

    def set_reference(self, ref: float, line_ref: float | None = None) -> None:
        self._ref = ref
        self._line_ref = ref if line_ref is None else line_ref
        self.update()

    def set_series_labels(self, bar_label: str, line_label: str) -> None:
        self._bar_label = bar_label
        self._line_label = line_label
        self.update()

    def clear_dashed_lines(self) -> None:
        self._dashed_lines.clear()
        self.update()

    def add_dashed_line(
        self,
        y_data: list[float | None],
        color: str,
        style=Qt.DashLine,
        label: str | None = None,
    ) -> None:
        self._dashed_lines.append((list(y_data), QColor(color), style, label or self._leave_label))
        self.update()

    def _active_ref(self) -> float:
        return self._line_ref if self._mode == "line" else self._ref

    def _labels(self) -> list[str]:
        source = self._bar_items if self._bar_items else self._line_items
        return [str(label) for label, _value in source]

    def _scale_values(self) -> list[float]:
        values: list[float] = []
        if self._mode in {"bar", "combo"}:
            values.extend(float(value) for _label, value in self._bar_items)
            if self._show_leave_markers:
                for index in self._leave_indices:
                    leave_value = self._leave_value_at(index)
                    if leave_value > 0:
                        values.append(self._bar_value_at(index) + leave_value)
        if self._mode in {"line", "combo"}:
            values.extend(float(value) for _label, value in self._line_items)
            for y_data, _color, _style, _label in self._dashed_lines:
                values.extend(float(value) for value in y_data if value is not None)
        ref = self._active_ref()
        if ref > 0:
            values.append(float(ref))
        return values

    def _point_y(self, value: float, max_v: float, mt: float, ch: float) -> float:
        return mt + ch * (1 - min(value, max_v) / max_v)

    def _draw_legend(self, p: QPainter, x: float, y: float) -> None:
        entries: list[tuple[str, str, QColor]] = []
        if self._mode in {"bar", "combo"}:
            entries.append(("bar", self._bar_label, QColor(self._acc)))
        if self._mode in {"line", "combo"}:
            entries.append(("line", self._line_label, QColor(self._c_line)))
        if self._show_leave_markers and self._mode in {"bar", "combo"} and self._leave_indices:
            entries.append(("leave", self._leave_label, QColor(self._c_leave)))
        if self._show_leave_markers and self._mode == "line":
            for _y_data, color, _style, label in self._dashed_lines:
                entries.append(("dashed", label, color))

        p.setFont(QFont("sans-serif", 8))
        fm = QFontMetrics(p.font())
        cursor = x
        for kind, label, color in entries:
            marker = QRectF(cursor, y + 2, 14, 8)
            if kind == "line":
                p.setPen(QPen(color, 2))
                p.drawLine(
                    QPointF(marker.left(), marker.center().y()),
                    QPointF(marker.right(), marker.center().y()),
                )
                p.setBrush(QBrush(color))
                p.drawEllipse(QRectF(marker.center().x() - 2, marker.center().y() - 2, 4, 4))
            elif kind == "dashed":
                p.setPen(QPen(color, 2, Qt.DashLine))
                p.drawLine(
                    QPointF(marker.left(), marker.center().y()),
                    QPointF(marker.right(), marker.center().y()),
                )
            elif kind == "leave":
                pale = QColor(color)
                pale.setAlpha(150)
                p.setPen(QPen(pale, 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(marker, 2, 2)
                self._draw_hatch(p, marker, pale, spacing=5)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(color))
                p.drawRoundedRect(marker, 2, 2)
            p.setPen(QColor(self._c_mut))
            p.drawText(QRectF(cursor + 18, y - 1, 120, 14), Qt.AlignLeft | Qt.AlignVCenter, label)
            cursor += 22 + fm.horizontalAdvance(label) + 14

    def _draw_hatch(self, p: QPainter, rect: QRectF, color: QColor, spacing: int = 7) -> None:
        p.save()
        p.setClipRect(rect)
        p.setPen(QPen(color, 1))
        start = int(rect.left() - rect.height())
        stop = int(rect.right() + rect.height())
        for x in range(start, stop, spacing):
            p.drawLine(
                QPointF(x, rect.bottom()),
                QPointF(x + rect.height(), rect.top()),
            )
        p.restore()

    def _value_label_rect(
        self,
        fm: QFontMetrics,
        text: str,
        center_x: float,
        top_y: float,
        left: float,
        right: float,
    ) -> QRectF:
        label_w = fm.horizontalAdvance(text) + COMBO_CHART_VALUE_LABEL_PADDING_X * 2
        label_h = fm.height() + COMBO_CHART_VALUE_LABEL_PADDING_Y * 2
        label_x = center_x - label_w / 2
        if label_w <= right - left:
            label_x = max(left, min(label_x, right - label_w))
        else:
            label_x = left
        return QRectF(label_x, top_y, label_w, label_h)

    def _draw_value_label(
        self,
        p: QPainter,
        rect: QRectF,
        text: str,
        color: QColor,
        fill: QColor | None = None,
        border: QColor | None = None,
    ) -> None:
        if fill is not None:
            p.setBrush(QBrush(fill))
            p.setPen(QPen(border or fill, 1))
            p.drawRoundedRect(
                rect,
                COMBO_CHART_VALUE_LABEL_RADIUS,
                COMBO_CHART_VALUE_LABEL_RADIUS,
            )
        p.setPen(color)
        p.drawText(rect, Qt.AlignCenter, text)

    def _bar_label_color(self, bar_color: QColor, inside_bar: bool) -> QColor:
        if inside_bar and bar_color.lightness() <= COMBO_CHART_VALUE_LABEL_LIGHTNESS_THRESHOLD:
            return QColor(COMBO_CHART_DOT_BORDER_COLOR)
        return QColor(self._c_txt)

    def _bar_value_at(self, index: int) -> float:
        if index < 0 or index >= len(self._bar_items):
            return 0.0
        try:
            return max(float(self._bar_items[index][1]), 0.0)
        except (TypeError, ValueError, IndexError):
            return 0.0

    def _leave_value_at(self, index: int) -> float:
        if index < 0 or index >= len(self._leave_items):
            return 0.0
        try:
            return max(float(self._leave_items[index][1]), 0.0)
        except (TypeError, ValueError, IndexError):
            return 0.0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self._bar_items and not self._line_items:
            p.setPen(QColor(self._c_mut))
            p.setFont(QFont("sans-serif", 11))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self._no_data)
            p.end()
            return

        ml, mr, mt, mb = 46, 12, 42, 40
        cw = max(1.0, w - ml - mr)
        ch = max(1.0, h - mt - mb)
        labels = self._labels()
        n = max(len(labels), len(self._bar_items), len(self._line_items), 1)
        slot_w = cw / n
        bar_w = max(min(slot_w * 0.60, 40.0), 6.0)
        max_v = max(self._scale_values() or [0.0]) * 1.18 or 10.0

        self._draw_legend(p, ml, 12)

        for i in range(6):
            frac = i / 5
            yy = mt + ch * (1 - frac)
            p.setPen(QPen(QColor(self._c_grid), 1))
            p.drawLine(ml, int(yy), ml + int(cw), int(yy))
            p.setPen(QColor(self._c_mut))
            p.setFont(QFont("sans-serif", 8))
            lbl = f"{max_v * frac:.0f}{self._unit}"
            fm = QFontMetrics(p.font())
            p.drawText(2, int(yy) + fm.ascent() // 2, lbl)

        active_ref = self._active_ref()
        if 0 < active_ref <= max_v:
            ry = self._point_y(active_ref, max_v, mt, ch)
            p.setPen(QPen(QColor(self._c_ref), 1.5, Qt.DashLine))
            p.drawLine(ml, int(ry), ml + int(cw), int(ry))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(self._c_ref_bg)))
            ref_text = f"{active_ref:.1f}{self._unit}"
            p.setFont(QFont("sans-serif", 8))
            fm_ref = QFontMetrics(p.font())
            pad_x = 6
            label_w = fm_ref.horizontalAdvance(ref_text) + pad_x * 2
            label_h = fm_ref.height() + 2
            label_x = max(ml + 4, ml + cw - label_w - 2)
            label_y = max(2, min(int(ry - label_h - 2), h - label_h - 2))
            p.drawRoundedRect(QRectF(label_x, label_y, label_w, label_h), 5, 5)
            p.setPen(QColor(self._c_ref))
            p.drawText(QRectF(label_x, label_y, label_w, label_h), Qt.AlignCenter, ref_text)

        value_font = QFont("sans-serif", 8)
        p.setFont(value_font)
        value_fm = QFontMetrics(value_font)
        label_h = value_fm.height() + COMBO_CHART_VALUE_LABEL_PADDING_Y * 2
        chart_left = ml
        chart_right = ml + cw
        bar_value_labels: list[tuple[QRectF, str, QColor]] = []
        bar_value_label_rects: dict[int, QRectF] = {}
        leave_value_labels: list[tuple[QRectF, str, QColor]] = []
        if self._mode in {"bar", "combo"}:
            for i, (_label, val) in enumerate(self._bar_items):
                bh = (min(val, max_v) / max_v) * ch
                x = ml + i * slot_w + (slot_w - bar_w) / 2
                y = mt + ch - bh
                c = QColor(self._c_ot if val > self._ref else self._acc)
                p.setBrush(QBrush(c))
                p.setPen(Qt.NoPen)
                if bh > 0:
                    p.drawRoundedRect(QRectF(x, y, bar_w, bh), 3, 3)
                if val > 0:
                    has_stacked_leave = (
                        self._show_leave_markers
                        and i in self._leave_indices
                        and self._leave_value_at(i) > 0
                    )
                    if has_stacked_leave:
                        label_y = y + max(
                            COMBO_CHART_VALUE_LABEL_PADDING_Y,
                            (bh - label_h) / 2,
                        )
                        label_y = min(label_y, mt + ch - label_h)
                    else:
                        label_y = y - label_h - COMBO_CHART_VALUE_LABEL_GAP
                    label_y = max(mt, label_y)
                    text = f"{float(val):.1f}"
                    rect = self._value_label_rect(
                        value_fm,
                        text,
                        x + bar_w / 2,
                        label_y,
                        chart_left,
                        chart_right,
                    )
                    bar_value_label_rects[i] = rect
                    bar_value_labels.append(
                        (rect, text, self._bar_label_color(c, has_stacked_leave))
                    )

        if self._show_leave_markers and self._mode in {"bar", "combo"} and self._leave_indices:
            leave_color = QColor(self._c_leave)
            leave_color.setAlpha(155)
            leave_text_color = QColor(self._c_txt)
            for i in sorted(self._leave_indices):
                if i < 0 or i >= n:
                    continue
                leave_value = self._leave_value_at(i)
                if leave_value <= 0:
                    continue
                work_value = self._bar_value_at(i)
                combined_value = work_value + leave_value
                bottom_y = (
                    self._point_y(work_value, max_v, mt, ch)
                    if work_value > 0
                    else mt + ch
                )
                top_y = self._point_y(combined_value, max_v, mt, ch)
                marker_h = max(1.0, bottom_y - top_y)
                x = ml + i * slot_w + (slot_w - bar_w) / 2
                p.setPen(QPen(leave_color, 1.8, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                rect = QRectF(x, top_y, bar_w, marker_h)
                p.drawRoundedRect(rect, 3, 3)
                self._draw_hatch(p, rect, leave_color)
                label_text = f"{leave_value:.1f}"
                if marker_h >= label_h + COMBO_CHART_VALUE_LABEL_GAP:
                    label_y = top_y + (marker_h - label_h) / 2
                else:
                    label_y = top_y - label_h - COMBO_CHART_VALUE_LABEL_GAP
                max_y_above_work = bottom_y - label_h - COMBO_CHART_VALUE_LABEL_GAP
                if max_y_above_work >= mt:
                    label_y = min(label_y, max_y_above_work)
                label_y = max(mt, min(label_y, mt + ch - label_h))
                label_rect = self._value_label_rect(
                    value_fm,
                    label_text,
                    x + bar_w / 2,
                    label_y,
                    chart_left,
                    chart_right,
                )
                work_rect = bar_value_label_rects.get(i)
                if work_rect is not None and label_rect.intersects(work_rect):
                    candidate_y = work_rect.top() - label_rect.height() - COMBO_CHART_VALUE_LABEL_GAP
                    if candidate_y >= mt:
                        label_rect.moveTop(candidate_y)
                    else:
                        right_x = x + bar_w + COMBO_CHART_VALUE_LABEL_GAP
                        left_x = x - label_rect.width() - COMBO_CHART_VALUE_LABEL_GAP
                        if right_x + label_rect.width() <= chart_right:
                            label_rect.moveLeft(right_x)
                        elif left_x >= chart_left:
                            label_rect.moveLeft(left_x)
                leave_value_labels.append((label_rect, label_text, leave_text_color))

        p.setFont(value_font)
        for rect, text, text_color in leave_value_labels:
            self._draw_value_label(p, rect, text, text_color)

        for rect, text, color in bar_value_labels:
            self._draw_value_label(p, rect, text, color)

        if self._mode in {"line", "combo"}:
            points: list[QPointF] = []
            for i, (_label, val) in enumerate(self._line_items):
                x = ml + i * slot_w + slot_w / 2
                y = self._point_y(float(val), max_v, mt, ch)
                points.append(QPointF(x, y))
            p.setPen(QPen(QColor(self._c_line), 2.2))
            for i in range(1, len(points)):
                p.drawLine(points[i - 1], points[i])
            p.setBrush(QBrush(QColor(self._c_line)))
            p.setPen(QPen(QColor(COMBO_CHART_DOT_BORDER_COLOR), 1))
            for point in points:
                p.drawEllipse(QRectF(point.x() - 3.5, point.y() - 3.5, 7, 7))

            if self._show_leave_markers:
                for y_data, color, style, _label in self._dashed_lines:
                    leave_points: list[QPointF | None] = []
                    for i, value in enumerate(y_data[:n]):
                        if value is None:
                            leave_points.append(None)
                            continue
                        x = ml + i * slot_w + slot_w / 2
                        y = self._point_y(float(value), max_v, mt, ch)
                        leave_points.append(QPointF(x, y))
                    p.setPen(QPen(color, 2.0, style))
                    previous: QPointF | None = None
                    for point in leave_points:
                        if point is None:
                            previous = None
                            continue
                        if previous is not None:
                            p.drawLine(previous, point)
                        previous = point
                    p.setBrush(QBrush(color))
                    p.setPen(Qt.NoPen)
                    for point in leave_points:
                        if point is not None:
                            p.drawEllipse(QRectF(point.x() - 3, point.y() - 3, 6, 6))

        p.setPen(QColor(self._c_mut))
        p.setFont(QFont("sans-serif", 8))
        fm2 = QFontMetrics(p.font())
        for i in range(n):
            label = labels[i] if i < len(labels) else str(i + 1)
            x = ml + i * slot_w + slot_w / 2
            tw = fm2.horizontalAdvance(label)
            p.drawText(int(x - tw / 2), h - mb + fm2.ascent() + 3, label)
        p.end()
