from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock

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

    def authenticate(self, *, cancellation=None, reauthenticate=False) -> Result[ExternalIdentityProfile]:
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

    def has_unresolved_provider(self, provider):
        return False

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
        self.identities = None
        self.remember_tokens = {}

    def set_remember_token(self, user_id, token, expires_at):
        self.remember_tokens[user_id] = (token, expires_at)

    def create_identity_account(self, username, profile):
        user = self.create_user(username, "", recovery_key=None, is_admin=False, local_password_enabled=False)
        linked = self.identities.add(LinkedIdentity(0, user.id, profile.provider, profile.subject,
                                                    profile.email, profile.display_name))
        return user, linked

    def user_count(self) -> int:
        return len(self.users)

    def get_by_id(self, user_id: int) -> User | None:
        return self.users.get(user_id)

    def verify_user(self, username, password):
        return next((user for user in self.users.values() if user.username == username), None) if password == "example-password" else None

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
        local_password_enabled: bool = True,
    ) -> User:
        user = User(
            id=len(self.users) + 1,
            username=username,
            is_admin=is_admin,
            must_change_password=must_change_password,
            created_at=datetime.now(timezone.utc),
            local_password_enabled=local_password_enabled,
        )
        self.users[user.id] = user
        return user


class IdentityUseCaseTests(unittest.TestCase):
    def test_disabled_identity_operations_do_not_access_providers_or_storage(self):
        identities, auth, provider = Mock(), Mock(), Mock(provider_id="google")
        operations = (
            (LoginWithIdentityHandler(identities=identities, auth=auth, providers=(provider,), enabled=False),
             LoginWithIdentityCommand("google")),
            (LinkIdentityHandler(repository=identities, auth=auth, providers=(provider,), enabled=False),
             LinkIdentityCommand(1, "google", "example-password")),
            (UnlinkIdentityHandler(identities, auth, providers=(provider,), enabled=False),
             UnlinkIdentityCommand(1, 1, "example-password")),
        )
        for handler, command in operations:
            self.assertEqual(handler.handle(command).error.code, "oidc_disabled")
        self.assertEqual(identities.mock_calls, [])
        self.assertEqual(auth.mock_calls, [])
        provider.authenticate.assert_not_called()

    def test_registration_policy_blocks_new_external_accounts_but_allows_linked_login(self):
        identities, auth = MemoryIdentities(), MemoryAuth()
        handler = LoginWithIdentityHandler(identities=identities, auth=auth, providers=(FakeProvider(),),
                                          self_registration_enabled=False)
        self.assertEqual(handler.handle(LoginWithIdentityCommand("google")).error.code, "self_registration_disabled")
        self.assertEqual(auth.users, {})
        self.assertEqual(identities.items, [])
        auth.users[1] = User(1, "local")
        identities.add(LinkedIdentity(0, 1, "google", "sub-1"))
        self.assertEqual(handler.handle(LoginWithIdentityCommand("google")).value.user.id, 1)

    def test_identity_changes_require_the_current_account_password(self):
        identities, auth = MemoryIdentities(), MemoryAuth()
        auth.users[1] = User(1, "local")
        handler = LinkIdentityHandler(repository=identities, providers=(FakeProvider(),), auth=auth)
        for password in (None, "incorrect"):
            self.assertFalse(handler.handle(LinkIdentityCommand(1, "google", password)).ok)
            self.assertEqual(identities.items, [])
        linked = handler.handle(LinkIdentityCommand(1, "google", "example-password")).value
        unlink = UnlinkIdentityHandler(identities, auth)
        for password in (None, "incorrect"):
            self.assertFalse(unlink.handle(UnlinkIdentityCommand(1, linked.id, password)).ok)
            self.assertEqual(identities.items, [linked])
        self.assertTrue(unlink.handle(UnlinkIdentityCommand(1, linked.id, "example-password")).ok)

    def test_external_only_accounts_reverify_an_owned_identity_before_changes(self):
        identities, auth = MemoryIdentities(), MemoryAuth()
        auth.users[1] = User(1, "external", local_password_enabled=False)
        linked = identities.add(LinkedIdentity(0, 1, "google", "sub-1"))
        other = identities.add(LinkedIdentity(0, 2, "google", "other-subject"))
        handler = LinkIdentityHandler(repository=identities, providers=(FakeProvider(),), auth=auth)
        for identifier in (None, other.id):
            self.assertFalse(handler.handle(LinkIdentityCommand(1, "google", verification_identity_id=identifier)).ok)
        self.assertTrue(handler.handle(LinkIdentityCommand(1, "google", verification_identity_id=linked.id)).ok)
        identities.items[0] = replace(linked, subject="changed")
        self.assertFalse(handler.handle(LinkIdentityCommand(1, "google", verification_identity_id=linked.id)).ok)

    def test_link_list_and_unlink_identity_without_tokens(self) -> None:
        identities = MemoryIdentities()
        providers = (FakeProvider(),)
        auth = MemoryAuth()
        auth.users[1] = User(id=1, username="local")
        linked = LinkIdentityHandler(
            repository=identities,
            providers=providers,
            auth=auth,
        ).handle(LinkIdentityCommand(1, "google", "example-password"))

        self.assertTrue(linked.ok)
        assert linked.value is not None
        self.assertEqual(linked.value.email, "person@example.test")
        self.assertFalse(hasattr(linked.value, "access_token"))

        listed = ListLinkedIdentitiesHandler(identities).handle(
            ListLinkedIdentitiesQuery(1)
        )
        self.assertEqual(listed.value, (linked.value,))

        auth = MemoryAuth()
        auth.users[1] = User(id=1, username="local")
        unlinked = UnlinkIdentityHandler(identities, auth).handle(
            UnlinkIdentityCommand(1, linked.value.id, "example-password")
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
        auth.identities = identities

        result = LoginWithIdentityHandler(
            identities=identities,
            auth=auth,
            providers=(FakeProvider(),),
        ).handle(LoginWithIdentityCommand(provider="google"))

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertFalse(result.value.user.is_admin)
        self.assertEqual(result.value.linked_identity.subject, "sub-1")
        self.assertFalse(result.value.user.local_password_enabled)
        unlinked = UnlinkIdentityHandler(identities, auth).handle(
            UnlinkIdentityCommand(result.value.user.id, result.value.linked_identity.id))
        self.assertFalse(unlinked.ok)
        self.assertEqual(identities.list_for_user(result.value.user.id), (result.value.linked_identity,))

    def test_identity_username_collision_does_not_replace_local_account(self):
        identities = MemoryIdentities()
        auth = MemoryAuth()
        auth.identities = identities
        auth.users[1] = User(id=1, username="PERSON")
        result = LoginWithIdentityHandler(identities=identities, auth=auth, providers=(FakeProvider(),)).handle(
            LoginWithIdentityCommand(provider="google"))
        self.assertTrue(result.ok)
        self.assertNotEqual(result.value.user.id, 1)
        self.assertNotEqual(result.value.user.username.casefold(), "person")
        self.assertEqual(auth.users[1].username, "PERSON")

    def test_cancelled_authorization_does_not_create_or_link_accounts(self):
        from worklogger.app.job_runner import CancellationToken
        token = CancellationToken()
        class CancelProvider(FakeProvider):
            def authenticate(self, *, cancellation=None):
                cancellation.cancel()
                return super().authenticate()
        identities, auth = MemoryIdentities(), MemoryAuth()
        auth.identities = identities
        providers = (CancelProvider(),)
        auth.users[1] = User(1, "local")
        for handler, command in ((LinkIdentityHandler(repository=identities, providers=providers, auth=auth), LinkIdentityCommand(1, "google", "example-password")),
                                 (LoginWithIdentityHandler(identities=identities, auth=auth, providers=providers), LoginWithIdentityCommand("google"))):
            result = handler.handle(command, cancellation=token)
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "identity_authorization_cancelled")
        self.assertEqual(identities.items, [])
        self.assertEqual(len(auth.users), 1)

    def test_provider_login_remembers_local_session_and_retains_bound_account(self):
        from worklogger.domain.auth.policies import remember_token_storage_value
        identities, auth = MemoryIdentities(), MemoryAuth()
        auth.identities = identities
        auth.users[1] = User(1, "local", display_name="Mary")
        linked = LinkIdentityHandler(repository=identities, providers=(FakeProvider(),), auth=auth).handle(LinkIdentityCommand(1, "google", "example-password"))
        handler = LoginWithIdentityHandler(identities=identities, auth=auth, providers=(FakeProvider(),))
        login = handler.handle(LoginWithIdentityCommand("google", remember=True))
        self.assertTrue(login.ok)
        self.assertEqual(login.value.user.effective_display_name, "Mary")
        self.assertEqual(login.value.linked_identity, linked.value)
        self.assertEqual(auth.remember_tokens[1][0], remember_token_storage_value(login.value.token))
        self.assertNotEqual(auth.remember_tokens[1][0], login.value.token)
        self.assertTrue(handler.handle(LoginWithIdentityCommand("google")).ok)
        self.assertEqual(auth.remember_tokens[1], (None, None))
        self.assertEqual(len(auth.users), 1)


if __name__ == "__main__":
    unittest.main()
