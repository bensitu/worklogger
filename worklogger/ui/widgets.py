"""Reusable custom Qt widgets."""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics


class SwitchButton(QWidget):
    """Animated toggle switch that replaces QCheckBox in settings."""

    toggled = Signal(bool)

    _W, _H = 42, 24

    def __init__(self, checked: bool = False,
                 color_on:  str = "#4f8ef7",
                 color_off: str = "#b0b8cc",
                 parent=None):
        super().__init__(parent)
        self._checked = checked
        self._color_on = QColor(color_on)
        self._color_off = QColor(color_off)
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

    def setChecked(self, val: bool) -> None:
        if val == self._checked:
            return
        self._checked = val
        self._anim_timer.start()
        self.toggled.emit(val)

    def mousePressEvent(self, event):
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
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(track_c))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        pad = 3
        td = h - pad * 2
        tx = self._pos + pad
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(tx, pad, td, td))
        p.end()


class BarChart(QWidget):
    """Vertical bar chart drawn with QPainter (no external libs)."""

    def __init__(self, items: list, ref: float, dark: bool,
                 accent: str, unit: str = "h",
                 no_data: str = "No data", parent=None):
        super().__init__(parent)
        self._items = items
        self._ref = ref
        self._unit = unit
        self._no_data = no_data
        self._acc = accent
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if dark:
            self._c_txt = "#c8cde8"
            self._c_mut = "#8890b8"
            self._c_grid = "#2a2d48"
            self._c_ref = "#555580"
            self._c_ot = "#ff8585"
            self._c_ref_bg = "#1c2035"
        else:
            self._c_txt = "#1e2035"
            self._c_mut = "#7080a8"
            self._c_grid = "#e0e4f0"
            self._c_ref = "#b0b8cc"
            self._c_ot = "#e03333"
            self._c_ref_bg = "#f4f7ff"

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self._items:
            p.setPen(QColor(self._c_mut))
            p.setFont(QFont("sans-serif", 11))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self._no_data)
            p.end()
            return

        ml, mr, mt, mb = 46, 12, 24, 40
        cw = w - ml - mr
        ch = h - mt - mb
        vals = [v for _, v in self._items]
        max_v = max(max(vals, default=0), self._ref) * 1.18 or 10.0
        n = len(self._items)
        slot_w = cw / n
        bar_w = max(min(slot_w * 0.60, 40.0), 6.0)

        for i in range(6):
            frac = i / 5
            yy = mt + ch * (1 - frac)
            p.setPen(QPen(QColor(self._c_grid), 1))
            p.drawLine(ml, int(yy), ml + cw, int(yy))
            p.setPen(QColor(self._c_mut))
            p.setFont(QFont("sans-serif", 8))
            lbl = f"{max_v * frac:.0f}{self._unit}"
            fm = QFontMetrics(p.font())
            p.drawText(2, int(yy) + fm.ascent() // 2, lbl)

        if 0 < self._ref <= max_v:
            ry = mt + ch * (1 - self._ref / max_v)
            p.setPen(QPen(QColor(self._c_ref), 1.5, Qt.DashLine))
            p.drawLine(ml, int(ry), ml + cw, int(ry))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(self._c_ref_bg)))
            ref_text = f"{self._ref:.1f}{self._unit}"
            p.setFont(QFont("sans-serif", 8))
            fm_ref = QFontMetrics(p.font())
            pad_x = 6
            label_w = fm_ref.horizontalAdvance(ref_text) + pad_x * 2
            label_h = fm_ref.height() + 2
            label_x = max(ml + 4, ml + cw - label_w - 2)
            label_y = max(2, min(int(ry - label_h - 2), h - label_h - 2))
            p.drawRoundedRect(QRectF(label_x, label_y, label_w, label_h), 5, 5)
            p.setPen(QColor(self._c_ref))
            p.drawText(
                QRectF(label_x, label_y, label_w, label_h),
                Qt.AlignCenter, ref_text
            )

        for i, (label, val) in enumerate(self._items):
            bh = (min(val, max_v) / max_v) * ch
            x = ml + i * slot_w + (slot_w - bar_w) / 2
            y = mt + ch - bh
            c = QColor(self._c_ot if val > self._ref else self._acc)
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            if bh > 0:
                p.drawRoundedRect(QRectF(x, y, bar_w, bh), 3, 3)
            if val > 0:
                p.setPen(QColor(self._c_txt))
                p.setFont(QFont("sans-serif", 8))
                vs = f"{val:.1f}"
                fm = QFontMetrics(p.font())
                p.drawText(
                    int(x + bar_w / 2 - fm.horizontalAdvance(vs) / 2),
                    int(y) - 3, vs)
            p.setPen(QColor(self._c_mut))
            p.setFont(QFont("sans-serif", 8))
            fm2 = QFontMetrics(p.font())
            tw = fm2.horizontalAdvance(label)
            p.drawText(int(x + bar_w / 2 - tw / 2),
                       h - mb + fm2.ascent() + 3, label)
        p.end()
