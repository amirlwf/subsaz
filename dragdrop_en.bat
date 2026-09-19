@echo off
REM Drag a video file onto this .bat -> SRT appears next to it
if "%~1"=="" (
  echo Drag a video file onto this file.
  pause
  exit /b
)
cd /d "%~dp0"
python cli.py "%~1" --lang en --model small
pause
