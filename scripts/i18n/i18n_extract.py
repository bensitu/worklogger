"""Extract gettext msgids from source files."""

from __future__ import annotations

from catalog_tools import extract_source_messages, write_pot


def main() -> int:
    messages = extract_source_messages()
    write_pot(messages)
    print(f"extracted {len(messages)} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

