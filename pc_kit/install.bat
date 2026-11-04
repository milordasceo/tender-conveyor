@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/windows/
  echo При установке отметьте галочку "Add python.exe to PATH".
  pause
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Нужен Python 3.10 или новее. Сейчас установлен:
  python --version
  pause
  exit /b 1
)
echo Ставлю зависимости...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Не получилось поставить зависимости, см. ошибку выше.
  pause
  exit /b 1
)
python kit.py configs
echo.
echo Готово. Дальше: проверьте settings.ini и запустите run_scanner.bat
pause
