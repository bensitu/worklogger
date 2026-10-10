"""Browser identity dependencies shared by sign-in and account linking."""

from worklogger.infrastructure.identity.config import IdentityConfigurationStore
from worklogger.infrastructure.identity.providers import BrowserIdentityProvider


def identity_providers(*, configuration=None, opener=None):
    store = configuration or IdentityConfigurationStore()
    return tuple(BrowserIdentityProvider(key, name, configuration=store, opener=opener)
                 for key, name in (("google", "Google"), ("microsoft", "Microsoft")))
