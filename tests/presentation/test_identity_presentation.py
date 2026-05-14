from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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

    def handle(self, command: object) -> object:
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
        dialog = IdentityDialog(view_model)

        self.assertTrue(dialog.refresh())
        self.assertTrue(dialog.link_selected_provider())
        dialog.identity_list.setCurrentRow(0)
        self.assertTrue(dialog.unlink_selected_identity())

        self.assertEqual(handlers.linked, ["google"])
        self.assertEqual(handlers.unlinked, [1])


if __name__ == "__main__":
    unittest.main()
