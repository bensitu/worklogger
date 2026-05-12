@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "WINDOWS_BUILD_HELPER=%SCRIPT_DIR%\scripts\build\worklogger_build_windows.ps1"
set "POWERSHELL_EXE="

if not exist "%WINDOWS_BUILD_HELPER%" (
    echo [WorkLogger build][ERROR] Missing helper script: %WINDOWS_BUILD_HELPER%
    exit /b 1
)

where pwsh.exe >nul 2>nul
if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"
if not defined POWERSHELL_EXE (
    where powershell.exe >nul 2>nul
    if not errorlevel 1 set "POWERSHELL_EXE=powershell.exe"
)
if not defined POWERSHELL_EXE (
    echo [WorkLogger build][ERROR] PowerShell executable not found ^(pwsh.exe or powershell.exe^).
    exit /b 1
)

"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%WINDOWS_BUILD_HELPER%" -ProjectRoot "%SCRIPT_DIR%"
exit /b %ERRORLEVEL%
