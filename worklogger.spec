# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WorkLogger.

Build (from project root, same dir as this spec):
    pip install pyinstaller
    pyinstaller worklogger.spec
"""

import sys
import os

block_cipher = None

a = Analysis(
    ['worklogger/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Bundle icons under "assets/" in the frozen app.
        ('worklogger/assets',               'assets'),
        # Bundle built-in templates under "templates/<lang>/".
        ('worklogger/templates/en',         'templates/en'),
        ('worklogger/templates/ja',         'templates/ja'),
        ('worklogger/templates/zh_cn',      'templates/zh_cn'),
        ('worklogger/templates/zh_tw',      'templates/zh_tw'),
        ('worklogger/templates/ko',         'templates/ko'),
        # Bundle only the shipped sample custom template.
        (
            'worklogger/templates/custom/Sample_1000000000000.json',
            'templates/custom',
        ),
    ],
    hiddenimports=[
        'sqlite3',
        'holidays',
        'holidays.countries',
        'tzlocal',
        'PySide6.QtPrintSupport',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
            'CFBundleShortVersionString': '1.0.0',
        },
    )
