from __future__ import annotations
from typing import Callable

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config.i18n import T
from services.ai_service import AIWorker
from utils.ai_status_formatter import parse_status


class AIProgressDialog(QDialog):
    def __init__(self, parent, lang: str, title: str):
        super().__init__(parent)
        self._cancelled = False
        self.lang = lang
        self.setWindowTitle(title)
        self.setMinimumSize(500, 400)
        self.resize(550, 450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace", 9))
        layout.addWidget(self.log, 1)

        self.cancel_btn = QPushButton(T[lang].get("btn_cancel", "Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self._worker = None
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

    def append(self, text_key: str, **kwargs):
        t = T[self.lang]
        msg = t.get(text_key, text_key).format(**kwargs)
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
        QApplication.processEvents()

    def set_error(self, short_key: str, detail: str):
        t = T[self.lang]
        short = t.get(short_key, short_key)
        self.append(f"\n[ERROR] {short}")
        if detail:
            self.append(detail)
        self.cancel_btn.setText(t.get("btn_close", "Close"))
        self._timeout_timer.stop()

    def _on_timeout(self):
        self.append("ai_timeout_warning")
        self._timeout_timer.start(60000)

    def reject(self):
        self._cancelled = True
        super().reject()

    @classmethod
    def run(cls, parent, lang: str, title: str,
            api_key: str, base_url: str, model: str,
            messages: list[dict],
            on_success: Callable[[str], None]):
        dlg = cls(parent, lang, title)
        dlg.append("ai_init")
        dlg._timeout_timer.start(30000)

        def on_status(msg_en: str):
            dlg._timeout_timer.start(30000)
            key, kw = parse_status(msg_en)
            if key:
                try:
                    dlg.append(key, **kw)
                except Exception:
                    dlg.log.append(msg_en)
            else:
                dlg.log.append(kw.get("raw", msg_en))
            sb = dlg.log.verticalScrollBar()
            sb.setValue(sb.maximum())
            QApplication.processEvents()

        def on_done(text: str):
            if dlg._cancelled:
                return
            dlg.append("ai_success")
            dlg._timeout_timer.stop()
            on_success(text)
            dlg.accept()

        def on_error(short: str, detail: str):
            dlg._timeout_timer.stop()
            dlg.set_error(short, detail)
            dlg.cancel_btn.setEnabled(True)

        dlg._worker = AIWorker(
            api_key, base_url, model, messages,
            on_done, on_error, max_tokens=2048,
            on_status=on_status
        )
        dlg.exec()
        dlg._worker = None


class AIResultDialog(QDialog):
    def __init__(self, parent, lang: str, original: str, generated: str, on_regenerate: Callable):
        super().__init__(parent)
        self.lang = lang
        self.original = original
        self.generated = generated
        self.on_regenerate = on_regenerate
        self.setWindowTitle(T[lang].get("ai_result_title", "AI Result"))
        self.setMinimumSize(800, 500)
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_label = QLabel(T[lang].get("original_content", "Original"))
        left_label.setObjectName("muted")
        left_layout.addWidget(left_label)
        self.original_edit = QTextEdit()
        self.original_edit.setPlainText(original)
        self.original_edit.setReadOnly(True)
        self.original_edit.setFont(QFont("monospace", 10))
        left_layout.addWidget(self.original_edit)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_label = QLabel(T[lang].get("ai_generated", "AI Generated"))
        right_label.setObjectName("muted")
        right_layout.addWidget(right_label)
        self.generated_edit = QTextEdit()
        self.generated_edit.setPlainText(generated)
        self.generated_edit.setFont(QFont("monospace", 10))
        right_layout.addWidget(self.generated_edit)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        layout.addWidget(splitter, 1)

        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton(T[lang].get("apply", "Apply"))
        self.apply_btn.setObjectName("primary_btn")
        self.regenerate_btn = QPushButton(
            T[lang].get("regenerate", "Regenerate"))
        self.cancel_btn = QPushButton(T[lang].get("btn_cancel", "Cancel"))
        btn_layout.addStretch()
        btn_layout.addWidget(self.regenerate_btn)
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.apply_btn.clicked.connect(self.accept)
        self.regenerate_btn.clicked.connect(self._regenerate)
        self.cancel_btn.clicked.connect(self.reject)

    def _regenerate(self):
        self.close()
        QTimer.singleShot(0, self.on_regenerate)
