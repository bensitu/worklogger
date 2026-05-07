"""Avoid stale optional pycparser table hidden imports.

Recent pycparser releases no longer ship pycparser.lextab or pycparser.yacctab.
Only include them when the installed package actually provides them.
"""

from __future__ import annotations

import importlib.util

hiddenimports = [
    name
    for name in ("pycparser.lextab", "pycparser.yacctab")
    if importlib.util.find_spec(name) is not None
]
