"""Global application sidebar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from worklogger.__about__ import APP_NAME
from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets._style import refresh_style
from worklogger.presentation.widgets.assets import pixmap_asset


class SidebarWidget(QFrame):
    route_changed = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        account_name: str = "",
        role: str = "Admin",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("app_sidebar_frame")
        self._buttons: dict[str, QPushButton] = {}
        self._active_route = "calendar"
        self._build_ui(account_name=account_name, role=role)
        self.set_active_route("calendar")

    @property
    def active_route(self) -> str:
        return self._active_route

    def set_profile(self, account_name: str, role: str = "Admin") -> None:
        name = str(account_name or "").strip() or _("Local user")
        self.profile_name_label.setText(name)
        self.profile_role_label.setText(_("Admin") if role == "Admin" else role)
        if self.profile_avatar_label.pixmap() is None:
            self.profile_avatar_label.setText(_initials(name))

    def set_active_route(self, route: str) -> None:
        normalized = str(route or "calendar").strip().lower()
        if normalized not in self._buttons:
            normalized = "calendar"
        self._active_route = normalized
        for key, button in self._buttons.items():
            button.setProperty("active", key == normalized)
            refresh_style(button)

    def _build_ui(self, *, account_name: str, role: str) -> None:
        self.setFixedWidth(154)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 16)
        layout.setSpacing(12)

        self.product_label = QLabel(APP_NAME)
        self.product_label.setObjectName("sidebar_product_label")
        self.product_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.product_label)

        self.profile_avatar_label = QLabel("")
        self.profile_avatar_label.setObjectName("sidebar_avatar_label")
        self.profile_avatar_label.setFixedSize(72, 72)
        self.profile_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar = pixmap_asset("images/avatar.webp")
        if not avatar.isNull():
            self.profile_avatar_label.setPixmap(
                avatar.scaled(
                    72,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(self.profile_avatar_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.profile_name_label = QLabel("")
        self.profile_name_label.setObjectName("sidebar_name_label")
        self.profile_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.profile_name_label)

        self.profile_role_label = QLabel("")
        self.profile_role_label.setObjectName("sidebar_role_label")
        self.profile_role_label.setProperty("badge", True)
        self.profile_role_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.profile_role_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.set_profile(account_name, role)

        layout.addSpacing(14)
        for route, label in (
            ("calendar", _("Calendar")),
            ("analytics", _("Analytics")),
            ("reports", _("Reports")),
        ):
            button = self._nav_button(route, label)
            layout.addWidget(button)

        layout.addStretch(1)
        self.settings_button = self._nav_button("settings", _("Settings"))
        layout.addWidget(self.settings_button)

    def _nav_button(self, route: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(f"navigation_{route}_button")
        button.setProperty("nav_item", True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, key=route: self._emit_route(key))
        self._buttons[route] = button
        return button

    def _emit_route(self, route: str) -> None:
        self.set_active_route(route)
        self.route_changed.emit(route)


def _initials(name: str) -> str:
    parts = [part for part in str(name).replace(".", " ").split() if part]
    if not parts:
        return "WL"
    return "".join(part[:1].upper() for part in parts[:2])
