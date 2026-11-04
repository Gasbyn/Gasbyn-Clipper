@echo off
chcp 65001 >nul
call .venv\Scripts\activate.bat
rem bez argumentů otevře grafické rozhraní, s argumenty běží příkazová řádka
if "%~1"=="" (
    start "" pythonw app.py
) else (
    python clipper.py %*
    echo.
    pause
)
