@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "AIGC_PYTHON=%~dp0app\work\local_test\venv\Scripts\python.exe"
if not exist "%AIGC_PYTHON%" (
  echo Python environment is missing. Run install.bat first.
  pause
  exit /b 1
)
"%AIGC_PYTHON%" -X utf8 "%~dp0app\server.py"
set "AIGC_EXIT=%errorlevel%"
if not "%AIGC_EXIT%"=="0" pause
exit /b %AIGC_EXIT%
