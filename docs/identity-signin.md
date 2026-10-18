# Browser Sign-In

If the encrypted local registration cannot be read, saving a replacement asks for
confirmation. Both local provider registrations are reset, and the original
encrypted file is retained beside the configuration as a uniquely named backup.
Managed registrations remain read-only. This operation does not delete accounts
or linked identities.

## Linking an Account

Upgrading from 3.3.3 preserves accounts and converts Firebase Google bindings
when their stored federated subject identifies the Google account. Historical
direct Google bindings use the canonical Google issuer after conversion.
If a binding cannot be converted unambiguously, automatic account creation for
that provider is stopped. Sign in with the existing local password or use
account recovery, then replace the old binding in Settings. Email addresses are
never used to infer ownership. Conflicting bindings abort the upgrade and leave
the original database and its migration snapshot available for recovery.

Create the initial local administrator before using Google or Microsoft sign-in.
To retain existing records, sign in locally and open **Settings > Account >
Linked identities**. Choose Link and complete authorization in the system browser.

Linking and unlinking first require the current local password. Without a local
password, choose an identity already linked to the account and authenticate again
in the browser. Cancelling either confirmation leaves the associations unchanged.
The returned provider, subject, and issuer must match the selected identity.

External confirmation requests `max_age=0` and requires a recent signed `auth_time`,
as defined by [OpenID Connect](https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest).
Missing or stale authentication time is rejected rather than trusting an existing
browser session. If the provider cannot confirm recent authentication, an
administrator can establish local password access before identities are changed.

Later provider sign-in opens that same account. An unlinked identity creates a
separate non-administrator account when deployment self-registration is enabled.
When it is disabled, an administrator must create an account, and the user must
sign in locally and link the external identity first. Matching names or email addresses do not
merge accounts. Unlinking the only usable sign-in method is rejected; establish a
local password through an administrator reset or retain another identity.

Remember me stores a local expiring credential, not provider access or refresh
tokens. Cancel stops pending authorization; it does not revoke a completed link
or permissions granted on the provider's website.

## Provider Registration

A distributor or deployment administrator supplies application registration.
Open the settings icon beside a provider on the login page or in linked-account
management. Enter registration values, not the user's account password.
Saving them applies without rebuilding the application.

For Google, use an installed desktop client with an appropriate consent audience.
Enter its client ID and optional desktop client secret if required. The callback
is `http://127.0.0.1:<port>/callback`, using an ephemeral port.
Scopes are `openid email profile`.

For Microsoft, use a mobile/desktop public client with
`http://localhost/callback` as its redirect. Enter the client ID and a concrete
tenant ID whose registration permits the intended users. Tenant aliases such as
`common` are rejected. A confidential web-client secret is not used.

Manage provider consent and registration policies through the provider's
administrative tools. WorkLogger does not provision the registration.

## Managed Configuration

Deployment policies `features.self_registration` and `features.oidc` in
`worklogger.config.json` both default to `true`. OIDC disabled by this file cannot
be enabled through provider registration or environment variables. See
[deployment configuration](configuration.md#deployment-configuration) before
disabling registration or browser sign-in on an existing installation.

Locally saved registrations use encrypted `identity-config.enc` in the OS user's
credential directory. This is separate from account preferences and database backup.

A deployment can supply an external JSON file through `WORKLOGGER_IDENTITY_CONFIG`:

```json
{
  "identity_enabled": "1",
  "google_login_enabled": "1",
  "google_client_id": "DESKTOP_CLIENT_ID",
  "microsoft_login_enabled": "1",
  "microsoft_client_id": "PUBLIC_CLIENT_ID",
  "microsoft_tenant_id": "TENANT_ID"
}
```

Equivalent environment names are `WORKLOGGER_IDENTITY_ENABLED`,
`WORKLOGGER_GOOGLE_LOGIN_ENABLED`, `WORKLOGGER_GOOGLE_CLIENT_ID`,
`WORKLOGGER_GOOGLE_CLIENT_SECRET`, `WORKLOGGER_MICROSOFT_LOGIN_ENABLED`,
`WORKLOGGER_MICROSOFT_CLIENT_ID`, and `WORKLOGGER_MICROSOFT_TENANT_ID`.

Environment values override external JSON values. A provider managed by either
source is read-only in its local configuration dialog. Do not mix managed and
local fields. Do not store registration secrets in public deployment flags,
source control, or logs.

## Authorization and Recovery

The flow uses authorization code exchange, PKCE, request-bound state/nonce,
a loopback-only callback, and verified provider ID tokens.
Token timestamps allow up to two minutes of clock skew. Larger future timestamps
produce a device-clock message; issuer, audience, signature, nonce, and recent
authentication checks remain required.
Refusal, cancellation, timeout, and network failure leave sign-in available for
another attempt.

Account linking uses the authenticated account's proxy. Pre-login requests use
direct HTTPS; the browser has its own network settings. The callback is local.

If a stored association cannot be validated, use another sign-in method, unlink,
and relink through browser authorization. An administrator reset can establish
local access. Do not bypass token verification or merge accounts by email.
See [security](security.md) and [troubleshooting](troubleshooting.md).
