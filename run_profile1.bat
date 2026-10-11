@echo off
rem hsystem scheduler - run profile 1 in console (stop: Ctrl+C, abort macro: F12)
cd /d "%~dp0"
title hsystem - Profile 1
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0hsystem.ps1" -Run -ProfileNo 1
pause
