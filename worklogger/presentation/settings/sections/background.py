"""Account background controls bound to the asynchronous shell workflow."""

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QWidget,
)

from worklogger.domain.settings.background import BackgroundState
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.settings.sections.common import (
    _secondary_label,
    _section_title,
    _switch_line,
)
from worklogger.presentation.widgets import CardFrame, SwitchButton
from worklogger.presentation.widgets.icons import set_button_icon


class BackgroundSettings(CardFrame):
    def __init__(self):
        super().__init__(object_name="settings_content_frame")
        self._controller = None
        self._state = BackgroundState()
        self._loaded = False
        self.content_layout.addWidget(_section_title(_("Background image")))
        self.enabled_switch = SwitchButton()
        self.enabled_switch.setAccessibleName(_("Enable background image"))
        self.content_layout.addWidget(_switch_line(_("Enable background image"), self.enabled_switch))
        self.image_label = _secondary_label(_("No background image"))
        self.content_layout.addWidget(self.image_label)

        opacity_row = QWidget()
        opacity_row.setObjectName("settings_switch_row_widget")
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.addWidget(QLabel(_("Image opacity")))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("background_opacity_slider_widget")
        self.opacity_slider.setMinimumHeight(24)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.setTracking(False)
        self.opacity_slider.setAccessibleName(_("Image opacity"))
        self.opacity_label = QLabel("50%")
        self.opacity_label.setFixedWidth(50)
        self.opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        opacity_layout.addWidget(self.opacity_slider, 1)
        opacity_layout.addWidget(self.opacity_label)
        self.content_layout.addWidget(opacity_row)

        buttons = QHBoxLayout()
        self.upload_button = QPushButton(_("Upload image"))
        set_button_icon(self.upload_button, "upload")
        self.remove_button = QPushButton(_("Remove image"))
        self.remove_button.setProperty("variant", "danger")
        set_button_icon(self.remove_button, "trash")
        buttons.addWidget(self.upload_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        self.content_layout.addLayout(buttons)
        self.status_label = _secondary_label("")
        self.status_label.hide()
        self.content_layout.addWidget(self.status_label)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_options)
        self.enabled_switch.toggled.connect(self._save_options)
        self.opacity_slider.valueChanged.connect(self._opacity_changed)
        self.upload_button.clicked.connect(self._upload)
        self.remove_button.clicked.connect(self._remove)
        self.hide()

    def bind(self, controller):
        self._controller = controller
        self.setVisible(controller.available)
        controller.busy_changed.connect(self._set_busy)
        controller.completed.connect(self._complete)
        self._set_busy(controller.is_busy)

    def _set_busy(self, busy):
        if busy:
            self._save_timer.stop()
            self.status_label.setText(_("Processing"))
            self.status_label.show()
        available = self._controller is not None and self._controller.available and not busy
        has_image = self._loaded and self._state.image is not None
        self.upload_button.setEnabled(available)
        self.remove_button.setEnabled(available and has_image)
        self.enabled_switch.setEnabled(available and has_image)
        self.opacity_slider.setEnabled(available and has_image)

    def _sync_state(self):
        with QSignalBlocker(self.enabled_switch), QSignalBlocker(self.opacity_slider):
            self.enabled_switch.setChecked(self._state.enabled)
            self.opacity_slider.setValue(self._state.opacity)
        self.opacity_label.setText(f"{self._state.opacity}%")
        image = self._state.image
        self.image_label.setText(
            f"{image.format.upper()} | {image.width} x {image.height}" if image else _("No background image")
        )

    def _complete(self, result):
        if result.ok:
            self._state = result.value
            self._loaded = True
            self.status_label.clear()
            self.status_label.hide()
        else:
            self.status_label.setText(display_error_message(result.error))
            self.status_label.show()
        self._sync_state()

    def _opacity_changed(self, value):
        self.opacity_label.setText(f"{value}%")
        self._save_timer.start()

    def _save_options(self):
        self._save_timer.stop()
        if self._controller is not None and self._state.image is not None:
            self._controller.set_options(enabled=self.enabled_switch.isChecked(), opacity=self.opacity_slider.value())

    def _upload(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Upload image"), "", _("Images (*.png *.jpg *.jpeg *.gif *.webp)")
        )
        if path:
            self._controller.import_image(path)

    def _remove(self):
        if QMessageBox.question(self, _("Remove image"), _("Remove background image?"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._controller.clear()
