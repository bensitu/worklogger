from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from threading import Event
import time

from worklogger.app.commands.identity_commands import LinkIdentityCommand, UnlinkIdentityCommand
from worklogger.app.queries.identity_queries import (
    GetIdentityProvidersQuery,
    ListLinkedIdentitiesQuery,
)
from worklogger.app.use_cases.identity import IdentityProviderList
from worklogger.domain.auth.models import LinkedIdentity
from worklogger.domain.identity.models import IdentityProviderStatus
from worklogger.domain.shared.result import Result
from worklogger.presentation.identity import IdentityDialog
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.viewmodels import IdentityManagementViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class FakeIdentityHandlers:
    def __init__(self) -> None:
        self.identities: list[LinkedIdentity] = []
        self.linked: list[str] = []
        self.unlinked: list[int] = []

    def handle(self, command: object, *, cancellation=None) -> object:
        if isinstance(command, ListLinkedIdentitiesQuery):
            return Result.success(tuple(self.identities))
        if isinstance(command, GetIdentityProvidersQuery):
            return Result.success(
                IdentityProviderList(
                    providers=(
                        IdentityProviderStatus(
                            provider="google",
                            display_name="Google",
                            available=True,
                            configured=True,
                        ),
                    )
                )
            )
        if isinstance(command, LinkIdentityCommand):
            self.linked.append(command.provider)
            identity = LinkedIdentity(
                id=1,
                user_id=command.user_id,
                provider=command.provider,
                subject="sub-1",
                email="person@example.test",
            )
            self.identities = [identity]
            return Result.success(identity)
        if isinstance(command, UnlinkIdentityCommand):
            self.unlinked.append(command.identity_id)
            self.identities = []
            return Result.success(None)
        raise AssertionError(f"Unexpected command: {command!r}")


class IdentityPresentationTests(unittest.TestCase):
    def setUp(self):
        from tests.presentation.qt_support import dispose_test_windows
        self.addCleanup(dispose_test_windows)
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_dialog_links_and_unlinks_provider(self) -> None:
        handlers = FakeIdentityHandlers()
        view_model = IdentityManagementViewModel(
            user_id=1,
            list_handler=handlers,
            providers_handler=handlers,
            link_handler=handlers,
            unlink_handler=handlers,
        )
        dialog = IdentityDialog(view_model, job_runner=ImmediateJobRunner())

        self.assertTrue(dialog.refresh())
        self.assertTrue(dialog.link_selected_provider())
        dialog.identity_list.setCurrentRow(0)
        self.assertTrue(dialog.unlink_selected_identity())

        self.assertEqual(handlers.linked, ["google"])
        self.assertEqual(handlers.unlinked, [1])

    def test_authorization_keeps_event_loop_responsive_and_cancels_on_close(self):
        from worklogger.domain.shared.errors import CancellationError
        entered = Event()
        class DelayedHandlers(FakeIdentityHandlers):
            def handle(self, command, *, cancellation=None):
                if isinstance(command, LinkIdentityCommand):
                    entered.set()
                    while not cancellation.is_cancelled():
                        time.sleep(0.005)
                    return Result.failure(CancellationError("identity_authorization_cancelled", "identity_authorization_cancelled"))
                return super().handle(command)
        handlers = DelayedHandlers()
        dialog = IdentityDialog(IdentityManagementViewModel(user_id=1, list_handler=handlers,
            providers_handler=handlers, link_handler=handlers, unlink_handler=handlers))
        dialog.refresh()
        dialog.show()
        self.assertTrue(dialog.link_selected_provider())
        self.assertFalse(dialog.link_selected_provider())
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        deadline = time.monotonic() + 3
        while not (entered.is_set() and heartbeat) and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.005)
        self.assertTrue(heartbeat)
        self.assertTrue(dialog.processing_progress.isVisible())
        self.assertFalse(dialog.link_button.isEnabled())
        dialog.close()
        while dialog._authorization_request.is_running and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.005)
        self.assertFalse(dialog._authorization_request.is_running)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(handlers.identities, [])

    def test_registration_dialog_saves_encrypted_configuration(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from worklogger.infrastructure.identity.config import IdentityConfigurationStore
        from worklogger.infrastructure.security.key_store import HmacSecretBox, FileMachineKeyProvider
        from worklogger.presentation.identity.dialogs import IdentityConfigurationDialog
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            store = IdentityConfigurationStore(root / "identity.enc", secret_box=HmacSecretBox(FileMachineKeyProvider(root / "machine.key")))
            dialog = IdentityConfigurationDialog(store, "google")
            dialog.client_id_input.setText("client-id")
            dialog.secret_input.setText("desktop-registration")
            dialog.save_button.click()
            self.assertTrue(store.load("google").ok)
            self.assertEqual(store.load("google").value[0].client_id, "client-id")
            self.assertEqual(store.load("google").value[0].client_secret, "desktop-registration")


if __name__ == "__main__":
    unittest.main()
