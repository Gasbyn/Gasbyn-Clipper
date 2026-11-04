@echo off
chcp 65001 >nul
echo Instalace Gasbyn Clipperu...
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Hotovo. Ted zkontroluj prostredi prikazem: run.bat --check
echo Nezapomen mit ffmpeg v PATH a Ollamu s modelem (ollama pull gemma3:12b), nebo OpenRouter klic.
pause
