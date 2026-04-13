"""WorkLogger — entry point."""

import sys

# Windows needs the AppUserModelID before QApplication for the taskbar icon.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "dev.worklogger.app.v1")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication

from utils.icon import make_icon
from ui.main_window import App


def _bootstrap() -> None:
    """Run one-time setup tasks before the Qt app starts.

    Called once at process start, before ``QApplication`` is created.
    Errors are silently swallowed — bootstrap failures must never prevent
    the app from launching.
    """
    try:
        # Ensure catalog.json is present in the user's models directory.
        # On a frozen (PyInstaller) first run the file lives only inside
        # sys._MEIPASS and must be copied out to the persistent location.
        from services.local_model_service import ensure_catalog
        ensure_catalog()
    except Exception:
        pass


def main():
    _bootstrap()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon = make_icon()
    app.setWindowIcon(icon)
    w = App()
    w.setWindowIcon(icon)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
