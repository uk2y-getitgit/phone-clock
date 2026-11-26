@echo off
rem Debug mode: run the server in a visible console window (close the window to stop)
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0stop.bat" quiet
python server.py
pause
