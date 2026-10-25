# Personal Cloud Backups

Failed uploads retain local cleanup information. An explicit remote version
conflict removes the unpublished object when possible; an uncertain network
result retains it until a later successful publication can safely reconcile
retention. Objects still referenced by the published manifest are not deleted.

Personal backups copy the signed-in account's records, notes, saved reports and
report versions, templates, classifications, work arrangements, projects, work
items, calendar events, background images, and portable preferences. They do not
copy other accounts, login identities, passwords, cloud credentials, proxy
credentials, model connections, running timers, or undo history. They are logical
snapshots, not copies of the live SQLite database or its WAL files.

## Configure Storage

Open **Settings > Data > Personal cloud backup**. The existing local directory
setting is named **Local data location**; changing a cloud destination does not
move the local database.

1. Choose **WebDAV** or **S3-compatible storage**.
2. Enter the HTTPS service endpoint and a backup directory/prefix. The generated
   prefix isolates a new account. Use the same endpoint, bucket, and prefix on
   another device to access the same backup history.
3. For WebDAV, enter the username and password or service-specific application
   password. The endpoint's root collection must exist; WorkLogger creates the
   configured child collections. For S3, supply an existing bucket, its region,
   access key ID, secret access key, and an optional session token. Turn off
   **Use an S3 session token** to remove a saved token. S3 uses path-style requests
   signed with Signature Version 4. The configured account proxy applies to both
   providers; TLS verification remains enabled.
   Both providers use system certificate roots together with the bundled CA
   certificates. S3 additionally respects an explicit `AWS_CA_BUNDLE`. Restart
   WorkLogger after changing trusted certificate roots. Certificate failures are
   reported separately from authentication failures; verification is never disabled.
4. Set encryption, retention, and the automatic schedule. Save before testing
   the connection or transferring backups. Unsaved edits disable cloud actions
   so they cannot silently use the previous destination or credentials.
5. Use **Test connection**, then **Upload backup**. The connection test creates
   and removes a small temporary object and verifies conditional-write support.

The service must allow reading, creating, updating, and deleting objects inside
the chosen prefix. WebDAV also requires child-collection creation. A server
that ignores conditional writes is rejected rather than allowing unsafe uploads.
WebDAV transfers retry transient connection failures a bounded number of times.
An uncertain upload is checked against the remote content before retrying; a
version conflict is never retried as an unconditional overwrite.
Never place credentials in the endpoint URL or public `worklogger.config.json`.

## Encryption and Credentials

Client-side encryption is enabled by default. Use an independent backup
passphrase of 12 to 1024 characters and keep a separate secure copy. Losing it
makes encrypted backups unrecoverable. Saved storage credentials and the
passphrase use the operating system's credential store, without a plaintext
fallback in SQLite. If that store is unavailable, configuration cannot be saved.

Backups use compressed account documents and authenticated AES-256-GCM
encryption with a random salt and nonce and a scrypt-derived key. Archive input
and decompressed output are bounded. A wrong passphrase or modified encrypted
archive is rejected before any account data is replaced.
New encrypted archives use format version 2, normalize canonically equivalent
Unicode passphrases with NFC, and authenticate the complete encryption header.
Earlier version 1 archives remain readable, including composed and decomposed
forms of their original passphrases. This does not change local login passwords.
Use the same or a newer application version on devices reading new archives.
When encryption is enabled, restoration also rejects plaintext archives, even
when the cloud history labels them as unencrypted. To restore a historical
plaintext backup, explicitly disable encryption after reviewing the warning.
The cloud history is not a trusted freshness authority: a storage operator can
delete backups or replay previously valid encrypted versions. Keep independent
local backups for recovery from storage-side deletion or rollback.

Disabling encryption requires confirmation. Anyone able to read an unencrypted
cloud object can inspect its content. Changing the passphrase affects new
backups only: older encrypted versions still need their original passphrase.
The restore dialog can accept a different passphrase for the selected version.

## Automatic Schedule and Failures

