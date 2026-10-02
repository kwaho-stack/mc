@echo off
rem Hourly random clicker - run profile 1 in console (stop: Ctrl+C, abort macro: F12)
cd /d "%~dp0"
title HourlyClicker - Profile 1
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0HourlyClicker.ps1" -Run -ProfileNo 1
pause
