#!/usr/bin/env python3
"""Проверить tender.json по схеме tender.schema.json (лежит рядом) и здравому смыслу.

Запуск:
  python3 validate_tender.py <tender.json> [--folder-name <номер>]
Ошибки (код 1) — файл не по схеме, заливать нельзя.
Предупреждения (код 0) — перечитать документы: сумма позиций не равна НМЦК,
категория расходится с условиями, пустые особые пометки при подъёме/разгрузке в условиях, «не указано» в важных полях и т.п.
Без зависимостей: поддержано подмножество JSON Schema, которое использует схема
(type, const, enum, required, properties, additionalProperties, items, minItems,
minLength, pattern, minimum).
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = Path(__file__).with_name("tender.schema.json")
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
NONE_WORDS = ("не треб", "не указано", "нет", "отсутству", "не установлен", "не предусмотрен")


def type_ok(v, t):
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])


def check(v, s, path, errs):
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: должно быть {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} не из {s['enum']}")
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(type_ok(v, t) for t in ts):
            errs.append(f"{path}: тип {type(v).__name__}, нужно {'/'.join(ts)}")
            return
    if isinstance(v, str):
        if len(v.strip()) < s.get("minLength", 0):
            errs.append(f"{path}: пусто")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: {v!r} не по шаблону {s['pattern']}")
    if type_ok(v, "number") and "minimum" in s and v < s["minimum"]:
        errs.append(f"{path}: меньше {s['minimum']}")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}.{k}: нет поля")
        props = s.get("properties", {})
        for k, x in v.items():
            if k in props:
                check(x, props[k], f"{path}.{k}", errs)
            elif s.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: лишнее поле")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            errs.append(f"{path}: нужно не меньше {s['minItems']} элементов")
        if "items" in s:
            for i, x in enumerate(v):
                check(x, s["items"], f"{path}[{i}]", errs)


def is_none(text):
    t = (text or "").strip().lower()
    return any(t.startswith(w) for w in NONE_WORDS)


def sanity(d, folder_name):
    w = []
    if folder_name and d.get("number") != folder_name:
        w.append(f"number {d.get('number')!r} не равен имени папки {folder_name!r}")
    try:
        datetime.fromisoformat(d["deadline"]["iso"])
    except (KeyError, TypeError, ValueError):
        w.append("deadline.iso не разбирается как дата")
    items = d.get("items") or []
    totals = [i.get("total_price") for i in items]
    amount = (d.get("nmck") or {}).get("amount")
    if amount is not None and totals and all(isinstance(t, (int, float)) for t in totals):
        if abs(sum(totals) - amount) > 0.01 * max(amount, 1):
            w.append(f"сумма позиций {sum(totals):.2f} не равна НМЦК {amount:.2f} — сверить с обоснованием НМЦК")
    for n, i in enumerate(items):
        q, up, tp = i.get("quantity"), i.get("unit_price"), i.get("total_price")
        if all(isinstance(x, (int, float)) for x in (q, up, tp)) and abs(q * up - tp) > max(1.0, 0.01 * tp):
            w.append(f"items[{n}]: количество × цена = {q * up:.2f}, а total_price {tp:.2f}")
        if not i.get("characteristics"):
            w.append(f"items[{n}]: нет характеристик — проверить ТЗ")
    c = d.get("conditions") or {}
    restricted = not is_none(c.get("licenses_permits")) or not is_none(c.get("experience"))
    cat = d.get("category")
    if restricted and cat != "С ограничениями":
        w.append("лицензии/опыт указаны как требование, а категория не «С ограничениями»")
    if not restricted and cat == "С ограничениями" and "огранич" not in (d.get("category_reason") or "").lower():
        w.append("категория «С ограничениями» без лицензий/опыта — причина должна называть ограничение")
    notes = d.get("special_notes") or []
    hint = " ".join([(d.get("delivery") or {}).get("notes") or "", (d.get("delivery") or {}).get("address_notice") or ""]).lower()
    if not notes and re.search(r"этаж|подъ[её]м|разгруз|монтаж|сборк|\bчас|время", hint):
        w.append("special_notes пусто, а в условиях доставки есть подъём/разгрузка/монтаж/время — перенести в особые пометки")
    for path in ("nmck.amount", "delivery.address", "delivery.city", "deadline.local"):
        a, b = path.split(".")
        v = (d.get(a) or {}).get(b)
        if v is None or (isinstance(v, str) and v.strip().lower() == "не указано"):
            w.append(f"{path}: не указано — перечитать извещение")
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--folder-name")
    a = ap.parse_args()
    try:
        d = json.loads(a.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"ОШИБКА: не читается как JSON: {e}")
        return 1
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errs = []
    check(d, schema, "$", errs)
    warns = sanity(d, a.folder_name) if isinstance(d, dict) and not errs else []
    for e in errs:
        print(f"ОШИБКА: {e}")
    for x in warns:
        print(f"предупреждение: {x}")
    print(f"итого: ошибок {len(errs)}, предупреждений {len(warns)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
