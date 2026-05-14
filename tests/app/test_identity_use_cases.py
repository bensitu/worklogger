from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import unittest

from worklogger.app.commands.identity_commands import (
    LinkIdentityCommand,
    LoginWithIdentityCommand,
    UnlinkIdentityCommand,
)
from worklogger.app.queries.identity_queries import (
    GetIdentityProvidersQuery,
    ListLinkedIdentitiesQuery,
)
from worklogger.app.use_cases.identity import (
    GetIdentityProvidersHandler,
    LinkIdentityHandler,
    ListLinkedIdentitiesHandler,
    LoginWithIdentityHandler,
    UnlinkIdentityHandler,
)
from worklogger.domain.auth.models import LinkedIdentity, User
from worklogger.domain.identity.models import ExternalIdentityProfile, IdentityProviderStatus
from worklogger.domain.shared.result import Result


class FakeProvider:
    provider_id = "google"
    display_name = "Google"

    def status(self) -> IdentityProviderStatus:
        return IdentityProviderStatus(
            provider="google",
            display_name="Google",
            available=True,
            configured=True,
        )

    def authenticate(self) -> Result[ExternalIdentityProfile]:
        return Result.success(
            ExternalIdentityProfile(
                provider="google",
                subject="sub-1",
                email="person@example.test",
                display_name="Person",
            )
        )


class MemoryIdentities:
    def __init__(self) -> None:
        self.items: list[LinkedIdentity] = []
        self.next_id = 1

    def list_for_user(self, user_id: int) -> tuple[LinkedIdentity, ...]:
        return tuple(item for item in self.items if item.user_id == user_id)

    def get_by_provider_subject(
        self,
        provider: str,
        subject: str,
    ) -> LinkedIdentity | None:
        for item in self.items:
            if item.provider == provider and item.subject == subject:
                return item
        return None

    def add(self, identity: LinkedIdentity) -> LinkedIdentity:
        stored = replace(identity, id=self.next_id)
        self.next_id += 1
        self.items.append(stored)
        return stored

    def remove(self, user_id: int, identity_id: int) -> None:
        self.items = [
            item
            for item in self.items
            if not (item.user_id == user_id and item.id == identity_id)
        ]


class MemoryAuth:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}

    def user_count(self) -> int:
        return len(self.users)

    def get_by_id(self, user_id: int) -> User | None:
        return self.users.get(user_id)

    def list_users(self) -> tuple[User, ...]:
        return tuple(self.users.values())

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
    ) -> User:
        user = User(
            id=len(self.users) + 1,
            username=username,
            is_admin=is_admin,
            must_change_password=must_change_password,
            created_at=datetime.utcnow(),
        )
        self.users[user.id] = user
        return user


class IdentityUseCaseTests(unittest.TestCase):
    def test_link_list_and_unlink_identity_without_tokens(self) -> None:
        identities = MemoryIdentities()
        providers = (FakeProvider(),)
        linked = LinkIdentityHandler(
            repository=identities,
            providers=providers,
        ).handle(LinkIdentityCommand(user_id=1, provider="google"))

        self.assertTrue(linked.ok)
        assert linked.value is not None
        self.assertEqual(linked.value.email, "person@example.test")
        self.assertFalse(hasattr(linked.value, "access_token"))

        listed = ListLinkedIdentitiesHandler(identities).handle(
            ListLinkedIdentitiesQuery(1)
        )
        self.assertEqual(listed.value, (linked.value,))

        unlinked = UnlinkIdentityHandler(identities).handle(
            UnlinkIdentityCommand(user_id=1, identity_id=linked.value.id)
        )
        self.assertTrue(unlinked.ok)
        self.assertEqual(identities.list_for_user(1), ())

    def test_provider_status_lists_google(self) -> None:
        result = GetIdentityProvidersHandler((FakeProvider(),)).handle(
            GetIdentityProvidersQuery(1)
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertEqual(result.value.providers[0].provider, "google")

    def test_identity_login_creates_non_admin_user_and_link(self) -> None:
        identities = MemoryIdentities()
        auth = MemoryAuth()

        result = LoginWithIdentityHandler(
            identities=identities,
            auth=auth,
            providers=(FakeProvider(),),
        ).handle(LoginWithIdentityCommand(provider="google"))

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertFalse(result.value.user.is_admin)
        self.assertEqual(result.value.linked_identity.subject, "sub-1")


if __name__ == "__main__":
    unittest.main()
