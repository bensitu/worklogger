# Testing

## Native Inference Measurements

Use verified catalog models already downloaded to the model directory:

```sh
python scripts/benchmark_local_models.py --quality --output build/native-models.json
```

The command verifies model checksums, skips absent files, and does not change
account preferences or records. It measures 2, 4, and 8 threads at 2,048 and 8,192
context tokens, with two repetitions after warming the model. Model load times can
include operating-system file caching; they are not cold-start measurements.
Generation uses a fixed 32-token budget with EOS suppression, reports actual token
counts, and records native prompt/evaluation rates separately from wall time.
Each request sets a fixed seed; results can still differ across hardware/backends.
Optional quality samples use synthetic work content rather than account data.
Inspect outputs manually; timing measurements do not establish factual accuracy.

Use `--model-id` to select a catalog entry, `--threads` and `--contexts` to narrow
measurements, and `--batch-threads` to compare prompt-processing thread counts.
Apple Silicon selects GPU offloading only when available; `--gpu-layers 0` forces
CPU for comparison. The JSON records requested offloading and detected availability
separately. Do not report CPU-only virtualized runs as Metal measurements.

On Linux, compare the approved official wheel with a portable source build on the
same host. Install each with `scripts/install_native_dependencies.py`, using
`--from-source` and a separate `--wheels` directory for the portable build. Keep
model files, prompts, thread counts, and token budgets identical, and record the
system information from each run. Official wheels can require CPU instructions
that are disabled in the portable source profile. Results from different hosts
are not a controlled backend comparison.

Native dependency verification can include real model generation and cancellation:

```powershell
python scripts/prepare_native_model.py
$env:WORKLOGGER_VERIFY_MODEL_PATH = "$PWD/build/native-verification/stories260K.gguf"
python -m worklogger.main --smoke-local-model-runtime
```

The small public model is downloaded from an immutable revision and checked against
its SHA-256 digest. CI performs this check for source runs and extracted application
archives. The model stays outside distributed artifacts. Omit the environment variable
to verify only native library initialization and availability.

After building on macOS, check the packaged application directly:

```sh
python scripts/prepare_native_model.py
WORKLOGGER_VERIFY_MODEL_PATH="$PWD/build/native-verification/stories260K.gguf" \
  ./dist/WorkLogger.app/Contents/MacOS/WorkLogger --smoke-local-model-runtime
```

The environment variable applies only to this executable invocation. For a
representative catalog model, replace the path with its checksum-verified GGUF
file. The check does not change account preferences or records, or copy weights
into the application bundle.

`NATIVE BACKEND: metal` identifies GPU offloading on a supported Apple Silicon
device; `cpu` identifies CPU inference. A successful check includes real native
text generation and model reloading. Cancellation uses a separate CPU context
because the native abort callback does not interrupt GPU evaluation.
Backend detection alone does not establish successful Metal inference. Recovery
tests simulate Metal detection, initialization, and execution failures; they do
not establish behavior under a native process crash or a physical GPU failure.

## Durable Coverage

Keep tests for business rules, authorization, data integrity, compatibility,
error recovery, and workflows across layers. Prefer observable behavior over
private painter calls or fixed pixel offsets. A regression test should protect an
observable behavior or compatibility contract.

Use synthetic accounts, injected clocks/transports, and temporary files.
Never mutate a personal database or send paid provider requests in the default suite.

| Directory | Coverage |
| --- | --- |
| `tests/domain/` | Calculation and validation rules |
| `tests/app/` | Use cases and service contracts |
| `tests/infrastructure/` | Persistence, credentials, files, networking |
| `tests/presentation/` | View models, signals, workflows, jobs |
| `tests/architecture/` | Dependency boundaries and application contracts |
| `tests/i18n/` | Catalog extraction and localization |
| `tests/visual/` | Opt-in layout/rendering checks |

## Running Tests

Compile catalogs before checks that inspect localized text:

```sh
python scripts/i18n/i18n_compile.py
python -m unittest tests.domain.test_worklog_rules -v
python -m unittest tests.infrastructure.test_database_schema -v
```

For broader verification:

```sh
python -m unittest discover -s tests -t . -v
python scripts/i18n/i18n_check.py
python scripts/build.py --check
git diff --check
```

Default discovery includes functional Qt tests but excludes visual modules,
whose names do not begin with `test`. Run the smallest relevant scope first.
CI additionally runs calendar, daylight-saving, language preference, and gettext
checks on Linux with `TZ=America/New_York` and `WORKLOGGER_LANG=ja_JP`. Dependency
vulnerability checks use Python 3.11 and 3.12 to cover both supported Qt dependency
selections. The documented temporary DiskCache exception remains in effect.

## Qt and Visual Checks

Qt application state is process-global. Dispose owned widgets, process deferred
deletion, and restore themes/language in fixtures. Keep native interactive checks
sequential. Use temporary file databases when multiple connections must share data.

Run optional visual checks for changes to layout, themes, fonts, images,
translations, or display scaling:

```sh
python -m unittest tests.visual.calendar_checks -v
python -m unittest tests.visual.report_settings_checks -v
python -m unittest tests.visual.control_states_checks -v
python -m unittest tests.visual.background_images_checks -v
```

To retain screenshots:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_SCALE_FACTOR = "1.5"
$env:WORKLOGGER_SCREENSHOTS = Join-Path $env:TEMP "worklogger-screenshots"
python -m unittest tests.visual.shell_checks -v
```

Inspect text fit, focus, button states, scrolling, and imagery with representative
languages/themes/window sizes. Offscreen rendering does not establish native
dialog, tray, credential-store, or packaged behavior; check those on the target OS.

## Persistence and Distribution

Migration tests use realistic supported layouts and verify IDs, credentials,
content, rollback, and repeat startup. Backup tests include committed WAL data.
Integrity checks alone do not prove the newest records were copied.

Review documentation procedures, examples, and links against the implementation
when editing a guide. Do not add unit tests that enforce documentation wording,
file naming, or other editorial conventions.

Executable import/startup/workflow checks use isolated data.
See [packaging](packaging.md). Record what a contribution tested and what it skipped
in its review, rather than adding a dated result log to the public guides.
