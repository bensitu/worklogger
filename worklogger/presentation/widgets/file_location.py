"""Copyable file locations grouped with a directory-opening action."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from worklogger.presentation.widgets.icons import set_button_icon


class FileLocationPanel(QFrame):
    open_failed = Signal()

    def __init__(self, path: Path, caption: str, action: str, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setProperty("role", "readonly_location")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        label = QLabel(caption)
        label.setWordWrap(True)
        header.addWidget(label, 1)
        self.open_button = QPushButton(action)
        self.open_button.setProperty("variant", "outline")
        self.open_button.setAutoDefault(False)
        set_button_icon(self.open_button, "folder-open")
        header.addWidget(self.open_button)
        layout.addLayout(header)
        self.path_view = QPlainTextEdit(str(path))
        self.path_view.setReadOnly(True)
        self.path_view.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.path_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.path_view.setFixedHeight(self.path_view.fontMetrics().lineSpacing() * 3 + 8)
        self.path_view.setToolTip(str(path))
        self.path_view.setAccessibleName(caption)
        self.path_view.setProperty("role", "readonly_location_path")
        layout.addWidget(self.path_view)
        self.open_button.clicked.connect(self.open_directory)

    def open_directory(self):
        try:
            directory = self.path.parent
            while not directory.is_dir() and directory.parent != directory:
                directory = directory.parent
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                return
        except OSError:
            pass
        self.open_failed.emit()
