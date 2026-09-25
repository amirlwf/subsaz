@echo off
rem Always start with THIS repo's venv: the Persian bidi fix needs
rem arabic-reshaper + python-bidi, and a random `pythonw` on PATH will not
rem have them (then display() silently falls back to logical order and
rem Persian renders mirrored / with unjoined letters).
setlocal
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
start "" "%PY%" "%~dp0gui.py"
