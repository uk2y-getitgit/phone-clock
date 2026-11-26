@echo off
rem Stop the Phone Clock server (use "stop.bat quiet" to suppress messages)
if /i "%1"=="quiet" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_server.ps1" -Quiet
) else (
  chcp 65001 >nul
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_server.ps1"
  timeout /t 2 >nul
)
