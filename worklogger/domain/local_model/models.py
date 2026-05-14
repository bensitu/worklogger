"""Local model domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalModelEntry:
    id: str
    display_name: str
    filename: str
    status: str = "local"
    sha256: str = ""
    download_url: str = ""
    estimated_size_mb: int = 0
    min_ram_gb: int = 0
    context_length: int = 8192
    max_output_tokens: int = 2048
    description: str = ""


@dataclass(frozen=True)
class LocalModelFileStatus:
    model_id: str
    available: bool
    verified: bool
    reason: str = ""


@dataclass(frozen=True)
class LocalModelListItem:
    entry: LocalModelEntry
    active: bool
    available: bool
    verified: bool
    reason: str = ""
