"""Markdown export adapter."""

from __future__ import annotations

from pathlib import Path

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class MarkdownExporter:
    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".md":
                path = path.with_suffix(".md")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        except OSError as exc:
            return Result.failure(
                InfrastructureError(
                    "markdown_export_failed",
                    "markdown_export_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(path)

