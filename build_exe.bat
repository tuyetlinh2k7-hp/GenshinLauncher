@echo off
title Build Genshin Impact Launcher (.exe)
cd /d "%~dp0"

echo Dang kiem tra moi truong va bat dau build...
python build_launcher.py
pause

