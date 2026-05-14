"""Synchronize language PO files with the POT template."""

from __future__ import annotations

from catalog_tools import LANGUAGES, POT_PATH, read_po_msgids, write_po


def main() -> int:
    messages = read_po_msgids(POT_PATH)
    for language in LANGUAGES:
        write_po(language, messages)
    print(f"synced {len(messages)} messages across {len(LANGUAGES)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

