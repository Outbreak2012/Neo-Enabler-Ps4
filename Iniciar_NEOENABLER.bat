@echo off
title NEOENABLER - PS4 Pro Neo Mode Unlocker (GoldHEN)
cd /d "%~dp0"
python neoenabler.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Hubo un error al ejecutar NEOENABLER. Verifica que Python 3 este instalado.
    pause
)
