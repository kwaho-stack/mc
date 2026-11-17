@echo off
cd /d "%~dp0"
where python >NUL 2>NUL || (echo [!] Python is not installed. Install Python 3.11+ from python.org and check "Add python.exe to PATH". & pause & exit /b 1)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done. Run start.bat
pause
