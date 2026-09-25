@echo off
rem WebView2 UI (TypeScript frontend + Python backend).
rem Always run with THIS repo's venv: the frontend bridge needs pywebview.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
if not exist "%ROOT%web_dist\index.html" (
  echo web_dist is missing. Build the frontend first:
  echo     cd web ^&^& npm install --include=dev ^&^& npm run build
  pause
  exit /b 1
)
start "" "%PY%" "%ROOT%webui.py"
