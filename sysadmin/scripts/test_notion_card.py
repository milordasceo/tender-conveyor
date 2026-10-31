#!/usr/bin/env python3
"""Проверка notion_card.py на вариациях формата (синтетические данные) и на образце examples/0151100007126000034.
Запуск: python3 sysadmin/scripts/test_notion_card.py — только стандартная библиотека, в сеть не ходит."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "notion_card.py"
EXAMPLE = HERE.parent / "examples" / "0151100007126000034"

PRICES = "## Товар\n\n**Цена 1: 10,00 ₽**\n- Где купить: «Склад», г. Новосибирск, ул. Ленина, 1\n"

# (tender.json, расчёт в tender.md, ожидаемые свойства)
CASES = {
    "вложенная схема, жирные строки": (
        {"number": "1", "subject": "Бумажные полотенца 700 упак. и туалетная бумага 450 упак. на 2027 год", "nmck": {"amount": 1000, "currency": "RUB"},
         "deadline": {"local": "01.12.2026 10:00", "iso": "2026-12-01T10:00:00+07:00"},
         "delivery": {"city": "Новосибирск", "address": "г. Новосибирск, ул. Ленина, 2"}},
        "## Расчёт рентабельности (проверка)\n### Вариант А\n- Закупка: 500,00 ₽\n- Доставка: 100,00 ₽\n"
        "- Налог 15% от (1 000 − 500 − 100 = 400): 60,00 ₽\n- **Прибыль варианта А:** 340,00 ₽\n"
        "### Вариант Б\n- **Прибыль варианта Б:** 10,00 ₽\n**Вердикт:** да\n## Другое\n- **Прибыль варианта В:** 9 999 ₽\n",
        {"Полная цена": 1000, "Прибыль": 340.0, "Расходы": 660.0, "date:Подача до:start": "2026-12-01T10:00:00+07:00",
         "Товар": "Полотенца и туалетная бумага"},
    ),
    "плоская схема, нежирные строки, nmck числом": (
        {"number": "2", "nmck": 1000.0, "application_deadline": "01.12.2026 10:00 (время Новосибирска)",
         "delivery_address": "630000, г. Новосибирск, ул. Ленина, 2, этаж 7", "deliveries_count": 1,
         "links": {"zakupki_card": "https://zakupki.gov.ru/x"}},
        "## Расчёт рентабельности\n### Вариант А\n- Закупка: 2 × 250,00 = 500,00 ₽\n- Доставка: 100,00 ₽\n"
        "- Налог 15% от (1 000,00 − 500,00 − 100,00): 60,00 ₽\n- Прибыль варианта А (по ценам А): 340,00 ₽\n"
        "### Вариант Б\n- Прибыль варианта Б (по ценам Б): −20,50 ₽\n\n**Вердикт: рентабельно**\n",
        {"Полная цена": 1000.0, "Прибыль": 340.0, "Расходы": 660.0, "Город": "Новосибирск",
         "Ссылка": "https://zakupki.gov.ru/x", "date:Подача до:start": "2026-12-01T10:00:00+07:00"},
    ),
    "nmck строкой, руб., жирная строка целиком, без вариантов": (
        {"number": "3", "nmck": "1 000,00 руб.", "application_deadline": "01.12.2026 10:00 (МСК+4)",
         "location": "Бердск (в городе)"},
        "## Расчет рентабельности\n* Закупка: 500 руб.\n* Доставка — 100 руб.\n* Налог: 60 руб.\n"
        "**- Прибыль: 340 руб.**\n",
        {"Полная цена": 1000.0, "Прибыль": 340.0, "Расходы": 660.0, "Город": "Бердск",
         "date:Подача до:start": "2026-12-01T10:00:00+07:00"},
    ),
}


def run(folder, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), str(folder), "--offline", *args],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise AssertionError(f"{folder}: код {r.returncode}: {r.stderr.strip()}")
    return r.stdout


def main():
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, (tj, calc, want) in CASES.items():
            d = Path(tmp) / str(tj["number"])
            d.mkdir()
            (d / "tender.json").write_text(json.dumps(tj, ensure_ascii=False), encoding="utf-8")
            (d / "tender.md").write_text(f"# Тендер {tj['number']}\n\n{calc}", encoding="utf-8")
            (d / "цены.md").write_text(PRICES, encoding="utf-8")
            try:
                props = json.loads(run(d))["properties"]
                run(d, "--card"), run(d, "--summary")
                diff = {k: (props.get(k), v) for k, v in want.items() if props.get(k) != v}
                assert not diff, diff
                print(f"ok   {name}")
            except AssertionError as e:
                bad += 1
                print(f"FAIL {name}: {e}")
    s = run(EXAMPLE / "input", "--gis-ids", str(EXAMPLE / "2gis_ids.json"), "--summary").splitlines()[0]
    want = "0151100007126000034 (Перчатки): прибыль 25 317,59 ₽ (вариант А), расходы 15 467,81 ₽, НМЦК 40 785,40 ₽"
    p = json.loads(run(EXAMPLE / "input", "--gis-ids", str(EXAMPLE / "2gis_ids.json")))["properties"]
    if p.get("Товар") != "Перчатки":
        bad += 1
        print(f"FAIL образец Товар: {p.get('Товар')!r}")
    if list(p)[:2] != ["Товар", "Номер тендера"] or p["Номер тендера"] != "0151100007126000034":
        bad += 1
        print(f"FAIL образец: заголовок «Товар» первым, «Номер тендера» текстом: {list(p)[:2]}, {p.get('Номер тендера')!r}")
    want_props = json.loads((EXAMPLE / "properties.json").read_text(encoding="utf-8"))["properties"]
    if list(want_props)[:2] != ["Товар", "Номер тендера"]:
        bad += 1
        print("FAIL examples properties.json: первыми должны быть «Товар», «Номер тендера»")
    f = json.loads(run(EXAMPLE / "input", "--gis-ids", str(EXAMPLE / "2gis_ids.json"), "--lookup"))["filters"][0]
    if (f["property"], f["propertyType"], f["value"]["value"]) != ("Номер тендера", "text", "0151100007126000034"):
        bad += 1
        print(f"FAIL --lookup: {f}")
    else:
        print("ok   --lookup ищет дубль по тексту «Номер тендера»")
    if s == want:
        print("ok   образец 0151100007126000034")
    else:
        bad += 1
        print(f"FAIL образец: {s}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
