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
echo [1/3] ставлю зависимости...
python -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo не получилось поставить зависимости, см. ошибку выше.
  pause
  exit /b 1
)
echo [2/3] ищу папки Сток и Бланки...
python setup_config.py
if errorlevel 1 (
  pause
  exit /b 1
)
echo [3/3] включаю автозапуск и запускаю...
python autostart.py install
echo.
echo Готово. Окно можно закрыть, загрузчик работает в фоне.
echo Посмотреть, что он делает: STATUS.bat. Выключить: UNINSTALL.bat.
pause
