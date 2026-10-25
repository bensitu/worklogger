# Local Models

## Setup

Local rewriting requires the optional native inference dependency in the Python
environment that starts WorkLogger:

```sh
python scripts/install_native_dependencies.py
```

The installer verifies approved CPU wheels on Windows/Linux and compiles a Metal
backend from verified source on macOS ARM64. Native compilation on macOS requires
Xcode command-line tools. Python-version-independent wheels must still match the
operating system, architecture, and CPU requirements; use `--from-source` on Linux
for a portable CPU build. Restart after installing it. Packaged
applications must include that dependency when built; see [packaging](packaging.md).

Open **Settings > AI > Local Model > Manage models**. Download a catalog entry or
import a GGUF file, verify it, and choose Use model. Enable Local Model and AI Assist.
Downloading a file alone does not select it.

## Managing Files

The model list identifies downloadable, imported, verified, and selected entries.
Details show filename, estimated size/RAM, context/output limits, and license.
RAM estimates are guidance: runtime context, other applications, and backend
settings affect memory use.

Downloads show byte progress and a percentage when the total is known. Checksum
verification completes before the file can be selected. Cancellation retains a
partial download for retry. Only verified complete files replace a destination.
Downloads have a 32 GiB size limit, including resumed bytes. An oversized response
is rejected even when it does not declare its length.

Import checks the GGUF signature, supported format version, and complete fixed
header before copying a file. Copied files keep private destination permissions
instead of inheriting the source file's permissions. Keep the source and license.
These checks and checksum verification do not validate the full model structure,
the accuracy of generated text, or the safety of native parsing.
Use files from publishers you trust; a checksum is not a publisher signature.
Deletion asks for confirmation and checks selections made by other accounts.

Models and their metadata are stored beside the database and are shared by its
accounts. Database backups do not contain them. Copy this directory separately
when moving an installation.
All local accounts can refresh the catalog, import, download, and manage these
shared files, except that a model selected by another account cannot be deleted.
Local application accounts are not operating-system isolation boundaries. Use
separate operating-system accounts or installations when model libraries must be
managed independently.

The first verification after each application start reads the complete file.
Unchanged files reuse verification results within that process; no persistent
verified flag bypasses checksum validation. Listing and selecting models, explicit
verification, and verification after a download support cancellation at file
chunk boundaries. A completed download can remain available after cancellation
without changing the selected model.

## Text Capacity

Settings shows the current model and its availability together. **Text capacity
per request (tokens)** is your account's chosen inference window; it defaults to 8,192 tokens with a
minimum of 512. The effective window is the smaller of the preference and the
selected model's declared limit. It includes the request, related records, and
generated text. Tokens are pieces of text, not a character count.

The input always shows the saved preference. The model's maximum appears below
it; when this is lower than the preference, a separate notice identifies the
effective capacity without changing the saved value.

Changing models preserves the preference. Changing effective context reloads the
engine on the next request, not during an active request. Larger windows use more
memory. If loading fails, reduce the window or choose a smaller model.

Catalog edits do not change GGUF weights or training metadata. A native warning
that runtime context is below training context describes unused capacity, not
necessarily a damaged file.

The engine loads on the first request and is reused in that session. Loading can
take longer than subsequent rewriting. Review generated text before saving.
On Apple Silicon, a usable native GPU backend selects Metal layer offloading by
default. If no GPU device is available, including some virtualized environments,
CPU inference is used. Windows and Linux distributions use CPU inference.
Recoverable Metal initialization or execution failures retry the same request on
CPU once. The CPU engine is reused until it is released or the model/context changes;
account preferences are unchanged. Cancellation, deadlines, and input limits do
not trigger retries. If CPU also fails, the request reports an error without
replacing the editor's content. Native process crashes cannot be recovered this way.
Generation uses at most eight available CPU threads; prompt processing uses at
most sixteen. Each reserves one when possible. Increasing context does not
increase these limits.
Cancellation is checked while verifying the model and during generation, including
CPU prompt evaluation. The request deadline includes verification and model loading.
Native model initialization must return before cancellation can complete. Cancelled
results never replace the editor's content.
GPU evaluation must finish its current native evaluation before Python cancellation
checks can run; the native prompt-evaluation abort callback applies to CPU only.

## Catalog Files

Import copies and hashes the source in one pass without holding the catalog lock
for the whole copy. **Cancel** stops copying or verification at a chunk boundary;
unpublished files are removed and the source remains unchanged. Completed files
are independently verified before selection. If cancellation arrives after a
file is published, the completed import can remain available but is not selected.

If a local catalog or manifest becomes unreadable, close the application and
preserve the affected JSON file and model weights before making changes. Move the
damaged metadata aside, restart with the bundled catalog, and re-import retained
GGUF files. Do not delete model files merely to silence a metadata error.

Source runs read root `model_catalog.json`; packaged runs use its bundled copy.
Persistent `models/catalog.json` entries override matching IDs and retain imports.
Refresh uses an explicitly configured HTTPS remote catalog, if supplied, otherwise
local catalog files.

Remote catalog updates cannot replace bundled model identities or filenames.
Additional remote entries still rely on the configured catalog publisher: their
checksums establish file integrity, not independent publisher authentication.
Only administrators or users who trust that source should configure a remote
catalog URL. Keep installation directories and deployment environment variables
protected against modification by untrusted users.

Download entries need a filename, URL, and SHA-256 digest. Model context and output
limits must match the intended backend. See [metadata format](data-formats.md).
Do not add credentials to catalogs or commit model weights.
