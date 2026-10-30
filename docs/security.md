# Security and Privacy

Credential reads can defer format-upgrade writes when storage is temporarily
unavailable without discarding a value already decrypted successfully. A failed
proxy credential conversion does not prevent local sign-in; the network settings
report that the password needs to be entered again. Plaintext fallback is not
used for outgoing authenticated requests when protection fails.

Larger OS-protected credentials are split into bounded values. A new set becomes
visible only after its parts are stored; replacing or removing it also removes
the previous parts when the OS credential service permits cleanup.
An unreadable part index remains an error when reading, but does not prevent
explicitly saving a replacement or clearing that credential. Unidentifiable old
parts are not deleted by guessing their names; remove orphaned entries through
the operating-system credential manager if necessary.

New Windows credential files use the local application-data directory. Existing
credential directories remain in use when they hold an earlier machine key,
session, or provider registration, avoiding accidental key replacement. Exclude
those existing directories from roaming or cloud profile synchronization.

Long-running model and network jobs use a separate bounded thread pool from
calendar/list requests. Shutdown cancels queued work and keeps processing UI
events while active operations finish. If they take longer than five seconds,
a stopping indicator remains visible. Account resources are not released and a
different account is not opened while previous work can still access them.
After 15 seconds, an explicit **Force quit** option becomes available. It requires
confirmation and never runs automatically. Prefer waiting for file operations;
forced termination can leave incomplete exports, downloads, or restore markers.
Keep database journals and recovery files for the next startup, rather than
deleting them to dismiss a warning.

Only load models from sources you trust. GGUF files are processed by native code
in the application process; checksums detect changed bytes, not a malicious
publisher. Remote catalog updates cannot replace bundled model IDs or filenames.
Use the deployment AI switch to disable model execution where required.

Database files are not encrypted. On Windows they inherit directory access-control
rules; POSIX file modes do not establish Windows access control. Keep custom data
locations and backups in directories restricted to the intended operating-system
account. Do not place a live database in a public or broadly shared folder.

Remembered-login files are scoped to the resolved database path. The default
database retains its existing session-file location; other databases use separate
encrypted files. Opening or signing out of one database does not remove another
database's local credential. Authentication tokens and recovery keys are excluded
from session representations and are not retained in the desktop runtime.

## Local Data

Accounts provide application-level separation, not protection against someone
who can read or modify the SQLite file. Local database data, SQLite backups,
notes, reports, images, and ordinary exported documents are unencrypted. Use OS
permissions and disk encryption and protect backups as carefully as live data.
Personal cloud backups use separate account archives and enable client-side
encryption by default; encryption can be disabled after confirmation. Local
recovery archives created by that feature follow its encryption setting.
See [personal cloud backups](cloud-backups.md) for passphrase handling and scope.

Background images may retain metadata in their encoded bytes. Avatars are saved
as normalized cropped PNGs. Private images and exports should not enter source
control or diagnostic attachments.

## Accounts and Recovery

Passwords require at least eight characters. Password and recovery verification
uses salted hashes. Login IDs use canonical Unicode comparison; display aliases
do not affect authentication or ownership.

Repeated login/recovery failures cause temporary lockouts of at most 30 minutes.
Password and recovery-key attempts have independent counters; a password lockout
does not prevent recovery with the correct key. The sign-in window reports the
remaining delay without extending it when a locked attempt is retried.
Recovery keys accept uppercase hexadecimal and differences in spaces or hyphens.
New IDs reject invisible control/formatting characters, and new passwords are limited
to 1024 UTF-8 bytes. Existing passwords remain usable when signing in or changing
them. Passwords retain their exact Unicode representation so that
existing password hashes do not change meaning during an upgrade.
Remembered local
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
Copied recovery keys and temporary passwords are cleared after 60 seconds if
the clipboard still contains the copied text. Other copied content is not cleared.
On Windows, sensitive copies request exclusion from clipboard history and cloud
synchronization. These flags do not remove existing history or prevent independent
clipboard managers from retaining copies.
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
Existing fallback values are updated before replacing a keyring entry, so a
failed cleanup cannot restore an older credential. When the keyring cannot be
cleared, an encrypted empty value disables the local credential until it is
replaced or cleanup can complete. This uses the existing encrypted format and
requires no database migration. It does not erase copies held by an unavailable
OS credential service; clear those separately when that service becomes available.
Proxy passwords require an approved system credential backend without a plaintext
fallback. Credential namespaces include account/database context.

Remembered-session and provider-registration files use authenticated encryption.
Machine keys are protected with current-user DPAPI on Windows or a private local
key file on other platforms. Protect the containing OS profile.
This fallback does not protect against other processes running as the same OS
user that can read the machine key and database. Use an approved system keyring
and restrict access to the operating-system account.
Changing machine or database path may require re-entering credentials.

Only approved OS keyring backends are used; plaintext-file backends are rejected.
Earlier encrypted values require their original random machine key. WorkLogger
does not reconstruct a key from host names or network identifiers. If that key is
unavailable, re-enter the credential; stored ciphertext is retained. Rotate old
API keys or proxy passwords if historical backups may have been exposed.
Failures to clear both the local credential and its fallback are reported.
Account deletion commits database removal before clearing external service
credentials. A database failure leaves credentials untouched. If credential
cleanup fails after deletion, the failure is reported and an administrator can
retry cleanup for the removed account; the account and its data are not recreated.
Credential names remain stable for existing accounts.

Do not regenerate or delete an unreadable key to silence a warning; preserve it
before recovery. Database backup does not transfer OS keyring entries or session
files. New backups exclude proxy passwords and API-key settings, including
encrypted fallback values. Credential removal uses a private temporary directory;
only the sanitized snapshot is written to the selected backup directory.
Private pre-change snapshots can
contain older credential material.

Keep secrets out of public deployment configuration, model catalogs, logs,
representations, and exception messages.

## Network and AI

Ordinary recording is local. Update checks contact the release service; model
downloads contact selected catalog/file hosts.
Keep the operating-system trust store and any administrator-supplied certificate
bundles current as well as the application's bundled roots. Removing a certificate
from one trust source does not remove it from another source.

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
HTTP proxy authentication uses Basic credentials on the connection to the proxy;
destination TLS does not encrypt that proxy-authentication exchange. Use only a
trusted proxy over a trusted network.
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

Password confirmation for password changes and external identity changes uses the same failure counter and temporary lockout as password sign-in.

Failed sign-in attempts use the same temporary lockout response for existing and unknown IDs. Unknown-ID records are limited to 1,024 entries; failure records expire after seven days.

The first self-registered account receives administrator access, whether it uses a local password or browser sign-in. Existing accounts are not automatically promoted. Keep a database backup containing a usable administrator account.

Account deletion removes the account's live data, protected credentials, and account-specific local recovery archives. It does not erase previously exported files, complete database backups, or preserved startup recovery databases. Protect and manage those copies separately.

Deployment feature controls depend on the installed configuration and operating-system file permissions. A missing configuration uses built-in defaults and records a warning; invalid configuration disables restricted services. Protect the application directory against changes by users who should not alter deployment policy.
