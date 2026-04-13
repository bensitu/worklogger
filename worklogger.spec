# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WorkLogger (with local model support).

Build (from project root, same dir as this spec):
    pip install pyinstaller
    pyinstaller worklogger.spec

Notes
-----
* catalog.json IS bundled so the model list is available out of the box.
* llama-cpp-python, httpx and portalocker are auto-installed at first use via
  services/dep_installer.py must NOT be in requirements.txt.
"""

import sys
import os

block_cipher = None

# ---------------------------------------------------------------------------
# Collect llama_cpp data/binaries if already installed in the build env.
# ---------------------------------------------------------------------------
def _collect_llama_cpp():
    try:
        from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
        data   = collect_data_files("llama_cpp", include_py_files=False)
        dylibs = collect_dynamic_libs("llama_cpp")
        return data, dylibs
    except Exception:
        return [], []

_llama_data, _llama_bins = _collect_llama_cpp()

a = Analysis(
    ['worklogger/main.py'],
    pathex=['.'],
    binaries=_llama_bins,
    datas=[
        # Icons
        ('worklogger/assets',                               'assets'),
        # Built-in templates
        ('worklogger/templates/en',                         'templates/en'),
        ('worklogger/templates/ja',                         'templates/ja'),
        ('worklogger/templates/zh_cn',                      'templates/zh_cn'),
        ('worklogger/templates/zh_tw',                      'templates/zh_tw'),
        ('worklogger/templates/ko',                         'templates/ko'),
        ('worklogger/templates/custom/Sample_1000000000000.json',
                                                            'templates/custom'),
        # Local model catalog (defines available models; no GGUF bundled)
        ('worklogger/models/catalog.json',                  'models'),
    ] + _llama_data,
    hiddenimports=[
        'sqlite3',
        'holidays',
        'holidays.countries',
        'tzlocal',
        'PySide6.QtPrintSupport',
        # Auto-installer & download deps (imported lazily; must be declared)
        'services.dep_installer',
        'services.download_controller',
        'services.local_model_service',
        # Runtime deps auto-installed ? declare so PyInstaller doesn't warn
        'httpx',
        'portalocker',
        # llama_cpp declared but optional (may not be installed at build time)
        'llama_cpp',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Exclude large ML frameworks not used by this app
        'torch', 'tensorflow', 'numpy', 'pandas',
        'matplotlib', 'scipy', 'sklearn',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='WorkLogger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='worklogger/assets/worklogger.ico',
)

# macOS .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='WorkLogger.app',
        icon='worklogger/assets/worklogger.icns',
        bundle_identifier='dev.worklogger.app.v1',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': '2.0.0',
            'CFBundleVersion': '4',
        },
    )
