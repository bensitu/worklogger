# Local Models

## Supplied Choices

The built-in catalog contains text-oriented Q4_K_M GGUF files hosted on Hugging
Face. The first entry is the preferred starting choice, not an automatic active
selection. Importing or downloading must pass checksum verification before the
account can select a file. No file is downloaded at startup.

| Model | Approximate file size | Estimated system RAM | Purpose |
| --- | --- | --- | --- |
| Qwen3-4B-Instruct-2507 | 2.33 GiB | 8 GB | Initial choice for multilingual summary drafting and editing |
| Qwen2.5-1.5B-Instruct | 1.04 GiB | 4 GB | Short notes on memory-constrained computers; lower model capacity |
| Qwen3-8B | 4.68 GiB | 12 GB | Larger multilingual option; the gateway requests non-thinking output |
| Phi-4-mini-instruct | 2.32 GiB | 8 GB | Alternative instruction-model family supporting the application's languages |
| Qwen2.5-7B-Instruct | 4.36 GiB | 12 GB | Retained non-thinking Qwen2.5 option for existing integrations |

Selection is based on upstream capabilities, language coverage, download size,
licensing, and the application's short text workflows, not a local quality or
speed benchmark. Hardware estimates are not measured minimums: operating-system
memory, other applications, backend configuration, KV cache, and GPU offload all
affect actual requirements. Review generated content before saving a report.

[Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
is explicitly non-thinking. [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)
supports both thinking and non-thinking behavior. The gateway adds `/no_think`
only to the hybrid Qwen3 family, not the non-thinking instruction variant.
[Phi-4-mini-instruct](https://huggingface.co/microsoft/Phi-4-mini-instruct)
documents English, Chinese, Japanese, and Korean support under the MIT license.
The Qwen entries use Apache-2.0; the small option uses the
[official GGUF repository](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF).

[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) is no longer a supplied
recommendation. Its non-thinking mode requires chat-template configuration rather
than Qwen3's prompt directive, and its architecture requires a compatible native
backend. The current generator interface does not carry those template options.
Existing downloaded or imported files are not removed. An integration can still
supply its own metadata and backend after verifying compatibility.

## Catalog Configuration

The model manager separates the catalog list from the selected model's details.
Details show localized descriptions, file names, size and RAM estimates, context
and output limits, license, verification state, and active selection. Refresh and
Import apply to the catalog; Download, Verify, Delete, and Use model apply to the
selected item. Context and maximum output use separate label/value rows in the same
columns as file, RAM, size, and license metadata. Unavailable actions are disabled,
refresh preserves selection, and deletion requires confirmation. The primary Use model action is enabled only
for an available, verified file that is not already active. Background operations
disable selection until completion; Cancel requests cancellation and keeps the
dialog open until that operation finishes. Model management does not itself
load model weights. Selecting a verified file updates the shared account inference
service and enables rewriting when the native dependency and preferences are available.
Settings exposes only Manage models; downloading and importing are performed
inside that dialog. Downloads show measured byte progress and a percentage when
the server supplies a total, including resumed transfers. Unknown lengths and
hash verification use indeterminate progress. Transfer progress is capped below
100 percent until download verification succeeds; failure/cancellation never
shows a completed download. UI progress notifications are rate-limited.

Every supplied URL uses an immutable repository commit, with the corresponding
LFS SHA-256 digest. File existence and digests were checked through public Hugging
Face metadata. The multi-gigabyte files were not downloaded or benchmarked.

The configured context is 8,192 tokens, not the model's advertised maximum.
Output is limited to 2,048 tokens, or 1,024 for the small model. These settings are
intended for short work summaries and leave room for input within the context;
an injected inference implementation must enforce the total token budget.
Using the advertised maximum would require substantially more memory and may
need additional backend configuration.

The desktop loads the root catalog in source checkouts and its packaged copy at
`worklogger/assets/models/model_catalog.json` in distributions. Persistent
`models/catalog.json` entries override matching IDs and preserve local imports.
A configured remote refresh replaces persistent downloadable entries while
retaining local imports; bundled choices remain available for IDs not overridden.
JSON metadata never activates an undownloaded model. Descriptions and hardware
details appear in localized model-list tooltips. See [data formats](data-formats.md).

## Runtime Integration

The desktop constructs `LocalInferenceRuntime` for the signed-in account. It shares
the model store with model management, checks selection and enablement preferences,
and verifies the file before inference. `LocalModelGateway` supplies prompt handling
and removes reasoning blocks from the final text. Records, notes, and reports share
the same rewrite handler; selecting a model refreshes their controls without restart.

Install the optional CPU dependency using the upstream wheel index:

```sh
python -m pip install --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu -r requirements-ai.txt
```

The index and chat-completion interface are documented by
[llama-cpp-python](https://github.com/abetlen/llama-cpp-python). Use the same Python
environment that starts WorkLogger. Restart after installing the dependency.
Choose a verified file with Use model, then enable Local Model and AI Assist.
Downloading alone does not select a model, and toggling a preference does not load
weights on the GUI thread.

The engine loads lazily on a worker, uses CPU execution and a bounded thread count,
and reuses one loaded model per account session. Changing models releases the previous
engine on the next request; deleting its file releases the native handle first.
Session shutdown releases the engine after outstanding jobs finish. Context is
limited to at most 8,192 tokens with space reserved for formatting and output.
Rewriting has a cooperative 180-second inference deadline, including weight loading;
the native loader and prompt evaluation cannot be forcibly interrupted mid-call.
Failed loading, timeout, and oversized input return errors without replacing the draft.

A native CPU rewrite was checked with Qwen2.5-1.5B-Instruct using synthetic text.
This is not a speed or quality benchmark across all catalog choices or platforms.
File integrity does not prove prompt compatibility or generated-text accuracy.
