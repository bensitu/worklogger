# Browser Sign-In and Linked Accounts

## User Workflow

Create the initial local administrator account before using provider sign-in.
The login page has Google and Microsoft buttons and a settings icon beside each.
Configured buttons open the system browser; the application remains responsive
and shows an authorization indicator with cancellation.

Open **Settings > Account > Linked identities** to bind a provider identity to
the current local account. Complete authorization in the browser. Later sign-in
with that identity returns to the same account, including its display name,
permissions, records and settings. Identity is determined by verified provider
claims and the saved issuer, not by the browser's displayed email address.

An identity that is not linked creates a separate non-administrator account with
no usable local password. Matching email addresses or names never merge accounts.
Use local sign-in followed by **Link** when existing data should stay in the local
account. A local administrator can reset an externally created account's password
to establish another usable sign-in method. Unlinking the only usable method is
rejected. Changing a preferred display name does not change the provider identity.

**Remember me** persists only a local, expiring session credential, encrypted on
disk and stored as a hash in SQLite. Provider tokens and authorization codes are
not persisted. Closing a pending dialog requests cancellation; it closes when the
bounded background operation returns. Cancellation does not undo an already
committed link or revoke permissions previously granted on the provider's website.

## Application Registration

Registration is a distributor or deployment-administrator responsibility. Users
do not enter Google or Microsoft account passwords into configuration fields.
An application registration cannot be created automatically without access to
the provider's administrative console.

For Google, register a **Desktop app** OAuth client and configure its consent screen
and permitted audience. Enter its client ID, and the optional desktop client secret
if required by that registration. The redirect uses
`http://127.0.0.1:<ephemeral-port>/callback`. Request scopes are only
`openid email profile`; no Calendar, Drive or offline access is requested.
The flow follows [Google's installed-app documentation](https://developers.google.com/identity/protocols/oauth2/native-app).

For Microsoft, register a mobile/desktop public client, configure
`http://localhost/callback` as its redirect, and enter the application client ID
and a concrete tenant ID. The callback port is ephemeral; Microsoft ignores the
port for localhost redirect matching. Confidential web-client secrets are not
used. This integration intentionally does not accept the `common`, `organizations`
or `consumers` tenant aliases; its token issuer is bound to the configured tenant.
Registration must permit the intended tenant's accounts. See Microsoft's
[desktop configuration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration)
and [redirect matching rules](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url).

Provider administrative policy, consent-screen publication and application
verification remain external prerequisites. Installing WorkLogger alone does not
provision those registrations.

## Configuration Sources

Provider configuration dialogs work both before login and in linked-account
management. Saved values apply immediately and survive restart; rebuilding the
application is unnecessary. Local values are installation-scoped for the current
operating-system user, rather than preferences belonging to a WorkLogger account.
They are stored as encrypted `identity-config.enc` beside the existing credential
files. Database backup does not include this configuration.

Deployments can instead supply a JSON file through `WORKLOGGER_IDENTITY_CONFIG`:

```json
{
  "identity_enabled": "1",
  "google_login_enabled": "1",
  "google_client_id": "DESKTOP_CLIENT_ID",
  "microsoft_login_enabled": "1",
  "microsoft_client_id": "PUBLIC_CLIENT_ID",
  "microsoft_tenant_id": "CONCRETE_TENANT_ID"
}
```

Optional `google_client_secret` is supported. Do not place a confidential web-client
secret here, commit deployment credentials to source control, or distribute them
in public diagnostic logs. Protect externally supplied configuration files with
appropriate operating-system permissions.

Equivalent environment names are `WORKLOGGER_IDENTITY_ENABLED`,
`WORKLOGGER_GOOGLE_LOGIN_ENABLED`, `WORKLOGGER_GOOGLE_CLIENT_ID`,
`WORKLOGGER_GOOGLE_CLIENT_SECRET`, `WORKLOGGER_MICROSOFT_LOGIN_ENABLED`,
`WORKLOGGER_MICROSOFT_CLIENT_ID` and `WORKLOGGER_MICROSOFT_TENANT_ID`.
Environment values override external JSON values. A provider managed through
either source ignores its locally saved registration fields and appears read-only
in the configuration dialog. Complete that provider's registration in the managed
source rather than mixing it with local values. Global disabling is retained.
Registrations are enabled by default when complete unless explicitly disabled.

## Validation and Compatibility

The listener binds to `127.0.0.1` only and closes after each attempt. State binds
the callback to its original request; PKCE binds the code exchange to that request;
nonce binds the signed ID token to the authorization. RS256 signatures are verified
using trusted provider signing keys. Issuer, audience, expiry, issue time, subject
and authorized-party claims are validated as applicable. Signing-key locations are
fixed by the provider, never supplied by token headers. Provider responses are
size-limited and are not copied into error messages.

Authorization refusal, cancellation, timeout, unavailable configuration and network
failure leave the login dialog available for another attempt. Invalid callbacks
do not consume a legitimate pending request. Closing or cancelling cannot open a
late session. Cooperative cancellation is checked before persistence; a completed
database commit is not rolled back retroactively.

The existing database schema already contains an issuer field. This integration
reads and writes it without adding columns or changing stored work records.
Older associations containing only a placeholder issuer, or Firebase-local subjects
rather than direct provider subjects, are not silently converted into trusted
direct OIDC identities. Sign in using another usable method, then unlink and
relink the provider through browser authorization. A local administrator can
restore access with a password reset when needed. No email-based merging or
unverified legacy-token acceptance is performed.

Account linking uses the authenticated account's HTTPS proxy settings. Provider
sign-in before account selection uses direct HTTPS; the system browser uses its
own network configuration. The callback is local and never routed through an
application proxy.

## Verification

Automated checks use a real local callback listener, synthetic signed tokens,
simulated provider endpoints, isolated credential files and SQLite databases.
They cover successful Google and Microsoft flows, denial, cancellation, timeout,
state mismatch, duplicate parameters, replay, issuer and signature validation,
registration precedence, account binding and hashed remembered sessions.
Opt-in layout checks cover supported languages and light/dark themes.
Real provider authorization requires valid deployment registrations and is not
performed by the test suite.
