"""User documentation navigation shared by guidance and settings."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from worklogger.__about__ import GITHUB_URL


def open_user_guide():
    return QDesktopServices.openUrl(QUrl(GITHUB_URL + "/blob/main/docs/user-guide.md"))
