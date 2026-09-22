@echo off
rem Windows: double-click to start the annotation site.
cd /d "%~dp0"

rem Prefer the "py" launcher; "python" may be the Microsoft Store stub.
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
if not errorlevel 1 (
    py -3 server.py %*
    goto :done
)
python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
if not errorlevel 1 (
    python server.py %*
    goto :done
)

echo Python 3.8 or newer was not found.
echo Install it from https://www.python.org/downloads/
echo During setup, tick "Add python.exe to PATH". Then double-click start.bat again.

:done
pause
