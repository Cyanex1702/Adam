@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME=%~dp0runtime\python"
set "PYTHONPATH=%~dp0backend"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ADAM_ASSETS_ROOT=%~dp0"
if not exist "%PYTHONHOME%\python.exe" (
  echo The offline Python runtime is missing. Extract the complete source-with-model ZIP.
  echo For a Git checkout, follow the source setup instructions in README.md.
  if not "%ADAM_NO_PAUSE%"=="1" pause
  exit /b 1
)
"%PYTHONHOME%\python.exe" -s -m adam.portable %*
set "adamExit=%ERRORLEVEL%"
if not "%adamExit%"=="0" if not "%ADAM_NO_PAUSE%"=="1" pause
exit /b %adamExit%
