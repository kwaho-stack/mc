@echo off
rem Hourly random clicker - run profile 2 in console (stop: Ctrl+C, abort macro: F12)
cd /d "%~dp0"
title HourlyClicker - Profile 2
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0HourlyClicker.ps1" -Run -ProfileNo 2
pause
