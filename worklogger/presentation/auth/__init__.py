"""Authentication presentation widgets."""

from worklogger.presentation.auth.controller import AuthController, AuthSession
from worklogger.presentation.auth.dialogs import (
    ChangePasswordDialog,
    ChangePasswordDraft,
    LoginDialog,
    LoginDraft,
    RegisterDialog,
    RegisterDraft,
    ResetPasswordDialog,
    ResetPasswordDraft,
)

__all__ = [
    "AuthController",
    "AuthSession",
    "ChangePasswordDialog",
    "ChangePasswordDraft",
    "LoginDialog",
    "LoginDraft",
    "RegisterDialog",
    "RegisterDraft",
    "ResetPasswordDialog",
    "ResetPasswordDraft",
]
