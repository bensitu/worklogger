@echo off
setlocal

echo ============================================================
echo  WorkLogger - PyInstaller build
echo ============================================================
echo.

:: Build using the spec file (run from project root)
pyinstaller worklogger.spec --clean --noconfirm

echo.
echo ============================================================
echo  Build complete.  EXE is in dist\WorkLogger.exe
echo ============================================================
pause
