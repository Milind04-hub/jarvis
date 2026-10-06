@echo off
rem Stop the background Jarvis process.
taskkill /f /im pythonw.exe >nul 2>&1
echo Jarvis stopped.
timeout /t 2 >nul
