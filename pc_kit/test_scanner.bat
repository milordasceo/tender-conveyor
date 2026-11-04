@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo Пробный поиск без выгрузки (в Сток ничего не пишется)...
python kit.py scan --dry-run
pause
