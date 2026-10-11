from concurrent.futures import ThreadPoolExecutor
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

from worklogger._vendor.pyglass.refract import array_to_qimage, qimage_to_array
from worklogger.presentation.theme.glass_renderer import GLASS_PADDING, MAX_GLASS_PIXELS, render_glass


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
