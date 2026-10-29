#!/usr/bin/env python3
### ЧТО ДЕЛАЕТ: добор очереди pending по одной закупке и утренний поиск Кузнеца под общей блокировкой.
###   run    — цикл: gosplan_scanner.py --limit 1, пауза, пока pending не пуст. новый поиск не запускает.
###   start  — запустить run в фоне, если не запущен и pending > 0 (идемпотентно).
###   status — json: работает ли добор, pending, выгружено всего и за час, последний прогон.
###   daily  — утренний прогон: pending > 0 или добор работает — только start; иначе поиск --limit 1, затем start.
### ЗАПУСК: python gosplan_drain.py run|start|status|daily
### ЗАВИСИМОСТИ: python 3.10+, стандартная библиотека. linux (fcntl). рядом gosplan_scanner.py.
### ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ: GOSPLAN_STATE_DIR (как у сканера, иначе scripts/state);
###   KUZNETS_CONFIG (config.novosibirsk.yaml), KUZNETS_REMOTE (gosplan:Госзакупки/Сток),
###   KUZNETS_PYTHON (../.venv/bin/python, иначе текущий), DRAIN_INTERVAL (30 с, старт-к-старту),
###   DRAIN_BACKOFF (300 с после ошибки или прогона без движения очереди).
### ВЫХОД: state_dir/drain_status.json, logs/drain.log. блокировка state_dir/kuznets_run.lock общая для run и daily.
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK_BUSY = 75


def env(name, default):
    return os.environ.get(name) or default


CONFIG = env("KUZNETS_CONFIG", "config.novosibirsk.yaml")
REMOTE = env("KUZNETS_REMOTE", "gosplan:Госзакупки/Сток")
INTERVAL = float(env("DRAIN_INTERVAL", "30"))
BACKOFF = float(env("DRAIN_BACKOFF", "300"))


def python_bin():
    venv = HERE.parent / ".venv" / "bin" / "python"
    return env("KUZNETS_PYTHON", str(venv) if venv.exists() else sys.executable)


def state_dir():
    raw = os.environ.get("GOSPLAN_STATE_DIR")
    p = Path(raw).expanduser() if raw else HERE / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def registry_file():
    # то же имя, что у сканера: sha1 строки remote, 12 знаков
    key = hashlib.sha1(REMOTE.strip().encode("utf-8")).hexdigest()[:12]
    return state_dir() / f"export_{key}.json"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def pending_count():
    reg = read_json(registry_file()) or {}
    return len(reg.get("pending") or [])


def log_file():
    d = HERE / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "drain.log"


def log(msg):
    with open(log_file(), "a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} {msg}\n")


def try_lock():
    # None — блокировку держит другой процесс (добор или утренний прогон)
    fh = open(state_dir() / "kuznets_run.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def lock_busy():
    fh = try_lock()
    if fh is None:
        return True
    fh.close()
    return False


def scanner(extra):
    cmd = [python_bin(), str(HERE / "gosplan_scanner.py"), "-c", CONFIG, "--remote", REMOTE] + extra
    p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, close_fds=True)
    with open(log_file(), "a", encoding="utf-8") as fh:
        fh.write(p.stderr)
    out = {}
    for line in p.stdout.splitlines():
        k, _, v = line.partition(":")
        if v.strip().isdigit():
            out[k.strip()] = int(v.strip())
    err_lines = [l for l in p.stderr.splitlines() if l.strip()]
    # для отчёта — последняя строка с причиной сбоя, иначе последняя строка лога
    keys = ("rclone", "ошибка", "сбой", "401", "invalid_grant", "token", "Traceback", "Error")
    hits = [l for l in err_lines if any(k in l for k in keys)]
    return p.returncode, out, (hits or err_lines or [""])[-1]


def status_path():
    return state_dir() / "drain_status.json"


def _on_term(signum, frame):
    raise SystemExit(f"сигнал {signum}")


