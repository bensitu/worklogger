# Security and Privacy

Remembered-login files are scoped to the resolved database path. The default
database retains its existing session-file location; other databases use separate
encrypted files. Opening or signing out of one database does not remove another
database's local credential. Authentication tokens and recovery keys are excluded
from session representations and are not retained in the desktop runtime.

## Local Data

Accounts provide application-level separation, not protection against someone
who can read or modify the SQLite file. Database data, backups, notes, reports,
images, and exported documents are unencrypted. Use OS permissions and disk
encryption and protect backups as carefully as live data.

Background images may retain metadata in their encoded bytes. Avatars are saved
as normalized cropped PNGs. Private images and exports should not enter source
control or diagnostic attachments.

## Accounts and Recovery

Passwords require at least eight characters. Password and recovery verification
uses salted hashes. Login IDs use canonical Unicode comparison; display aliases
do not affect authentication or ownership.

Repeated login/recovery failures cause temporary lockouts. Remembered local
credentials expire and are invalidated by password workflows.
Logout revokes the account's remembered credential before removing the device
session file. A file-removal failure is reported, and the next sign-in is manual.
If revocation itself fails, logout reports failure rather than claiming success.
Only the first self-registered account is an administrator. Later self-registration
cannot request administrator privileges; administrator-created accounts use a
separate authorized workflow. Administrative operations check permissions
independently of visible controls.

Password changes replace recovery keys. Save or copy a displayed key privately.
Clipboard contents and exported key/temporary-password files are not encrypted.
An administrator reset invalidates recovery and remembered credentials and requires
the user to change the temporary password. Successful password workflows clear
the account's local lockout state.

Provider sign-in uses signed token validation, PKCE, state/nonce binding, and
loopback callbacks. Linking requires an authenticated session; email/name matching
does not merge accounts. Provider access/refresh tokens are not persisted.
See [browser sign-in](identity-signin.md).

## Stored Credentials

API keys use OS keyring-first storage with authenticated encrypted fallback.
When a keyring update fails, the successfully saved encrypted fallback remains
authoritative until a later keyring update succeeds. Previous machine keys are
persisted locally when read so subsequent keyring outages do not change them.
Proxy passwords require an approved system credential backend without a plaintext
fallback. Credential namespaces include account/database context.

Remembered-session and provider-registration files use authenticated encryption.
Machine keys are protected with current-user DPAPI on Windows or a private local
key file on other platforms. Protect the containing OS profile.
Changing machine or database path may require re-entering credentials.

Only approved OS keyring backends are used; plaintext-file backends are rejected.
Earlier encrypted values require their original random machine key. WorkLogger
does not reconstruct a key from host names or network identifiers. If that key is
unavailable, re-enter the credential; stored ciphertext is retained. Rotate old
API keys or proxy passwords if historical backups may have been exposed.
Failed credential deletion is reported instead of treated as a successful removal.
Account deletion clears system credentials first; if the credential backend is
unavailable, deletion is refused and the account is retained. Credential names
remain stable for existing accounts.

Do not regenerate or delete an unreadable key to silence a warning; preserve it
before recovery. Database backup does not transfer OS keyring entries or session
files. New backups exclude proxy passwords, but private pre-change snapshots can
contain older credential material.

Keep secrets out of public deployment configuration, model catalogs, logs,
representations, and exception messages.

## Network and AI

Ordinary recording is local. Update checks contact the release service; model
downloads contact selected catalog/file hosts.

The optional native inference backend depends on DiskCache, which has an
unpatched pickle-deserialization advisory ([CVE-2025-69872](https://github.com/grantjenks/python-diskcache/issues/357)).
WorkLogger does not enable the backend's on-disk inference cache. Do not add
disk-backed inference caching or read shared cache files without reviewing
serialization safety and directory permissions.

External AI sends selected content only after explicit account enablement.
Saving a credential alone makes no request. Sample connection tests exclude work
records. Local failures do not trigger remote fallback.

Review account privacy controls and per-date note sharing.
Per-date sharing controls independent memos, not time-record content. The account's
content setting controls whether record notes accompany AI context; selecting
text for rewriting explicitly supplies that text.
The preferred account name accompanies AI requests. Approved context and generated
responses can contain private work information.

The HTTP CONNECT proxy preserves destination TLS verification. Trust the proxy
and network before using authentication. Pre-login provider requests and browser
traffic are separate from account proxy configuration.
Transport loads default SSL trust roots together with certifi; certificate and
hostname checks remain enabled. Restart after changing trust configuration.
See [configuration](configuration.md).

## Sharing Diagnostics

Logging redacts credential fields and authorization material, but this is not a guarantee that
all arbitrary text is safe to publish. Review logs, screenshots, and exports.
Never share passwords, recovery keys, tokens, authorization headers, provider
codes, personal databases, machine keys, or private prompts.

Use synthetic records when reporting defects and follow
[the security policy](../SECURITY.md) for sensitive reports.

## Contributor Responsibilities

Preserve authorization, input bounds, credential validation, and storage safety.
Use parameterized SQL, bounded file/network reads, atomic writes, and explicit
account ownership. Maintain supported-data migration/rollback coverage.
Review dependencies and native binaries before distribution.
See [database](database.md), [testing](testing.md), and [packaging](packaging.md).
