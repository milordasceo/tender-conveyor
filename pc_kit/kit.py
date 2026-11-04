#!/usr/bin/env python3
# единая точка входа набора pc_kit: читает settings.ini, генерирует конфиги сканера и загрузчика,
# запускает их, ставит/снимает задачи в планировщике windows (schtasks), показывает статус.
# вызов: python kit.py configs | scan [--dry-run] | fetch [--once] | schedule | unschedule | status
import configparser
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "settings.ini"
SCANNER_DIR = HERE / "scanner"
FETCHER_DIR = HERE / "fetcher"
STATE_DIR = HERE / "state"
LOGS_DIR = HERE / "logs"
TASK_SCAN = "TenderKit_Scanner"
TASK_SCAN_REPEAT = "TenderKit_Scanner_Repeat"
TASK_FETCH = "TenderKit_Fetcher"

PURCHASE_KINDS = {
    "auction": {"fz44": ["epNotificationEF2020"],
                "fz223": ["purchaseNoticeAE", "purchaseNoticeAESMBO", "purchaseNoticeOA"]},
    "zk": {"fz44": ["epNotificationEZK2020"],
           "fz223": ["purchaseNoticeZK", "purchaseNoticeZKESMBO"]},
}


def die(msg):
    print("ОШИБКА: " + msg)
    sys.exit(2)


def split(v):
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


def load():
    if not SETTINGS.exists():
        die(f"нет файла {SETTINGS}")
    cp = configparser.ConfigParser(inline_comment_prefixes=None)
    with open(SETTINGS, encoding="utf-8-sig") as f:  # блокнот может дописать BOM
        cp.read_file(f)
    try:
        s = {
            "stock": cp.get("папки", "сток").strip().strip('"'),
            "blanks": cp.get("папки", "бланки").strip().strip('"'),
            "regions": [int(x) for x in split(cp.get("поиск", "регион"))],
            "cities": split(cp.get("поиск", "город", fallback="")),
            "keywords": split(cp.get("поиск", "ключевые_слова", fallback="")),
            "kw_all": cp.get("поиск", "все_слова", fallback="нет").strip().lower() in ("да", "yes", "1", "true"),
            "supply_only": cp.get("поиск", "только_поставка", fallback="да").strip().lower() in ("да", "yes", "1", "true"),
            "supply_words": split(cp.get("поиск", "слова_поставки", fallback="поставк")),
            "stop_words": split(cp.get(
                "поиск", "стоп_слова",
                fallback="оказание услуг, выполнение работ, услуги по, работы по, аренда, ремонт, техническое обслуживание, медицин, лекарств, препарат, реактив, реагент, шприц, перевязоч, лаборатор, диагностик, стоматолог, ортопед, протез, медизделий, хирург, катетер, инфузион, тест-полоск, тест-полос, дезинфиц, стерилиз, стерильн, анализатор, глюкометр, глюкоз, рентген, маммограф, инъекц, бактерицид, облучател, эндоскоп, биопси, ларингеаль, плевральн, дренир, кювет, коагулометр, пациент, термоиндикатор, абсорбент, бактериальн, влагообменник, трехсекцион, ватн, мочевой, кдл, ивд, диаграммн, рециркулятор, вспомогательного назначения, подгузник",
            )),
            "min": int(float(cp.get("поиск", "сумма_от"))),
            "max": int(float(cp.get("поиск", "сумма_до"))),
            "laws": split(cp.get("поиск", "законы")),
            "kinds": split(cp.get("поиск", "виды")),
            "d_from": float(cp.get("поиск", "срок_от_дней").replace(",", ".")),
            "d_to": float(cp.get("поиск", "срок_до_дней").replace(",", ".")),
            "limit": int(cp.get("поиск", "лимит", fallback="0") or 0),
            "scan_time": cp.get("расписание", "сканер_время", fallback="07:00").strip(),
            "scan_every": int(cp.get("расписание", "сканер_каждые_минут", fallback="0") or 0),
            "fetch_interval": int(cp.get("расписание", "загрузчик_интервал_сек", fallback="60") or 60),
        }
    except (configparser.Error, ValueError) as e:
        die(f"settings.ini заполнен неверно: {e}")
    sources = []
    for law in s["laws"]:
        if law not in ("44", "223"):
            die(f"законы: допустимо 44 и 223, а не «{law}»")
        sources.append("fz" + law)
    for k in s["kinds"]:
        if k not in PURCHASE_KINDS:
            die(f"виды: допустимо zk и auction, а не «{k}»")
    if not sources or not s["kinds"] or not s["regions"]:
        die("регион, законы и виды не должны быть пустыми")
    if s["min"] > s["max"] or s["d_from"] > s["d_to"]:
        die("«от» больше «до» в суммах или сроках")
    s["sources"] = sources
    return s


