@echo off
rem hsystem scheduler - settings / run window
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0hsystem.ps1"
if errorlevel 1 pause
