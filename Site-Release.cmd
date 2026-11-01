@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "sitePython=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%sitePython%" (
    echo Python runtime was not found. No site files were changed.
    pause
    exit /b 1
)
"%sitePython%" -X utf8 "%~dp0scripts\site_release.py" build --open %*
if errorlevel 1 pause
