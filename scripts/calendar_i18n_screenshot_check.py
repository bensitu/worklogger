from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "worklogger"
ARTIFACT_DIR = ROOT / "tests" / "_artifacts"


def _assert_no_i18n_header_text(window) -> None:
    bad_markers = ("Language:", "Content-Type: text/plain; charset=UTF-8")
    for btn in getattr(window, "_day_btns", []):
        text = btn.text()
        if any(marker in text for marker in bad_markers):
            raise AssertionError(
                f"Calendar cell contains i18n header text: {text!r}"
            )


def _render_and_capture(window, lang_code: str, file_tag: str) -> Path:
    window.lang = lang_code
    window.apply_lang()
    window.render()
    QApplication.processEvents()
    _assert_no_i18n_header_text(window)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACT_DIR / f"calendar_view_{file_tag}.png"
    pix = window.grab()
    if not pix.save(str(out_path)):
        raise RuntimeError(f"Failed to save screenshot: {out_path}")
    return out_path


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import sys

    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))

    from ui.main_window import App

    app = QApplication.instance() or QApplication([])
    window = App()
    window.show()
    QApplication.processEvents()

    captures = [
        ("en_US", "en-US"),
        ("zh_CN", "zh-CN"),
        ("xx_XX", "xx_XX"),
    ]
    saved: list[Path] = []
    for lang_code, tag in captures:
        saved.append(_render_and_capture(window, lang_code, tag))

    window.close()
    for path in saved:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
