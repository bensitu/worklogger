# Browser Sign-In

## Linking an Account

Create the initial local administrator before using Google or Microsoft sign-in.
To retain existing records, sign in locally and open **Settings > Account >
Linked identities**. Choose Link and complete authorization in the system browser.

Later provider sign-in opens that same account. An unlinked identity creates a
separate non-administrator account. Matching names or email addresses do not
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
Refusal, cancellation, timeout, and network failure leave sign-in available for
another attempt.

Account linking uses the authenticated account's proxy. Pre-login requests use
direct HTTPS; the browser has its own network settings. The callback is local.

If a stored association cannot be validated, use another sign-in method, unlink,
and relink through browser authorization. An administrator reset can establish
local access. Do not bypass token verification or merge accounts by email.
See [security](security.md) and [troubleshooting](troubleshooting.md).
