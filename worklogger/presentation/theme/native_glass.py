"""Optional macOS glass adapter with reversible widget and window changes."""

from importlib import import_module
import logging
import sys

from PySide6.QtCore import Qt
from shiboken6 import isValid

LOGGER = logging.getLogger(__name__)
_MISSING = object()


def _load_backend():
    if sys.platform != "darwin" or sys.version_info < (3, 12):
        return None
    try:
        backend = import_module("pyqt_liquidglass")
        if not (backend.HAS_GLASS_EFFECT or backend.HAS_VISUAL_EFFECT):
            return None
        bridge = import_module("pyqt_liquidglass._bridge")
        return backend, bridge.get_nswindow_from_widget
    except (ImportError, OSError):
        return None


class NativeGlassAdapter:
    def __init__(self, target, *, backend_factory=None):
        self.target = target
        self._factory = backend_factory or _load_backend
        self._backend = None
        self._effect = None
        self._saved = None
        self._failed = False
        self._dark = None

    @property
    def active(self):
        return self._effect is not None

    def apply(self, *, dark=False):
        if self.active:
            self._update_appearance(dark)
            return True
        if self._failed or not isValid(self.target) or not self.target.isVisible():
            return self.active
        try:
            resolved = self._factory()
        except Exception:
            resolved = None
        if resolved is None:
            self._failed = True
            return False
        self._backend, get_window = resolved
        attributes = (Qt.WidgetAttribute.WA_NativeWindow, Qt.WidgetAttribute.WA_TranslucentBackground)
        self._saved = ({name: self.target.__dict__.get(name, _MISSING) for name in
                        ("resizeEvent", "moveEvent", "_glass_view", "_update_glass_frame")},
                       {attribute: self.target.testAttribute(attribute) for attribute in attributes})
        try:
            window = get_window(self.target)
        except Exception:
            self._failed = True
            self._restore_widget()
            return False
        mask = window.styleMask() if window is not None else None
        titlebar = window.titlebarAppearsTransparent() if window is not None else None
        try:
            options = self._backend.GlassOptions(corner_radius=8, blending_mode=self._backend.BlendingMode.WITHIN_WINDOW)
            self._backend.prepare_widget_for_glass(self.target)
            self._effect = self._backend.apply_glass_to_widget(self.target, options=options)
            if self._effect is None:
                self._failed = True
                self._restore_widget()
        except Exception:
            LOGGER.warning("native_glass_unavailable")
            self._failed = True
            self.remove()
        finally:
            if window is not None:
                try:
                    window.setStyleMask_(mask)
                    window.setTitlebarAppearsTransparent_(titlebar)
                except Exception:
                    LOGGER.warning("native_glass_window_restore_failed")
        if self.active:
            self._update_appearance(dark)
        return self.active

    def _update_appearance(self, dark):
        if self._dark == dark:
            return
        try:
            appkit = import_module("AppKit")
            name = appkit.NSAppearanceNameDarkAqua if dark else appkit.NSAppearanceNameAqua
            self.target._glass_view.setAppearance_(appkit.NSAppearance.appearanceNamed_(name))
            self._dark = dark
        except Exception:
            LOGGER.debug("native_glass_appearance_unavailable")

    def _restore_widget(self):
        if self._saved is None or not isValid(self.target):
            return
        methods, attributes = self._saved
        for name, value in methods.items():
            if value is _MISSING:
                self.target.__dict__.pop(name, None)
            else:
                setattr(self.target, name, value)
        for attribute, value in attributes.items():
            self.target.setAttribute(attribute, value)
        self._saved = None

    def remove(self):
        if self._effect is not None:
            try:
                self._backend.remove_glass_effect(self._effect)
            except Exception:
                LOGGER.warning("native_glass_cleanup_failed")
        self._effect = None
        self._dark = None
        self._restore_widget()
