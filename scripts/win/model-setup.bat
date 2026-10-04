@echo off
rem Thin wrapper: model-setup is implemented once, in Python (scripts\model_setup.py), for every OS.
where py >nul 2>nul && ( py -3 "%~dp0..\model_setup.py" %* & goto :done )
where python >nul 2>nul && ( python "%~dp0..\model_setup.py" %* & goto :done )
echo model-setup needs Python 3 (standard library only, nothing to pip install).
echo Install it with:  winget install Python.Python.3.12   (or https://www.python.org/downloads/)
exit /b 1
:done
if errorlevel 1 pause
