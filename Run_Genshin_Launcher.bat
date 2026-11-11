@echo off
title Genshin Impact Launcher
cd /d "%~dp0"

REM Try to find Python
where pythonw >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start "" pythonw "%~dp0genshin_launcher.py"
    exit /b
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start "" python "%~dp0genshin_launcher.py"
    exit /b
)

echo [Loi] Khong tim thay Python! Vui long cai dat Python 3.10+ va thu lai.
pause