def num(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def write_configs(s):
    types = {src: sorted({t for k in s["kinds"] for t in PURCHASE_KINDS[k][src]}) for src in s["sources"]}
    scanner_cfg = {
        "base_url": "https://v2test.gosplan.info",  # тестовый api без ключа
        "api_key": None,
        "state_dir": str(STATE_DIR),
        "sources": s["sources"],
        "purchase_kinds": {k: PURCHASE_KINDS[k] for k in s["kinds"]},
        "filters": {
            "keywords": s["keywords"], "keywords_all": s["kw_all"], "okpd2": [],
            "supply_only": s["supply_only"],
            "supply_words": s["supply_words"] or (["поставк"] if s["supply_only"] else []),
            "stop_words": s["stop_words"],
            "min_budget": s["min"], "max_budget": s["max"],
            "since": "auto", "published_after": None, "published_before": None,
            "regions": s["regions"], "delivery_cities": s["cities"], "stage": 1,
            "deadline_from": f"+{num(s['d_from'])}d", "deadline_to": f"+{num(s['d_to'])}d",
            "currency": "RUB", "purchase_types": types,
        },
        "limits": {"page_size": 100, "max_pages_per_source": 50, "pause_ms": 0, "timeout_sec": 60},
        "run": {"limit": s["limit"]},
        "export": {"dir": s["stock"], "city_strict": bool(s["cities"])},
        "output": {"dir": str(HERE / "tenders"), "keep_days": 90},
    }
    import yaml
    (SCANNER_DIR / "config.yaml").write_text(
        "# СГЕНЕРИРОВАНО из settings.ini (kit.py). Правьте settings.ini, а не этот файл.\n"
        + yaml.safe_dump(scanner_cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    fetcher_cfg = {
        "stock_dir": s["stock"], "blanks_dir": s["blanks"],
        "scan_interval_sec": s["fetch_interval"], "download_pause_sec": 3,
        "request_timeout_sec": 60, "http_retries": 3, "retry_backoff_sec": 5,
        "max_file_size_mb": 200, "retry_delay_min": 30, "max_attempts": 5,
        "log_file": str(LOGS_DIR / "fetcher.log"), "log_max_bytes": 5242880, "log_backups": 5,
        "lock_file": str(STATE_DIR / "stock_docs_fetcher.lock"),
        "verify_ssl": True, "ssl_fallback_hosts": ["zakupki.gov.ru"],
    }
    (FETCHER_DIR / "config.json").write_text(json.dumps(fetcher_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    STATE_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)


# технические строки сканера (адреса, сводка для ботов, дубли по номеру) — только в журнал
TECH_LINE = re.compile(r"^(\[fz\d+\]|найдено:|новых:|выгружено:|since:|429:|pending:|dry-run:|\d{6,}: )")


def say(msg):
    # вывод в консоль, только если она есть (у pythonw/планировщика stdout = None)
    out = sys.stdout
    if out is None:
        return
    try:
        out.write(msg + "\n")
        out.flush()
    except Exception:
        pass


def check_dir(path, name):
    if not Path(path).is_dir():
        die(f"папка «{name}» не найдена: {path}\nПроверьте путь в settings.ini и что Google Drive для ПК запущен.")


def env():
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    e.pop("GOSPLAN_STATE_DIR", None)
    return e


def cmd_scan(extra):
    s = load()
    write_configs(s)
    dry = "--dry-run" in extra
    if not dry:
        check_dir(s["stock"], "Сток")
    args = [sys.executable, "-u", str(SCANNER_DIR / "gosplan_scanner.py"), "-c", str(SCANNER_DIR / "config.yaml")]
    # в dry-run «Сток» нужен только чтобы сравнить с реестром (новых); запись не идёт
    if not dry or Path(s["stock"]).is_dir():
        args += ["--export", s["stock"]]
    args += extra
    log = LOGS_DIR / "scanner.log"
    say(f"Сканер запущен{' (ПРОБНЫЙ, без выгрузки)' if dry else ''}. Журнал: {log}")
    say("Запросы к gosplan идут не чаще раза в ~10 с — это нормально, ждите.")
    with open(log, "a", encoding="utf-8") as lf:
        lf.write(f"\n===== запуск {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        lf.flush()
        p = subprocess.Popen(args, cwd=SCANNER_DIR, env=env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in p.stdout:
            lf.write(line)
            lf.flush()
            # технические строки (адреса запросов, сводка для ботов) — только в журнал
            if not TECH_LINE.match(line):
                say(line.rstrip("\n"))
        p.wait()
        lf.write(f"код выхода: {p.returncode}\n")
    if p.returncode not in (0, 3):
        say(f"Сканер завершился с ошибкой (код {p.returncode}), подробности в {log}")
    elif p.returncode == 3:
        say("Часть тендеров осталась в очереди — выгрузятся при следующем запуске.")
    # 0 — всё выгружено, 3 — часть осталась в очереди до следующего запуска (это нормально)
    return 0 if p.returncode in (0, 3) else p.returncode


def cmd_fetch(extra):
    s = load()
    write_configs(s)
    check_dir(s["stock"], "Сток")
    check_dir(s["blanks"], "Бланки")
    args = [sys.executable, str(FETCHER_DIR / "stock_docs_fetcher.py"), "--config", str(FETCHER_DIR / "config.json")] + extra
    return subprocess.run(args, cwd=FETCHER_DIR, env=env()).returncode


def schtasks(*a):
    p = subprocess.run(["schtasks", *a], capture_output=True, text=True, errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


def pythonw():
    w = Path(sys.executable).with_name("pythonw.exe")
    return w if w.exists() else Path(sys.executable)


def cmd_schedule():
    if os.name != "nt":
        die("расписание ставится только на Windows")
    s = load()
    write_configs(s)
    cmd_unschedule(quiet=True)
    kit = f'"{pythonw()}" "{HERE / "kit.py"}"'
    rc, out = schtasks("/Create", "/F", "/TN", TASK_SCAN, "/SC", "DAILY", "/ST", s["scan_time"], "/TR", f"{kit} scan")
    print(("OK  " if rc == 0 else "СБОЙ ") + f"сканер ежедневно в {s['scan_time']}" + ("" if rc == 0 else f": {out}"))
    if s["scan_every"] > 0:
        rc, out = schtasks("/Create", "/F", "/TN", TASK_SCAN_REPEAT, "/SC", "MINUTE", "/MO", str(s["scan_every"]),
                           "/TR", f"{kit} scan")
        print(("OK  " if rc == 0 else "СБОЙ ") + f"сканер каждые {s['scan_every']} мин" + ("" if rc == 0 else f": {out}"))
    rc, out = schtasks("/Create", "/F", "/TN", TASK_FETCH, "/SC", "ONLOGON", "/TR", f"{kit} fetch")
    print(("OK  " if rc == 0 else "СБОЙ ") + "загрузчик при входе в Windows (работает постоянно)" + ("" if rc == 0 else f": {out}"))
    if rc == 0:
        schtasks("/Run", "/TN", TASK_FETCH)
        print("Загрузчик запущен прямо сейчас в фоне.")
    return 0


def cmd_unschedule(quiet=False):
    if os.name != "nt":
        die("только на Windows")
    for t in (TASK_SCAN, TASK_SCAN_REPEAT, TASK_FETCH):
        schtasks("/End", "/TN", t)
        rc, _ = schtasks("/Delete", "/F", "/TN", t)
        if not quiet:
            print(("удалена задача " if rc == 0 else "задачи не было: ") + t)
    if not quiet:
        # остановить загрузчик, если он ещё работает в фоне
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*stock_docs_fetcher.py*' } "
              "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
        print("Фоновый загрузчик остановлен.")
    return 0


def tail(path, n=15):
    if not path.exists():
        print("  (журнала пока нет)")
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    for line in lines:
        print("  " + line)


def cmd_status():
    s = load()
    print("== Папки ==")
    for name, p in (("Сток", s["stock"]), ("Бланки", s["blanks"])):
        ok = Path(p).is_dir()
        cnt = sum(1 for x in Path(p).iterdir() if x.is_dir()) if ok else 0
        print(f"  {name}: {p} -> " + (f"есть, папок тендеров: {cnt}" if ok else "НЕ НАЙДЕНА"))
    if os.name == "nt":
        print("== Задачи в Планировщике ==")
        for t in (TASK_SCAN, TASK_SCAN_REPEAT, TASK_FETCH):
            rc, out = schtasks("/Query", "/TN", t, "/FO", "LIST")
            if rc != 0:
                print(f"  {t}: нет")
                continue
            info = {}
            for line in out.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = v.strip()
            vals = list(info.values())
            print(f"  {t}: есть; " + "; ".join(vals[1:4]))
    print("== Сканер, последние строки журнала (logs\\scanner.log) ==")
    tail(LOGS_DIR / "scanner.log")
    print("== Загрузчик, последние строки журнала (logs\\fetcher.log) ==")
    tail(LOGS_DIR / "fetcher.log")
    return 0


def main(argv):
    if not argv:
        print(__doc__ or "вызов: python kit.py configs|scan|fetch|schedule|unschedule|status")
        return 2
    cmd, extra = argv[0], argv[1:]
    if cmd == "configs":
        write_configs(load())
        print("Настройки прочитаны, конфиги обновлены.")
        return 0
    return {"scan": lambda: cmd_scan(extra), "fetch": lambda: cmd_fetch(extra),
            "schedule": cmd_schedule, "unschedule": cmd_unschedule, "status": cmd_status}.get(
        cmd, lambda: die(f"неизвестная команда {cmd}"))()


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        try:
            if st is not None:
                st.reconfigure(errors="replace")
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
