"""Compile gettext PO files into MO files."""

from __future__ import annotations

from catalog_tools import compile_po_to_mo, locale_po_paths


def main() -> int:
    compiled = 0
    for path in locale_po_paths():
        if path.exists():
            compile_po_to_mo(path)
            compiled += 1
    print(f"compiled {compiled} catalogs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

