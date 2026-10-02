@echo off
rem Hourly random clicker - settings / run window
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0HourlyClicker.ps1"
if errorlevel 1 pause
