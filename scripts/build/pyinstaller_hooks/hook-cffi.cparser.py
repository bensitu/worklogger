"""Ignore obsolete pycparser table imports in cffi's static-import workaround.

cffi.cparser keeps a never-called helper that imports pycparser.lextab and
pycparser.yacctab for old packaging tools. Recent pycparser releases no longer
ship those modules, so PyInstaller should not report them as missing.
"""

excludedimports = ["pycparser.lextab", "pycparser.yacctab"]
