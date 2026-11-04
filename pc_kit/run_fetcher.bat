@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo Загрузчик работает, пока открыто это окно. Остановить: закрыть окно или Ctrl+C.
python kit.py fetch
pause
