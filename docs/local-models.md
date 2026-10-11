# Local Models

## Setup

Local rewriting requires the optional native inference dependency in the Python
environment that starts WorkLogger:

```sh
python -m pip install -r requirements-ai.txt
```

Use a wheel or native build appropriate to the target platform, following the
dependency's installation instructions. Restart after installing it. Packaged
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

Import requires a nonempty GGUF file. Keep its source and license. Verification
checks file integrity, not the accuracy or suitability of generated text.
Use files from publishers you trust; a checksum is not a publisher signature.
Deletion asks for confirmation and checks selections made by other accounts.

Models and their metadata are stored beside the database and are shared by its
accounts. Database backups do not contain them. Copy this directory separately
when moving an installation.

## Runtime Context

Model context limit is the catalog's declared model capacity. Runtime context
is your account's chosen inference window; it defaults to 8,192 tokens with a
minimum of 512. The effective window is the smaller of the preference and the
selected model's declared limit.

Changing models preserves the preference. Changing effective context reloads the
engine on the next request, not during an active request. Larger windows use more
memory. If loading fails, reduce the window or choose a smaller model.

Catalog edits do not change GGUF weights or training metadata. A native warning
that runtime context is below training context describes unused capacity, not
necessarily a damaged file.

The engine loads on the first request and is reused in that session. Loading can
take longer than subsequent rewriting. Review generated text before saving.
Cancellation prevents a late result from replacing your draft but may not stop a
native call immediately.

## Catalog Files

Source runs read root `model_catalog.json`; packaged runs use its bundled copy.
Persistent `models/catalog.json` entries override matching IDs and retain imports.
Refresh uses an explicitly configured HTTPS remote catalog, if supplied, otherwise
local catalog files.

Download entries need a filename, URL, and SHA-256 digest. Model context and output
limits must match the intended backend. See [metadata format](data-formats.md).
Do not add credentials to catalogs or commit model weights.
