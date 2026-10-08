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
selected item. Unavailable actions are disabled, refresh preserves selection,
and deletion requires confirmation. The primary Use model action is enabled only
for an available, verified file that is not already active. Background operations
disable selection until completion; Cancel requests cancellation and keeps the
dialog open until that operation finishes. Model management does not itself
configure or start an inference backend.

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

The standard application manages files but does not construct a generation
engine. `LocalModelGateway` requires an injected generator. Installing
`requirements-ai.txt` or packaging native inference is not sufficient to connect
that generator. Model selection alone does not enable AI generation.

An integration must initialize the backend with the selected file, context limit,
chat template, and hardware configuration; enforce token and timeout limits; and
test representative input in each required language. File integrity does not
prove prompt compatibility, correct output, or acceptable interactive performance.
