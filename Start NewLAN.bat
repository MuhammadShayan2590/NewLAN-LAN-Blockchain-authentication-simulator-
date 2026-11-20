@echo off
rem Double-click launcher for NewLAN
cd /d "%~dp0"

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY goto nopython

%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto notk

rem Prefer the no-console launchers so no black window stays open
where pythonw >nul 2>&1 && (start "" pythonw "%~dp0NewLAN.pyw" & exit /b 0)
where pyw >nul 2>&1 && (start "" pyw "%~dp0NewLAN.pyw" & exit /b 0)
start "" %PY% "%~dp0NewLAN.pyw"
exit /b 0

:nopython
echo Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer.
pause
exit /b 1

:notk
echo Python is installed but its tkinter component is missing.
echo Run the Python installer again, choose Modify, and tick "tcl/tk and IDLE".
pause
exit /b 1
