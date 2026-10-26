from concurrent.futures import ThreadPoolExecutor
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

from worklogger._vendor.pyglass.refract import array_to_qimage, qimage_to_array
from worklogger.presentation.theme.glass_renderer import GLASS_PADDING, MAX_GLASS_PIXELS, render_glass
from worklogger.presentation.theme import ThemeEngine


class GlassRendererTests(unittest.TestCase):
    def test_image_conversion_preserves_pixels_and_detaches_buffers(self):
        image = QImage(17, 13, QImage.Format.Format_ARGB32)
        image.fill(QColor("#137687"))
        array = qimage_to_array(image)
        restored = array_to_qimage(array)
        array[:] = 0
        image.fill(QColor("#ffffff"))
        self.assertEqual(restored.pixelColor(8, 6).name(), "#137687")

    def test_background_rendering_is_bounded_and_runs_without_gui_widgets(self):
        width, height = 1200, 800
        source = QImage(width + GLASS_PADDING * 2, height + GLASS_PADDING * 2, QImage.Format.Format_ARGB32)
        gradient = QLinearGradient(QPointF(), QPointF(source.width(), source.height()))
        gradient.setColorAt(0, QColor("#152f51"))
        gradient.setColorAt(1, QColor("#bcddb8"))
        painter = QPainter(source)
        painter.fillRect(source.rect(), gradient)
        painter.end()
        with ThreadPoolExecutor(max_workers=1) as executor:
            rendered = executor.submit(render_glass, source, width, height, "#eef5f7").result()
        self.assertLessEqual(rendered.width() * rendered.height(), MAX_GLASS_PIXELS)
        self.assertFalse(rendered.isNull())
        self.assertNotEqual(rendered.pixelColor(10, 10), rendered.pixelColor(rendered.width() - 10, rendered.height() - 10))
        self.assertEqual(rendered.pixelColor(10, 10).alpha(), 255)
        with self.assertRaises(ValueError):
            render_glass(QImage(), width, height, "#ffffff")

    def test_glass_softens_structured_backgrounds_beyond_a_flat_tint(self):
        width, height = 200, 100
        source = QImage(width + 2 * GLASS_PADDING, height + 2 * GLASS_PADDING, QImage.Format.Format_ARGB32)
        source.fill(QColor("#ffffff"))
        painter = QPainter(source)
        for x in range(0, source.width(), 8):
            painter.fillRect(x, 0, 4, source.height(), QColor("#000000"))
        painter.end()
        tint = QColor("#eef5f7")
        baseline = source.copy(GLASS_PADDING, GLASS_PADDING, width, height)
        tint.setAlpha(160)
        painter = QPainter(baseline)
        painter.fillRect(baseline.rect(), tint)
        painter.end()
        rendered = render_glass(source, width, height, "#eef5f7")
        def contrast(image):
            values = [image.pixelColor(x, height // 2).lightnessF() for x in range(40, 160)]
            return max(values) - min(values)
        self.assertLess(contrast(rendered), contrast(baseline))
        source.fill(QColor("#000000"))
        self.assertNotEqual(rendered, render_glass(source, width, height, "#eef5f7"))

    def test_glass_tint_keeps_text_readable_over_extreme_backgrounds(self):
        def luminance(color):
            channels = (color.redF(), color.greenF(), color.blueF())
            return sum(weight * (channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
                       for channel, weight in zip(channels, (0.2126, 0.7152, 0.0722)))
        for dark, background in ((False, "#000000"), (True, "#ffffff")):
            colors = ThemeEngine().palette("liquid_glass", dark=dark)
            image = QImage(236, 136, QImage.Format.Format_ARGB32)
            image.fill(QColor(background))
            result = render_glass(image, 200, 100, colors.surface)
            values = sorted((luminance(QColor(colors.text)), luminance(result.pixelColor(100, 50))))
            self.assertGreaterEqual((values[1] + 0.05) / (values[0] + 0.05), 4.5)
