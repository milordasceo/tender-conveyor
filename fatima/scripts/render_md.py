#!/usr/bin/env python3
"""Собрать tender.md из проверенного tender.json (один источник данных — JSON).

Запуск:
  python3 render_md.py <tender.json> [-o <tender.md>]
Без -o пишет tender.md рядом с tender.json.
Перед запуском — validate_tender.py без ошибок.
"""
import argparse
import json
import sys
from pathlib import Path


def money(v, cur="RUB"):
    if v is None:
        return "не указано"
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} ₽" if cur == "RUB" else f"{s} {cur}"


def num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (f"{v:,.3f}".rstrip("0").rstrip(".")).replace(",", " ").replace(".", ",")
    return str(v)


def render(d):
    c, s, dl, cu = d["conditions"], d["supply"], d["delivery"], d["customer"]
    cur = d["nmck"].get("currency", "RUB")
    L = [f"# Закупка № {d['number']}", "", f"**{d['subject']}**", "", "## Основное",
         f"- **Номер:** {d['number']}",
         f"- **Ссылка:** {d['url']}",
         f"- **Заказчик:** {cu['name']}" + (f" ({cu['short_name']})" if cu["short_name"] != cu["name"] else ""),
         f"- **ИНН заказчика:** {cu['inn']}",
         f"- **Закон:** {d['law']}",
         f"- **Способ закупки:** {d['method']}",
         f"- **Площадка:** {d['platform']}",
         f"- **Окончание подачи заявок:** {d['deadline']['local']} ({d['deadline']['timezone']})",
         f"- **НМЦК:** {money(d['nmck']['amount'], cur)}",
         "", "## Место поставки",
         f"- **Адрес (ТЗ, контракт):** {dl['address']}",
         f"- **Адрес (извещение):** {dl['address_notice']}",
         f"- **Город:** {dl['city']}",
         f"- **Условия:** {dl['notes']}",
         "", "## Поставка",
         f"- **Количество поставок:** {s['deliveries_count']}",
         f"- **График:** {s['schedule']}",
         f"- **Срок поставки:** {s['terms']}",
         f"- **Срок исполнения контракта:** {s['contract_period']}",
         f"- **Оплата:** {s['payment']}",
         "", "## Особые условия",
         f"- **Лицензии / разрешения:** {c['licenses_permits']}",
         f"- **Опыт:** {c['experience']}",
         f"- **Требования к участникам:** {c['participant_requirements']}",
         f"- **СМП / СОНО:** {c['smp_sono']}",
         f"- **Нацрежим:** {c['national_regime']}",
         f"- **Обеспечение заявки:** {c['application_security']}",
         f"- **Обеспечение контракта:** {c['contract_security']}",
         f"- **Обеспечение гарантийных обязательств:** {c['warranty_security']}",
         f"- **Прочее:** {c['other']}",
         "", "## Особые пометки"]
    notes = d.get("special_notes") or []
    L += [f"- {x}" for x in notes] if notes else ["нет"]
    L += ["", "## Объекты закупки"]
    for n, it in enumerate(d["items"], 1):
        L += ["", f"### {n}. {it['name']}", f"- ОКПД2: {it['okpd2']}; КТРУ: {it['ktru']}"]
        L += [f"- {x['name']}: {x['value']}" for x in it["characteristics"]]
        L += [f"- Количество: {num(it['quantity'])}",
              f"- Единица измерения: {it['unit']}",
              f"- Цена за единицу (НМЦК): {money(it['unit_price'], cur)}; стоимость позиции: {money(it['total_price'], cur)}",
              f"- **Допускается аналог:** {'да' if it['analog_allowed'] else 'нет'} — {it['analog_note']}"]
    L += ["", "## Категория", f"**{d['category']}** — {d['category_reason']}", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args()
    d = json.loads(a.file.read_text(encoding="utf-8"))
    out = a.out or a.file.with_name("tender.md")
    out.write_text(render(d), encoding="utf-8")
    print(f"записан {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
