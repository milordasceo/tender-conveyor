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

echo [1/3] ставлю зависимость...
python -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo не получилось поставить requests, см. ошибку выше.
  pause
  exit /b 1
)

echo [2/3] ищу папки Сток и Бланки...
python setup_config.py
if errorlevel 1 (
  pause
  exit /b 1
)

echo [3/3] один проход по Стоку...
python stock_docs_fetcher.py --once

echo.
echo Готово. Подробности в stock_docs_fetcher.log рядом с этим файлом.
pause
