"""Bounded CPU scheduling and automatic Metal selection for native inference."""

import os
import platform
import sys


def is_apple_silicon(*, platform_name=None, architecture=None):
    return (platform_name or sys.platform) == "darwin" and (
        architecture or platform.machine()
    ).lower() in {"arm64", "aarch64"}


def engine_options(*, gpu_offload_supported=False, cpu_count=None, platform_name=None, architecture=None):
    if cpu_count is None:
        cpu_count = getattr(os, "process_cpu_count", os.cpu_count)() or 2
        if hasattr(os, "sched_getaffinity"):
            try:
                cpu_count = min(cpu_count, len(os.sched_getaffinity(0)))
            except OSError:
                pass
    threads = max(1, min(8, cpu_count - 1))
    return dict(
        n_threads=threads, n_threads_batch=max(1, min(16, cpu_count - 1)),
        n_gpu_layers=-1 if gpu_offload_supported and is_apple_silicon(
            platform_name=platform_name, architecture=architecture) else 0,
    )
