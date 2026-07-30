@echo off
cd /d "%~dp0"
python "%~dp0dist\session-bridge-v1.0.0.pyz" serve
pause
