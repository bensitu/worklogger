"""Notes workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol

from PySide6.QtWidgets import QWidget

from worklogger.presentation.notes.dialog import NoteEditorDialog
from worklogger.presentation.viewmodels import NoteEditorViewModel


class NotesWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> NoteEditorDialog:
        ...


NoteEditorDialogFactory = Callable[
    [NoteEditorViewModel, date, QWidget | None],
    NoteEditorDialog,
]


class NotesWorkflowController:
    def __init__(
        self,
        view_model: NoteEditorViewModel,
        *,
        dialog_factory: NoteEditorDialogFactory | None = None,
        after_save: Callable[[], None] | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or NoteEditorDialog
        self._after_save = after_save

    def open(self, day: date, parent: QWidget | None = None) -> NoteEditorDialog:
        dialog = self._dialog_factory(self._view_model, day, parent)
        if self._after_save is not None:
            dialog.saved.connect(self._after_save)
        dialog.refresh()
        dialog.exec()
        return dialog