Choose Off, an interval in hours, daily, weekly, or monthly, with the relevant
local time and weekday/date. A monthly date beyond the month's length uses its
last day. Daylight-saving gaps move the scheduled time forward; repeated hours
do not trigger the same occurrence twice. Successful manual uploads also update
the last-backup time used by the schedule.

Automatic work runs only while WorkLogger is open or resident. Missed backups
are eligible after the next sign-in's startup delay, which defaults to 300
seconds. Configure `cloud_backup.startup_delay_seconds` in
[deployment configuration](configuration.md#deployment-configuration). Busy
record, report, or data operations delay automatic work further. Checks run
once per minute by default, configurable with `cloud_backup.check_interval_seconds`;
there is no exact-second execution guarantee or background
service after the application exits. A never-backed-up enabled destination is
eligible after the delay. Manual operations do not wait for the startup delay.

Network, encryption, and remote I/O run through background jobs. The settings
panel displays the operation state, last successful upload, last restore, and
failures. Failures also produce a tray notification when available, otherwise a
non-blocking warning. Transient failures use increasing retry delays, from five
minutes to one hour by default, without repeating the same notification on every retry.
Configure `cloud_backup.retry_initial_seconds` and `cloud_backup.retry_max_seconds`
to change those retry bounds, independently of the account's backup schedule.
Version conflicts stop automatic uploads until a manual transfer resolves them.

## Versions and Retention

Manual upload and download first fetch the remote history and local data
version. Review the selected version and confirm replacement. If another device
changed the cloud version, uploading requires an explicit overwrite confirmation.
Restoring over locally changed data also requires confirmation. Force permits
the reviewed replacement; it does not bypass a change that happens after that
confirmation. Such a race is rejected and requires a fresh review.
Snapshot comparison uses stable primary-key ordering rather than physical row
order. The first transfer after upgrading may request confirmation if the stored
comparison digest was produced with a different ordering; review it normally.

Uploads create immutable version objects, then publish the history using the
server's ETag condition. Downloads verify the archive size, SHA-256 digest, and
encryption before replacement, and recheck the remote history after download.
No live multi-device merge or automatic download occurs.

Both the maximum count and retention days apply after a successful upload. When
the configured maximum is at least two, the latest upload and one previous
version are kept regardless of their age, protecting against local clock jumps.
A maximum of one explicitly retains only the latest version. A cleanup failure does not invalidate
the completed upload: its status remains visible and deletion is retried after
a later successful upload. Connection failures during publication can leave an
unlisted object; objects are not blindly deleted when publication is uncertain.

## Restore and Local Recovery

Use **Download and restore** to choose a saved version. Save or discard edits and
stop automatic recording first. Restore replaces only the current account's
portable data in one transaction. Its original account and login credentials,
other accounts, and storage configuration remain unchanged. IDs are remapped to
avoid cross-account collisions. Invalid data, a failed safety copy, or a stale
local version aborts replacement. Sign in again after success to reload all views.

Before replacement, a private account recovery archive is written under
`personal-recovery/<account-id>/` beside the local database. The completion
message gives its exact path. The latest three local recovery archives are retained per account, independently of cloud retention. Deleting an account through user management also removes its local recovery archives. Their encryption follows the current backup setting; protect the data directory when encryption is disabled.

Use **Restore local recovery copy** to select a `.wlbackup` file even when the
cloud is offline. Enter its passphrase and confirm replacement of the current
account. This operation also creates a new safety copy and checks that neither
the selected file nor local data changed during confirmation. Without configured
cloud settings, supply a passphrase for the new encrypted safety copy. Automatic
uploads remain stopped after local recovery until a manual cloud transfer has
been reviewed. Keep the source archive and passphrase until recovery is verified.

For a complete local database, including account credentials, administrators
should use the separate **Database Backup** controls rather than personal
cloud restoration. Back up the database before upgrading WorkLogger. Personal
restore accepts supported document versions and rejects unknown future formats without replacing account data. Unrecognized settings in a supported document are skipped; credentials and device-specific settings are never imported.
