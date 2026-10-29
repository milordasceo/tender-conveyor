@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите его с https://www.python.org/downloads/windows/
  echo При установке отметьте галочку "Add python.exe to PATH", потом запустите этот файл снова.
  pause
  exit /b 1
)
python autostart.py status
pause
