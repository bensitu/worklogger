"""Account background controls bound to the asynchronous shell workflow."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
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
from worklogger.presentation.settings.sections.layouts import SettingsActionGroup, SettingsContainer


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
        self.options_widget = SettingsContainer("background_image_options_widget")
        options_layout = QVBoxLayout(self.options_widget)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(12)
        self.options_widget.hide()
        self.content_layout.addWidget(self.options_widget)
        self.image_label = _secondary_label(_("No background image"))
        options_layout.addWidget(self.image_label)

        opacity_row = SettingsContainer("background_opacity_row_widget")
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

        self.upload_button = QPushButton(_("Upload image"))
        set_button_icon(self.upload_button, "upload")
        self.remove_button = QPushButton(_("Remove image"))
        self.remove_button.setProperty("variant", "danger")
        set_button_icon(self.remove_button, "trash")
        options_layout.addWidget(SettingsActionGroup((self.upload_button, self.remove_button)))
        options_layout.addWidget(opacity_row)
        self.status_label = _secondary_label("")
        self.status_label.hide()
        self.content_layout.addWidget(self.status_label)
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
        if controller.last_result is not None:
            self._complete(controller.last_result)
        self._set_busy(controller.is_busy)

    def _set_busy(self, busy):
        if busy and self._controller is not None and self._controller.is_saving_options:
            return
        if busy:
            self.status_label.setText(_("Processing"))
            self.status_label.show()
        available = self._controller is not None and self._controller.available and not busy
        has_image = self._loaded and self._state.image is not None
        self.upload_button.setEnabled(available and self._state.enabled)
        self.remove_button.setEnabled(available and self._state.enabled and has_image)
        self.enabled_switch.setEnabled(available and self._loaded)
        self.opacity_slider.setEnabled(available and self._state.enabled)

    def showEvent(self, event):
        super().showEvent(event)
        controller = self._controller
        if (not self._loaded and controller is not None and controller.available
                and not controller.is_busy):
            controller.reload()

    def _sync_state(self):
        self.options_widget.setVisible(self._state.enabled)
        with QSignalBlocker(self.enabled_switch), QSignalBlocker(self.opacity_slider):
            self.enabled_switch.setChecked(self._state.enabled)
            if not self.opacity_slider.isSliderDown():
                self.opacity_slider.setValue(self._state.opacity)
        self.opacity_label.setText(f"{self.opacity_slider.sliderPosition()}%")
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
        self._save_options()

    def _save_options(self):
        if self._controller is not None and self._loaded:
            self._controller.set_options(enabled=self.enabled_switch.isChecked(), opacity=self.opacity_slider.value())

    def _upload(self):
        if self._controller is None or not self._state.enabled:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Upload image"), "", _("Images (*.png *.jpg *.jpeg *.gif *.webp)")
        )
        if path:
            self._controller.import_image(path)

    def _remove(self):
        if self._controller is None or not self._state.enabled or self._state.image is None:
            return
        if QMessageBox.question(self, _("Remove image"), _("Remove background image?"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._controller.clear()
