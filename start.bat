@echo off
rem Run the server in the background (no window). Log: server.log
cd /d "%~dp0"
call "%~dp0stop.bat" quiet
start "" pythonw "%~dp0server.py"
