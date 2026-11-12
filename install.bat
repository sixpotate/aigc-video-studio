@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "AIGC_BOOTSTRAP="
if exist "%~dp0app\runtime\python-base\.aigc-python-base" if exist "%~dp0app\runtime\python-base\python.exe" set "AIGC_BOOTSTRAP=portable"
if defined AIGC_BOOTSTRAP goto run
py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 set "AIGC_BOOTSTRAP=py -3.12"
if defined AIGC_BOOTSTRAP goto run
python -c "import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 set "AIGC_BOOTSTRAP=python"
if defined AIGC_BOOTSTRAP goto run
echo Python 3.12 64-bit was not found. Downloading the official local runtime...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap-python.ps1"
if errorlevel 1 goto failed
set "AIGC_BOOTSTRAP=portable"

:run
if "%AIGC_BOOTSTRAP%"=="portable" goto portable
%AIGC_BOOTSTRAP% -X utf8 "%~dp0scripts\install.py" %*
goto done
:portable
"%~dp0app\runtime\python-base\python.exe" -X utf8 "%~dp0scripts\install.py" %*
:done
set "AIGC_EXIT=%errorlevel%"
if not "%AIGC_EXIT%"=="0" echo Installation did not finish. See the message above.
pause
exit /b %AIGC_EXIT%

:failed
echo Python preparation failed. Existing files were preserved.
pause
exit /b 1
