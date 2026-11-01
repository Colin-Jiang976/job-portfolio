@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "photoPython=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%photoPython%" (
    echo Python runtime was not found. No photos were changed.
    pause
    exit /b 1
)
"%photoPython%" -X utf8 "%~dp0scripts\photo_maintenance.py" %*
set "photoExit=%ERRORLEVEL%"
if not "%photoExit%"=="0" pause
exit /b %photoExit%
