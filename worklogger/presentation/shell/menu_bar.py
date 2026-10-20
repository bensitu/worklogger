"""Native application menus backed by existing window and editor operations."""

from collections.abc import Callable, Mapping
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QLineEdit, QMenuBar, QMessageBox,
    QPlainTextEdit, QTextEdit, QWidget,
)
from shiboken6 import isValid

from worklogger.__about__ import APP_AUTHOR, APP_NAME, APP_VERSION, GITHUB_URL
from worklogger.infrastructure.i18n import _

TextEditor = QLineEdit | QPlainTextEdit | QTextEdit


def install_application_menu(window, **callbacks):
    if sys.platform != "darwin":
        return None
    return ApplicationMenuController(window, **callbacks)


class ApplicationMenuController(QObject):
    def __init__(self, window: QWidget, *, new_record: Callable, save_target: Callable,
                 settings: Callable | None, routes: Mapping[str, Callable | None], quit_app: Callable):
        super().__init__(window)
        self._window = window
        self._save_target = save_target
        self._editor: TextEditor | None = None
        self._save_button: QAbstractButton | None = None
        self._disposed = False
        self._routes = routes
        self._dialog_bars = {}
        self.menu_bar = QMenuBar(None)
        self.menu_bar.setNativeMenuBar(True)
        self.actions: dict[str, QAction] = {}

        file_menu = self.menu_bar.addMenu(_("File"))
        self._action(file_menu, "new", _("New time record"), new_record, QKeySequence.StandardKey.New)
        self._action(file_menu, "save", _("Save"), self._save, QKeySequence.StandardKey.Save)
        self._action(file_menu, "close", _("Close window"), self._close, QKeySequence.StandardKey.Close)
        file_menu.addSeparator()
        self._action(file_menu, "about", _("About"), self._about, role=QAction.MenuRole.AboutRole)
        self._action(file_menu, "preferences", _("Settings"), settings,
                     QKeySequence.StandardKey.Preferences, QAction.MenuRole.PreferencesRole)
        self._action(file_menu, "quit", _("Quit"), quit_app,
                     QKeySequence.StandardKey.Quit, QAction.MenuRole.QuitRole)

        edit_menu = self.menu_bar.addMenu(_("Edit"))
        for key, label, shortcut in (
            ("undo", _("Undo"), QKeySequence.StandardKey.Undo),
            ("redo", _("Redo"), QKeySequence.StandardKey.Redo),
            ("cut", _("Cut"), QKeySequence.StandardKey.Cut),
            ("copy", _("Copy"), QKeySequence.StandardKey.Copy),
            ("paste", _("Paste"), QKeySequence.StandardKey.Paste),
            ("select_all", _("Select all"), QKeySequence.StandardKey.SelectAll),
        ):
            if key in {"cut", "select_all"}:
                edit_menu.addSeparator()
            self._action(edit_menu, key, label, lambda _checked=False, key=key: self._edit(key), shortcut)

        view_menu = self.menu_bar.addMenu(_("View"))
        for key, label in (("calendar", _("Calendar")), ("analytics", _("Analytics")),
                           ("reports", _("Reports")), ("settings", _("Settings"))):
            self._action(view_menu, key, label, routes.get(key))

        window_menu = self.menu_bar.addMenu(_("Window"))
        self._action(window_menu, "minimize", _("Minimize"), self._minimize, "Ctrl+M")
        self._action(window_menu, "show", _("Show main window"), self._show)

        help_menu = self.menu_bar.addMenu(_("Help"))
        self._action(help_menu, "homepage", _("Project homepage"),
                     lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        self._action(help_menu, "feedback", _("Report an issue"),
                     lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL + "/issues/new/choose")))

        self._menus = (file_menu, edit_menu, view_menu, window_menu, help_menu)
        for menu in self._menus:
            menu.aboutToShow.connect(self.refresh)
        self._settings_available = settings is not None
        self._window.installEventFilter(self)
        self._window.destroyed.connect(self.dispose)
        application = QApplication.instance()
        application.focusChanged.connect(self._focus_changed)
        application.clipboard().dataChanged.connect(self._refresh_paste)
        self._focus_changed(None, application.focusWidget())

    def _action(self, menu, key, label, callback, shortcut=None, role=QAction.MenuRole.NoRole):
        action = QAction(label, self)
        action.setMenuRole(role)
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if callback is not None:
            action.triggered.connect(callback)
        menu.addAction(action)
        self.actions[key] = action
        return action

    def _owns(self, widget):
        while widget is not None and isValid(widget):
            if widget is self._window:
                return True
            widget = widget.parentWidget()
        return False

    def _active_window(self):
        widget = QApplication.activeModalWidget() or QApplication.activeWindow()
        return widget if self._owns(widget) else None

    def _focused_editor(self):
        widget = QApplication.focusWidget()
        if (isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit)) and self._owns(widget)
                and widget.window() is self._active_window() and widget.isEnabled() and widget.isVisible()):
            return widget
        return None

    @Slot(QWidget, QWidget)
    def _focus_changed(self, _previous, _current):
        if self._disposed:
            return
        if self._editor is not None and isValid(self._editor):
            self._editor.textChanged.disconnect(self.refresh)
            self._editor.selectionChanged.disconnect(self.refresh)
        self._editor = self._focused_editor()
        if self._editor is not None:
            self._editor.textChanged.connect(self.refresh)
            self._editor.selectionChanged.connect(self.refresh)
        self.refresh()

    def _current_save_button(self):
        active = self._active_window()
        widget = QApplication.focusWidget()
        if widget is not None and widget.window() is not active:
            widget = None
        while widget is not None and self._owns(widget):
            button = getattr(widget, "save_button", None)
            if isinstance(button, QAbstractButton) and button.isVisible():
                return button
            widget = widget.parentWidget()
        if active is not None and active is not self._window:
            button = getattr(active, "save_button", None)
            return button if isinstance(button, QAbstractButton) and button.isVisible() else None
        return self._save_target() if active is self._window else None

    def _ensure_window_menu(self, active):
        if active is None or active is self._window or active in self._dialog_bars:
            return
        bar = QMenuBar(active)
        bar.setNativeMenuBar(True)
        self._dialog_bars[active] = bar
        for source in self._menus:
            menu = bar.addMenu(source.title())
            for action in source.actions():
                menu.addAction(action)
            menu.aboutToShow.connect(self.refresh)
        active.destroyed.connect(lambda _object=None, active=active: self._dialog_bars.pop(active, None))

    @Slot()
    def refresh(self):
        if self._disposed or not isValid(self._window) or not isValid(self.menu_bar):
            return
        active = self._active_window()
        self._ensure_window_menu(active)
        main_active = active is self._window and self._window.isVisible() and QApplication.activeModalWidget() is None
        self.actions["new"].setEnabled(main_active and not self._window.entry_panel.is_busy)
        self.actions["preferences"].setEnabled(main_active and self._settings_available)
        for key in ("calendar", "analytics", "reports", "settings"):
            self.actions[key].setEnabled(main_active and self._routes.get(key) is not None)
        self.actions["close"].setEnabled(active is not None and active.isVisible())
        self.actions["minimize"].setEnabled(main_active)
        self.actions["quit"].setEnabled(QApplication.activeModalWidget() is None)

        button = self._current_save_button()
        if button is not self._save_button:
            if self._save_button is not None and isValid(self._save_button):
                self._save_button.removeEventFilter(self)
            self._save_button = button
            if button is not None:
                button.installEventFilter(self)
        self.actions["save"].setEnabled(button is not None and button.isEnabled() and button.isVisible())

        editor = self._focused_editor()
        editable = editor is not None and not editor.isReadOnly()
        if isinstance(editor, QLineEdit):
            selection = editor.hasSelectedText() and editor.echoMode() == QLineEdit.EchoMode.Normal
            undo, redo = editor.isUndoAvailable(), editor.isRedoAvailable()
            text = bool(editor.text())
        elif editor is not None:
            selection = editor.textCursor().hasSelection()
            undo, redo = editor.document().isUndoAvailable(), editor.document().isRedoAvailable()
            text = not editor.document().isEmpty()
        else:
            selection = undo = redo = text = False
        self.actions["undo"].setEnabled(editable and undo)
        self.actions["redo"].setEnabled(editable and redo)
        self.actions["cut"].setEnabled(editable and selection)
        self.actions["copy"].setEnabled(selection)
        clipboard = QApplication.clipboard().mimeData()
        can_paste = clipboard is not None and (clipboard.hasText() if isinstance(editor, QLineEdit) else
                                               editor.canPaste() if editor is not None else False)
        self.actions["paste"].setEnabled(editable and can_paste)
        self.actions["select_all"].setEnabled(editor is not None and text)

    @Slot()
    def _refresh_paste(self):
        if self._disposed:
            return
        editor = self._focused_editor()
        clipboard = QApplication.clipboard().mimeData()
        can_paste = clipboard is not None and (clipboard.hasText() if isinstance(editor, QLineEdit) else
                                               editor.canPaste() if editor is not None else False)
        self.actions["paste"].setEnabled(editor is not None and not editor.isReadOnly() and can_paste)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.EnabledChange, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowActivate):
            self.refresh()
        return False

    def _edit(self, operation):
        self.refresh()
        editor = self._focused_editor()
        if editor is not None and self.actions[operation].isEnabled():
            getattr(editor, "selectAll" if operation == "select_all" else operation)()
            self.refresh()

    def _save(self):
        self.refresh()
        button = self._current_save_button()
        if button is not None and button.isEnabled() and button.isVisible():
            button.click()

    def _close(self):
        active = self._active_window()
        if active is not None:
            active.close()

    def _minimize(self):
        if self._active_window() is self._window:
            self._window.showMinimized()

    def _show(self):
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def _about(self):
        QMessageBox.about(self._window, _("About"),
                          APP_NAME + "\n" + _("Version {version}").format(version=APP_VERSION) + "\n" + APP_AUTHOR)

    @Slot()
    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        for bar in (self.menu_bar, *self._dialog_bars.values()):
            if isValid(bar):
                bar.clear()
                bar.deleteLater()
        self._dialog_bars.clear()
