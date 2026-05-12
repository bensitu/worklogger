"""PyInstaller hook for WorkLogger service modules."""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("services")
