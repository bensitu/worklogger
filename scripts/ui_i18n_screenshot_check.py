from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "worklogger"
ARTIFACT_DIR = ROOT / "tests" / "_artifacts"


def _save(widget, name: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_DIR / name
    pix = widget.grab()
    if not pix.save(str(out)):
        raise RuntimeError(f"Failed to save screenshot: {out}")
    return out


def _assert_localized(window, settings_dlg) -> None:
    if window.lbl_wt.text() == "Work type":
        raise AssertionError("Main window work type label is still English.")
    options = {window.wt_combo.itemText(i) for i in range(window.wt_combo.count())}
    english = {"Normal", "Remote work", "Business trip", "Paid leave", "Comp leave", "Sick leave"}
    if not options.isdisjoint(english):
        raise AssertionError(f"Main window work type options contain English values: {options & english}")
    if settings_dlg._check_upd_btn.text() == "Check for Updates":
        raise AssertionError("Settings About update button is still English.")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import sys

    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))

    from ui.main_window import App
    from ui.dialogs.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    window = App()
    window.show()
    QApplication.processEvents()

    saved: list[Path] = []
    for lang, tag in (("ja_JP", "ja-JP"), ("ko_KR", "ko-KR"), ("zh_TW", "zh-TW")):
        window.lang = lang
        window.apply_lang()
        window.render()
        QApplication.processEvents()
        dlg = SettingsDialog(window)
        dlg.show()
        QApplication.processEvents()
        _assert_localized(window, dlg)
        saved.append(_save(window, f"main_window_{tag}.png"))
        saved.append(_save(dlg, f"settings_about_{tag}.png"))
        dlg.close()

    window.close()
    for p in saved:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
