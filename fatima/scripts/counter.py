#!/usr/bin/env python3
"""Счётчик тендеров в «Госзакупки/Цены/<город>/счётчик.json» (локальная копия файла).

Формат: {"В городе": N, "Загород": N, "С ограничениями": N, "обновлено": "YYYY-MM-DD HH:MM"}.
Фатима делает +1 у папки, куда положила тендер. Бот, который ищет цены, вычитает 1, когда забирает тендер.
Скрипт с Drive не работает: файл скачивают rclone copyto/cat, правят здесь, заливают rclone copyto.

Подкоманды:
  show  <файл>                         — показать
  inc   <файл> <категория> [--by N]     — +N (по умолчанию 1) и время обновления
  count                                 — посчитать папки тендеров по выводу
                                          `rclone lsf -R --dirs-only 'gosplan:Госзакупки/Цены/<город>'` со stdin
  init  <файл> [--force]                — создать файл; счёт берёт со stdin (как у count)
Время «обновлено» — по часам бокса (TZ) или --tz Europe/Berlin.
Категории: «В городе», «Загород», «С ограничениями» (подпапки «Лицензии», «Опыт» и любые другие
внутри категории считаются в неё).
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

CATS = ["В городе", "Загород", "С ограничениями"]
TENDER = re.compile(r"^[0-9]{6,}$")


def now(tz):
    if tz:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def load(p):
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    for c in CATS:
        if not isinstance(d.get(c), int) or isinstance(d.get(c), bool):
            raise SystemExit(f"в {p} поле «{c}» не целое: {d.get(c)!r} — не править вслепую, сообщить владельцу")
    return d


def save(p, d):
    out = {c: d[c] for c in CATS}
    out["обновлено"] = d["обновлено"]
    for k, v in d.items():  # чужие поля (если бот с ценами добавил свои) не терять
        if k not in out:
            out[k] = v
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


def count(lines):
    res = {c: 0 for c in CATS}
    unknown = []
    for raw in lines:
        parts = [x for x in raw.strip().strip("/").split("/") if x]
        if not parts:
            continue
        # папка тендера: последний элемент — номер, и выше по пути номеров нет
        if not TENDER.match(parts[-1]) or any(TENDER.match(x) for x in parts[:-1]):
            continue
        if parts[0] in res:
            res[parts[0]] += 1
        else:
            unknown.append("/".join(parts))
    if unknown:
        print(f"вне категорий (не посчитано): {', '.join(unknown)}", file=sys.stderr)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("file", type=Path)
    s = sub.add_parser("inc"); s.add_argument("file", type=Path); s.add_argument("category", choices=CATS)
    s.add_argument("--by", type=int, default=1); s.add_argument("--tz")
    sub.add_parser("count")
    s = sub.add_parser("init"); s.add_argument("file", type=Path); s.add_argument("--force", action="store_true")
    s.add_argument("--tz")
    a = ap.parse_args()
    if a.cmd == "show":
        print(json.dumps(load(a.file), ensure_ascii=False))
    elif a.cmd == "inc":
        if not a.file.exists():
            raise SystemExit(f"нет {a.file}: сначала init по текущим папкам")
        d = load(a.file)
        d[a.category] += a.by
        d["обновлено"] = now(a.tz)
        save(a.file, d)
    elif a.cmd == "count":
        print(json.dumps(count(sys.stdin), ensure_ascii=False))
    elif a.cmd == "init":
        if a.file.exists() and not a.force:
            raise SystemExit(f"{a.file} уже есть — не затираю (--force, если точно надо)")
        d = count(sys.stdin)
        d["обновлено"] = now(a.tz)
        save(a.file, d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
