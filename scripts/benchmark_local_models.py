"""Measure native inference and inspect synthetic work-text outputs without account data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worklogger.app.ports import AIRequest
from worklogger.app.use_cases.text_prompts import rewrite_messages
from worklogger.infrastructure.ai.local import LocalModelGateway
from worklogger.infrastructure.ai.runtime_options import engine_options, is_apple_silicon

QUALITY_CASES = (
    ("time_entry", "reviewed T-12 for 30 minutes; implementation is still ongoing"),
    ("time_entry", "\u30c6\u30b9\u30c8\u3084\u308b"),
    ("daily_note", "- [x] Reviewed T-12\n- [ ] Follow up with the team"),
    ("daily_report", "# Work\n- Reviewed T-12 for 30 minutes. Implementation is ongoing.\n## Risks\n- \n## Plan\n-"),
)
PERFORMANCE_PROMPT = (
    "Summarize the following work notes without inventing facts.\n"
    + "Reviewed ticket T-12 for 30 minutes. Implementation is ongoing. No risks were recorded.\n" * 12
)


def measure(entry, path, *, threads, batch_threads, context, gpu_layers, repeats, quality):
    import llama_cpp

    started = perf_counter()
    engine = llama_cpp.Llama(model_path=str(path), n_ctx=context, n_threads=threads,
                             n_threads_batch=batch_threads, n_gpu_layers=gpu_layers,
                             seed=1, verbose=False)
    result = dict(model_id=entry["id"], context=context, threads=threads, batch_threads=batch_threads,
                  gpu_layers_requested=gpu_layers, load_seconds=perf_counter() - started,
                  chat_format=engine.chat_format, measurements=[])
    try:
        token_bias = {str(engine.token_eos()): -100}
        engine.create_completion("Warm up.", max_tokens=8, temperature=0, logit_bias=token_bias, seed=1)
        for _ in range(repeats):
            engine.reset()
            llama_cpp.llama_perf_context_reset(engine._ctx.ctx)
            started = perf_counter()
            completion = engine.create_completion(PERFORMANCE_PROMPT, max_tokens=32,
                                                   temperature=0, logit_bias=token_bias, seed=1)
            elapsed = perf_counter() - started
            native = llama_cpp.llama_perf_context(engine._ctx.ctx)
            result["measurements"].append(dict(
                elapsed_seconds=elapsed, completion_tokens=completion["usage"]["completion_tokens"],
                prompt_tokens=completion["usage"]["prompt_tokens"],
                prompt_tokens_per_second=1000 * native.n_p_eval / native.t_p_eval_ms if native.t_p_eval_ms else None,
                generation_tokens_per_second=1000 * native.n_eval / native.t_eval_ms if native.t_eval_ms else None,
            ))
        result["median_seconds"] = median(row["elapsed_seconds"] for row in result["measurements"])
        if quality:
            def generate(messages, limit):
                engine.reset()
                return engine.create_chat_completion(messages=list(messages), max_tokens=limit,
                                                      temperature=0.2, seed=1)["choices"][0]["message"]["content"]
            gateway = LocalModelGateway(generator=generate, model_id=entry["id"], catalog_entry=entry,
                                        max_output_tokens=min(256, entry["max_output_tokens"]))
            result["outputs"] = []
            for task, source in QUALITY_CASES:
                values = dict(content=source, context=task)
                started = perf_counter()
                response = gateway.generate(AIRequest(rewrite_messages(**values), entry["id"], 180,
                                                       local_messages=rewrite_messages(**values, compact=True)))
                result["outputs"].append(dict(task=task, source=source, elapsed_seconds=perf_counter() - started,
                                              ok=response.ok, output=response.value.text if response.ok else None,
                                              error=response.error.code if response.error else None))
        return result
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=ROOT / "worklogger/models")
    parser.add_argument("--catalog", type=Path, default=ROOT / "model_catalog.json")
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--threads", type=int, nargs="+", default=[2, 4, 8])
    parser.add_argument("--batch-threads", type=int)
    parser.add_argument("--contexts", type=int, nargs="+", default=[2048, 8192])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--gpu-layers", type=int)
    parser.add_argument("--quality", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (not 1 <= args.repeats <= 10 or any(not 1 <= item <= 128 for item in args.threads)
            or any(not 512 <= item <= 32768 for item in args.contexts)
            or (args.gpu_layers is not None and args.gpu_layers < -1)
            or (args.batch_threads is not None and not 1 <= args.batch_threads <= 128)
            or args.output.suffix.lower() != ".json"):
        parser.error("Invalid measurement configuration")
    if args.output.resolve() in {
        args.catalog.resolve(), (args.models / "catalog.json").resolve(), (args.models / "manifest.json").resolve(),
    }:
        parser.error("Measurement output must not replace model metadata")
    import llama_cpp

    gpu_offload_available = is_apple_silicon() and llama_cpp.llama_supports_gpu_offload()
    gpu_layers = (args.gpu_layers if args.gpu_layers is not None else
                  engine_options(gpu_offload_supported=gpu_offload_available)["n_gpu_layers"])
    report = dict(version=llama_cpp.__version__, platform=sys.platform, architecture=platform.machine(),
                  python=platform.python_version(), logical_cpus=os.cpu_count(), seed=1,
                  gpu_offload_available=gpu_offload_available,
                  system_info=llama_cpp.llama_print_system_info().decode(), models=[], missing=[])
    entries = json.loads(args.catalog.read_text(encoding="utf-8"))["models"]
    if args.model_id and set(args.model_id) - {entry["id"] for entry in entries}:
        parser.error("Unknown model ID")
    for entry in entries:
        if args.model_id and entry["id"] not in args.model_id:
            continue
        if Path(entry["filename"]).name != entry["filename"]:
            raise ValueError("Model filename must not contain a directory")
        path = args.models / entry["filename"]
        if not path.is_file():
            report["missing"].append(entry["id"])
            continue
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("Model checksum does not match the catalog")
        for context in args.contexts:
            if context > entry["context_length"]:
                raise ValueError("Requested context exceeds the model limit")
            for threads in args.threads:
                row = measure(entry, path, threads=threads, batch_threads=args.batch_threads or threads, context=context,
                              gpu_layers=gpu_layers, repeats=args.repeats,
                              quality=args.quality and context == args.contexts[-1] and threads == args.threads[-1])
                report["models"].append(row)
                print(json.dumps({key: row[key] for key in ("model_id", "context", "threads", "median_seconds")}), flush=True)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if not report["models"]:
        parser.error("No matching verified model files are available")
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
