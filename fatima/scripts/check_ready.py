#!/usr/bin/env python3
"""Готова ли папка тендера к разбору: смотрит docs_status.json.

Готова, если state == "done", error == null, documents[] не пуст
и у каждого документа status == "ok" и файл лежит в папке (если папка локальная).

Запуск:
  python3 check_ready.py <папка> [<папка> ...]        # локальные папки
  python3 check_ready.py --status-file docs_status.json # один файл (например, из rclone cat)
  rclone cat 'gosplan:Госзакупки/Бланки/<номер>/docs_status.json' | python3 check_ready.py --status-file -

Вывод: одна строка на папку «<номер>\tready» или «<номер>\tnot_ready\t<причина>».
Код выхода: 0 — все готовы, 1 — есть неготовые, 2 — ошибка запуска.
"""
import argparse
import json
import sys
from pathlib import Path


def check_status(st, folder=None):
    """Вернуть (готова, причина). folder — локальная папка для проверки файлов или None."""
    if not isinstance(st, dict):
        return False, "docs_status.json не объект"
    if st.get("state") != "done":
        return False, f"state={st.get('state')!r}, нужно 'done'"
    if st.get("error") is not None:
        return False, f"error={st.get('error')!r}"
    docs = st.get("documents")
    if not isinstance(docs, list) or not docs:
        return False, "documents пуст или не список"
    for d in docs:
        name = d.get("file") or d.get("name") or f"#{d.get('index')}"
        if d.get("status") != "ok":
            return False, f"документ {name}: status={d.get('status')!r}"
        if folder is not None and d.get("file") and not (folder / d["file"]).is_file():
            return False, f"документ {name}: файла нет в папке"
    return True, ""


def check_folder(folder):
    p = folder / "docs_status.json"
    if not p.is_file():
        return False, "нет docs_status.json"
    try:
        st = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return False, f"docs_status.json не читается: {e}"
    return check_status(st, folder)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", type=Path)
    ap.add_argument("--status-file", help="путь к docs_status.json или '-' для stdin")
    a = ap.parse_args()
    if not a.folders and not a.status_file:
        ap.error("нужна папка или --status-file")
    all_ok = True
    if a.status_file:
        raw = sys.stdin.read() if a.status_file == "-" else Path(a.status_file).read_text(encoding="utf-8-sig")
        try:
            st = json.loads(raw)
        except ValueError as e:
            print(f"-\tnot_ready\tdocs_status.json не JSON: {e}")
            return 1
        ok, why = check_status(st)
        num = st.get("number", "-") if isinstance(st, dict) else "-"
        print(f"{num}\tready" if ok else f"{num}\tnot_ready\t{why}")
        all_ok &= ok
    for f in a.folders:
        ok, why = check_folder(f)
        print(f"{f.name}\tready" if ok else f"{f.name}\tnot_ready\t{why}")
        all_ok &= ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
