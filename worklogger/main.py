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


def main():
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
