@echo off
setlocal
if "%~1"=="" (
  echo Usage: run_report.bat CONTEST_CODE
  echo Example: run_report.bat START254
  exit /b 1
)
python main.py --contest "%~1" --send-email
if errorlevel 1 (
  echo.
  echo Report generation failed. Check logs\contest_report.log
  exit /b %errorlevel%
)
endlocal
