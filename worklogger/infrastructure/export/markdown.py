"""Markdown export adapter."""

from __future__ import annotations

from pathlib import Path
from worklogger.infrastructure.files import atomic_destination

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class MarkdownExporter:
    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".md":
                path = Path(str(path) + ".md")
            with atomic_destination(path) as temporary:
                temporary.write_text(str(content), encoding="utf-8")
        except OSError as exc:
            return Result.failure(
                InfrastructureError(
                    "markdown_export_failed",
                    "markdown_export_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(path)

