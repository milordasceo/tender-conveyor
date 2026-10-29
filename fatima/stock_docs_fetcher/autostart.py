# автозапуск загрузчика на windows: install / uninstall / status
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "stock_docs_fetcher.py"
LOG = HERE / "stock_docs_fetcher.log"
STARTUP = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
LAUNCHER = STARTUP / "stock_docs_fetcher.cmd"


def pythonw() -> Path:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def running_pids() -> list[str]:
    ps = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*stock_docs_fetcher.py*' } "
        "| ForEach-Object { $_.ProcessId }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return [x.strip() for x in out.stdout.split() if x.strip().isdigit()]


def start() -> None:
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(pythonw()), str(SCRIPT)], cwd=str(HERE), creationflags=flags, close_fds=True)


def install() -> int:
    STARTUP.mkdir(parents=True, exist_ok=True)
    LAUNCHER.write_text(
        "@echo off\r\nchcp 65001 >nul\r\n"
        f'cd /d "{HERE}"\r\n'
        f'start "" "{pythonw()}" "{SCRIPT}"\r\n',
        encoding="utf-8",
    )
    print(f"автозапуск при входе в windows: {LAUNCHER}")
    if running_pids():
        print("загрузчик уже работает")
    else:
        start()
        print("загрузчик запущен в фоне, проверяет Сток раз в минуту")
    return 0


def uninstall() -> int:
    if LAUNCHER.exists():
        LAUNCHER.unlink()
        print("автозапуск убран")
    pids = running_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    print(f"остановлено процессов: {len(pids)}")
    return 0


def status() -> int:
    print("автозапуск:", "включён" if LAUNCHER.exists() else "выключен")
    print("работает:", "да" if running_pids() else "нет")
    if LOG.exists():
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
        print("\nпоследние строки лога:")
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    sys.exit({"install": install, "uninstall": uninstall, "status": status}[cmd]())
