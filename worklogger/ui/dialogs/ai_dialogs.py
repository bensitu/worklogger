"""AI progress and result dialogs.

``AIProgressDialog.run()`` is the single dispatch point for all AI requests.
It inspects ``api_key`` against ``LOCAL_MODEL_SENTINEL``:

* sentinel  → ``LocalModelWorker`` (on-device inference, no network)
* anything else → ``AIWorker``   (external API call)

On local model failure the dialog appends a toast message explaining the
fallback so the user always understands what channel was actually used.
"""

from __future__ import annotations
from typing import Callable

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config.i18n import T
from services.ai_service import AIWorker, LocalModelWorker
from services.local_model_service import LOCAL_MODEL_SENTINEL
from utils.ai_status_formatter import parse_status

# Keys emitted by LocalModelWorker that signal a failed local inference attempt.
_LOCAL_FAIL_KEYS = frozenset({
    "local_model_load_fail",
    "local_model_not_downloaded",
    "local_model_import_error",
})


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
        msg = t.get(text_key, text_key)
        try:
            msg = msg.format(**kwargs)
        except Exception:
            pass
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
        QApplication.processEvents()

    def set_error(self, short_key: str, detail: str):
        t = T[self.lang]
        short = t.get(short_key, short_key)
        self.append(f"\n[ERROR] {short}")
        if detail:
            self.log.append(detail)
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
            on_success: Callable[[str], None],
            services=None):
        """Dispatch an AI request and show progress.

        Routes to ``LocalModelWorker`` when *api_key* is the local sentinel,
        otherwise uses the network ``AIWorker``.

        Fallback
        --------
        When local inference fails (load error, OOM, file missing …), this
        method automatically re-tries with the configured external model.
        The user sees a toast in the log and the dialog continues seamlessly.
        """
        dlg       = cls(parent, lang, title)
        use_local = (api_key == LOCAL_MODEL_SENTINEL)

        dlg.append("local_model_loading" if use_local else "ai_init")
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
            t = T[lang]
            if short in _LOCAL_FAIL_KEYS:
                # ── Automatic fallback to external model ──────────────────
                # 1. Tell user what happened.
                dlg.append("local_model_fallback_toast")
                # 2. Fetch real external params (api_key here is the sentinel).
                if services is not None:
                    try:
                        ext_key, ext_url, ext_mdl = services.get_setting(
                            "ai_api_key", ""), services.get_setting(
                            "ai_base_url", ""), services.get_setting(
                            "ai_model", "")
                    except Exception:
                        ext_key, ext_url, ext_mdl = "", "", ""
                else:
                    ext_key, ext_url, ext_mdl = "", "", ""

                if ext_key and ext_url and ext_mdl:
                    # 3. Start external worker; reuse the same dialog.
                    dlg.append("ai_init")
                    dlg._timeout_timer.start(30000)
                    dlg._worker = AIWorker(
                        ext_key, ext_url, ext_mdl, messages,
                        on_done, on_error_external, max_tokens=2048,
                        on_status=on_status,
                    )
                else:
                    # No external model configured — show error and stop.
                    friendly = t.get(short, short)
                    dlg.set_error(friendly, detail)
                    dlg.cancel_btn.setEnabled(True)
            else:
                dlg.set_error(short, detail)
                dlg.cancel_btn.setEnabled(True)

        def on_error_external(short: str, detail: str):
            """Error handler for the fallback external-model attempt."""
            dlg._timeout_timer.stop()
            dlg.set_error(short, detail)
            dlg.cancel_btn.setEnabled(True)

        # max_tokens for local: use n_ctx-aware value from catalog if available
        local_max_tokens = 4096
        if services is not None:
            try:
                from services.local_model_service import (
                    get_active_entry_id, get_catalog_entry,
                )
                eid   = get_active_entry_id()
                cat   = get_catalog_entry(eid)
                # Use catalog max_tokens if set, else n_ctx - overhead
                n_ctx = int(cat.get("n_ctx", 32768))
                local_max_tokens = int(
                    cat.get("max_tokens", min(n_ctx - 512, 8192))
                )
            except Exception:
                pass

        if use_local:
            dlg._worker = LocalModelWorker(
                messages, on_done, on_error,
                services=services,
                max_tokens=local_max_tokens,
                temperature=0.3,
                on_status=on_status,
            )
        else:
            dlg._worker = AIWorker(
                api_key, base_url, model, messages,
                on_done, on_error, max_tokens=2048,
                on_status=on_status,
            )
        dlg.exec()
        dlg._worker = None


class AIResultDialog(QDialog):
    def __init__(self, parent, lang: str, original: str,
                 generated: str, on_regenerate: Callable):
        super().__init__(parent)
        self.lang = lang
        self.on_regenerate = on_regenerate
        self.setWindowTitle(T[lang].get("ai_result_title", "AI Result"))
        self.setMinimumSize(800, 500)
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_w = QWidget()
        ll = QVBoxLayout(left_w)
        lbl_l = QLabel(T[lang].get("original_content", "Original"))
        lbl_l.setObjectName("muted")
        ll.addWidget(lbl_l)
        self.original_edit = QTextEdit()
        self.original_edit.setPlainText(original)
        self.original_edit.setReadOnly(True)
        self.original_edit.setFont(QFont("monospace", 10))
        ll.addWidget(self.original_edit)

        right_w = QWidget()
        rl = QVBoxLayout(right_w)
        lbl_r = QLabel(T[lang].get("ai_generated", "AI Generated"))
        lbl_r.setObjectName("muted")
        rl.addWidget(lbl_r)
        self.generated_edit = QTextEdit()
        self.generated_edit.setPlainText(generated)
        self.generated_edit.setFont(QFont("monospace", 10))
        rl.addWidget(self.generated_edit)

        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        layout.addWidget(splitter, 1)

        btn_layout = QHBoxLayout()
        self.apply_btn      = QPushButton(T[lang].get("apply",      "Apply"))
        self.regenerate_btn = QPushButton(T[lang].get("regenerate", "Regenerate"))
        self.cancel_btn     = QPushButton(T[lang].get("btn_cancel", "Cancel"))
        self.apply_btn.setObjectName("primary_btn")
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
