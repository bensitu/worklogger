"""Qt's color picker localized through the application's gettext catalogs."""

from PySide6.QtCore import QTranslator
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QWidget

from worklogger.infrastructure.i18n import _


class _ColorDialogTranslator(QTranslator):
    def __init__(self) -> None:
        super().__init__()
        self._colors = {
            "Select Color": _("Choose custom color"),
            "Hu&e:": _("Hu&e:"),
            "&Sat:": _("&Sat:"),
            "&Val:": _("&Val:"),
            "&Red:": _("&Red:"),
            "&Green:": _("&Green:"),
            "Bl&ue:": _("Bl&ue:"),
            "A&lpha channel:": _("A&lpha channel:"),
            "&HTML:": _("&HTML:"),
            "&Basic colors": _("&Basic colors"),
            "&Custom colors": _("&Custom colors"),
            "&Add to Custom Colors": _("&Add to Custom Colors"),
            "&Pick Screen Color": _("&Pick Screen Color"),
            "Cursor at %1, %2\nPress ESC to cancel": _("Cursor at %1, %2\nPress ESC to cancel"),
        }
        self._buttons = {"OK": _("OK"), "Cancel": _("Cancel")}

    def isEmpty(self) -> bool:
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if context == "QColorDialog":
            return self._colors.get(source_text)
        if context in ("QPlatformTheme", "QDialogButtonBox"):
            return self._buttons.get(source_text)
        return None


def choose_custom_color(initial: QColor, parent: QWidget) -> QColor:
    translator = _ColorDialogTranslator()
    application = QApplication.instance()
    # Scope the adapter to this modal dialog; gettext remains the only catalog.
    application.installTranslator(translator)
    try:
        return QColorDialog.getColor(
            initial, parent, _("Choose custom color"),
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
    finally:
        application.removeTranslator(translator)
