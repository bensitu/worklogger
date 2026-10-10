# Background Images

Background customization has no user-facing entry point and is disabled in the
desktop configuration. It must not activate merely because an account has stored
media. The underlying service supports importing, replacing, clearing and changing
account-owned preferences independently of work records and AI configuration.

## Storage and Validation

The default image opacity is 50 percent. Zero means invisible; 100 means fully
opaque. Accepted values are integers from 0 to 100. Importing does not enable the
image automatically; clearing disables it while retaining the chosen opacity.

PNG, JPEG, WebP and GIF are accepted by detected content rather than filename.
Animated WebP and GIF retain their encoded animation. The long edge must be at least
1280 pixels and the short edge at least 720 pixels, including portrait images.
Limits are 20 MiB encoded data, 16 million pixels per frame, 300 frames and 128 million
decoded pixels across an animation. Every frame is decoded before committing, with
bounded reads and no external URLs or SVG execution. Failed validation or storage
does not replace the existing media.

Migration 14 adds one optional row per account. Source filenames and paths are not
stored. Bytes and preferences commit transactionally, replacements retain current
options, and account deletion cascades. Full database backups include the media;
CSV, reports and AI context do not. Import and storage calls are synchronous service
operations and must be submitted through the existing background job runner by a
future presentation workflow.
