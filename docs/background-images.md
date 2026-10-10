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
stored as separate fields, but encoded bytes may retain embedded image metadata.
Media resides in the unencrypted database and its backups. Bytes and preferences
commit transactionally, replacements retain current
options, and account deletion cascades. Full database backups include the media;
CSV, reports and AI context do not. Import and storage calls are synchronous service
operations and must be submitted through the existing background job runner by a
future presentation workflow.

## Desktop Rendering

`AppWindowConfig.background_images_available` defaults to false. There is no menu,
settings control, file picker, command-line option or environment switch for this
feature. Even stored enabled preferences do not load or play media while this flag
is false. Composition provides the account-scoped service without reading the BLOB.

When explicitly enabled by a developer, `BackgroundController` provides asynchronous
reload, import, option updates and clearing through the existing job runner. It
publishes completion and busy signals for a future UI, rejects concurrent requests,
and ignores callbacks after its surface is disposed. Failed operations preserve the
displayed background. Decoding and validation happen outside the UI thread.

`MainBackgroundWidget` paints one image behind all four main pages, not behind the
sidebar, separate dialogs or minimal mode. Centered aspect-preserving cover scaling
fills the available area without tiling or letterboxing. Image opacity is blended
over the current theme's normal surface color, including dark mode. Resizing and
theme changes preserve the media. Foreground cards, inputs, buttons and tables keep
their normal solid surfaces. Only background containers become transparent.

Animation uses Qt's GIF/WebP decoder in an owned worker thread without caching the
whole movie. A latest-frame mailbox coalesces updates, so a busy UI cannot accumulate
an unbounded queue of images. Playback pauses when hidden or opacity is zero, resumes
when shown, and observes source timing and loop metadata. Closing or destroying the
surface joins the worker before deleting it. Invalid stored media falls back to the
normal theme background without preventing startup. No external imaging dependency
or new bundled user artwork is required; the existing resource collector includes
the background stylesheet and PyInstaller's Qt hooks supply image-format plugins.
