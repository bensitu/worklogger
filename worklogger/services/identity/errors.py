from __future__ import annotations


class IdentityError(RuntimeError):
    """Base class for external identity failures."""


class IdentityProviderNotConfigured(IdentityError):
    """Raised when required provider or broker configuration is missing."""


class IdentityProviderUnavailable(IdentityError):
    """Raised when a provider is intentionally disabled or unsupported."""


class IdentityFlowCancelled(IdentityError):
    """Raised when the provider redirects back with an error."""


class IdentityCallbackTimeout(IdentityError):
    """Raised when no loopback callback arrives before the timeout."""


class IdentityStateMismatch(IdentityError):
    """Raised when the callback state does not match the requested state."""


class IdentityTokenExchangeFailed(IdentityError):
    """Raised when an OAuth token exchange fails."""


class IdentityTokenInvalid(IdentityError):
    """Raised when an ID token fails validation."""


class IdentityBrokerError(IdentityError):
    """Raised when an identity broker rejects an upstream identity."""