def cmd_run():
    signal.signal(signal.SIGTERM, _on_term)
    lock = try_lock()
    if lock is None:
        print("добор уже работает или идёт утренний прогон — выход")
        return 0
    st = {
        "pid": os.getpid(), "state": "running", "started_at": now_iso(), "last_run_at": None,
        "last_exit": None, "uploaded_total": 0, "pending_left": pending_count(),
        "last_progress_at": None, "last_error": None, "interval": INTERVAL,
    }
    write_json(status_path(), st)
    log(f"добор: старт, pending {st['pending_left']}, интервал {INTERVAL:g} с")
    try:
        while True:
            before = pending_count()
            if before == 0:
                # пустая очередь: сканер с --limit 1 начал бы новый поиск — не запускаем
                st.update(state="done", pending_left=0)
                write_json(status_path(), st)
                log(f"добор: очередь пуста, выгружено за сессию {st['uploaded_total']}")
                return 0
            t0 = time.monotonic()
            rc, out, last = scanner(["--limit", "1"])
            after = pending_count()
            up = out.get("выгружено", 0)
            st.update(last_run_at=now_iso(), last_exit=rc, pending_left=after)
            st["uploaded_total"] += up
            moved = after < before
            if moved:
                st["last_progress_at"] = st["last_run_at"]
            log(f"добор: код {rc}, выгружено {up}, pending {before} -> {after}")
            if rc == 0 and after == 0:
                st.update(state="done", last_error=None)
                write_json(status_path(), st)
                log(f"добор: очередь пуста, выгружено за сессию {st['uploaded_total']}")
                return 0
            if rc in (0, 3) and moved:
                st["last_error"] = None
                write_json(status_path(), st)
                time.sleep(max(0.0, INTERVAL - (time.monotonic() - t0)))
                continue
            # код не 0/3 или очередь не сдвинулась (rclone 401, lsf, api) — пауза и дальше
            rep = read_json(state_dir() / "run_report.json") or {}
            st["last_error"] = f"код {rc}; rclone_failures {rep.get('rclone_failures')}; {last}"[:500]
            write_json(status_path(), st)
            log(f"добор: без движения, пауза {BACKOFF:g} с: {st['last_error']}")
            time.sleep(BACKOFF)
    except BaseException as e:
        st.update(state="stopped", last_error=f"{type(e).__name__}: {e}"[:500])
        write_json(status_path(), st)
        log(f"добор: остановлен: {st['last_error']}")
        raise
    finally:
        lock.close()


def cmd_start():
    if lock_busy():
        print("добор уже работает (или идёт утренний прогон) — второй не запускаю")
        return 0
    n = pending_count()
    if n == 0:
        print("pending пуст — добор не нужен")
        return 0
    with open(log_file(), "a", encoding="utf-8") as fh:
        p = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "run"], cwd=HERE,
            stdin=subprocess.DEVNULL, stdout=fh, stderr=fh, start_new_session=True,
        )
    time.sleep(2)
    if p.poll() is not None:
        print(f"добор не запустился, код {p.returncode}; см. {log_file()}")
        return 1
    print(f"добор запущен, pid {p.pid}, pending {n}")
    return 0


def cmd_status():
    reg = read_json(registry_file()) or {}
    tenders = reg.get("tenders") or {}
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    last_hour = 0
    for rec in tenders.values():
        try:
            at = datetime.fromisoformat(str(rec.get("at")))
        except (TypeError, ValueError):
            continue
        if rec.get("status") == "exported" and at.tzinfo and at >= hour_ago:
            last_hour += 1
    out = {
        "drain_running": lock_busy(),
        "pending": len(reg.get("pending") or []),
        "exported_total": sum(1 for r in tenders.values() if r.get("status") == "exported"),
        "exported_last_hour": last_hour,
        "last_completed_at": reg.get("last_completed_at"),
        "drain_status": read_json(status_path()),
        "run_report": {k: (read_json(state_dir() / "run_report.json") or {}).get(k)
                       for k in ("date", "found", "new", "exported", "pending_left",
                                 "http_429", "rclone_failures", "exit_code")},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_daily():
    if pending_count() > 0 or lock_busy():
        print("pending не пуст или добор работает — поиск не нужен")
        return cmd_start()
    lock = try_lock()
    if lock is None:
        print("блокировка занята — пропуск")
        return LOCK_BUSY
    try:
        log("утренний прогон: поиск + 1 выгрузка")
        rc, out, last = scanner(["--limit", "1"])
        log(f"утренний прогон: код {rc}, {out}")
        print(f"код {rc}; найдено {out.get('найдено')}; новых {out.get('новых')}; "
              f"выгружено {out.get('выгружено')}; pending {pending_count()}")
        if rc not in (0, 3):
            print(f"ошибка: {last}")
    finally:
        lock.close()
    if rc in (0, 3) and pending_count() > 0:
        cmd_start()
    return rc


def main():
    cmds = {"run": cmd_run, "start": cmd_start, "status": cmd_status, "daily": cmd_daily}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        print("использование: gosplan_drain.py run|start|status|daily", file=sys.stderr)
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
