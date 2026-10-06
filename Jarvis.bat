@echo off
rem Launch Jarvis silently (no console). The native window opens itself.
cd /d "%~dp0"
start "" /b "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
