"""Reversible spreadsheet-safe text in WorkLogger CSV files."""

from worklogger.infrastructure.files import spreadsheet_text

TEXT_FORMAT = "spreadsheet-safe-v1"


def requires_encoding(values) -> bool:
    return any(str(value).startswith("'") or spreadsheet_text(value) != str(value) for value in values)


def encode_text(value: str) -> str:
    text = str(value)
    return "'" + text if text.startswith("'") else spreadsheet_text(text)


def decode_text(value: str, text_format: str) -> str:
    if text_format and text_format != TEXT_FORMAT:
        raise ValueError("csv_import_failed")
    return value[1:] if text_format == TEXT_FORMAT and value.startswith("'") else value
