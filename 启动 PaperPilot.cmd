@echo off
setlocal
call "%~dp0run.cmd"  %*
if errorlevel 1 (
  echo PaperPilot could not complete this operation. See the message above.
  pause
  exit /b 1
)
exit /b 0
