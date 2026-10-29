@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not defined PAPERPILOT_PYTHON set "PAPERPILOT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PAPERPILOT_PYTHON%" (
  echo Python not found. Follow the Windows setup instructions in README.md.
  exit /b 1
)
"%PAPERPILOT_PYTHON%" -c "import pdfplumber,pypdfium2,pypdf" >nul 2>&1
if errorlevel 1 (
  echo Python dependencies missing. See README.md.
  exit /b 1
)
if not exist "node_modules\katex\dist\katex.min.js" (
  echo Node dependencies missing. Run npm.cmd ci in this folder.
  exit /b 1
)
"%PAPERPILOT_PYTHON%" -m paperpilot.launcher %*
exit /b %errorlevel%
