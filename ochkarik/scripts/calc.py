#!/usr/bin/env python3
"""Расчёт рентабельности тендера по правилам Очкарика (только для проверки).

Промт бота от скрипта не зависит: бот может считать и без него.

Пример (тендер 0151100007126000034, перчатки):
  python3 calc.py --nmck 40785.40 --delivery 1500 \
      --line А=25.00x380 --line Б=32.20x380
  python3 calc.py ... --date 2027-01-01   # тот же расчёт по режиму с 01.01.2027

--line ВАРИАНТ=ЦЕНАxКОЛИЧЕСТВО — одна позиция одного варианта; позиций может быть
несколько, они суммируются по варианту. Запятая в числах допускается (25,00).
--nmck — выручка: НМЦК, а для тендера по цене единицы без определённого объёма —
вся максимальная сумма контракта.

Налог зависит от даты расчёта (--date, по умолчанию сегодня; --regime переопределяет):
  до 31.12.2026 включительно — УСН «Доходы»: 6% от выручки, независимо от расходов;
  с 01.01.2027 — УСН «доходы минус расходы»: 15% от (выручка − закупка − доставка), не меньше 0.
Минимальный налог 1% при «доходы минус расходы» не учитывается (как и в промте).
Порог: рентабельно, если хотя бы один вариант даёт прибыль от 15 000 ₽.
"""
import argparse
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

THRESHOLD = Decimal("15000")
CENT = Decimal("0.01")
USN6_LAST_DAY = date(2026, 12, 31)  # последний день режима УСН «Доходы» 6%
REGIMES = {
    "usn6": ("УСН «Доходы» 6% от выручки", Decimal("0.06")),
    "usn15": ("УСН «доходы минус расходы» 15% от (выручка − закупка − доставка)", Decimal("0.15")),
}


def regime_for(day: date) -> str:
    return "usn6" if day <= USN6_LAST_DAY else "usn15"


def parse_date(s: str) -> date:
    s = s.strip()
    if "." in s:
        d, m, y = s.split(".")
        return date(int(y), int(m), int(d))
    return date.fromisoformat(s)


def tax_for(regime: str, revenue: Decimal, buy: Decimal, delivery: Decimal) -> Decimal:
    rate = REGIMES[regime][1]
    base = revenue if regime == "usn6" else max(revenue - buy - delivery, Decimal(0))
    return (base * rate).quantize(CENT, ROUND_HALF_UP)


def num(s: str) -> Decimal:
    return Decimal(s.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def rub(d: Decimal) -> str:
    d = d.quantize(CENT, ROUND_HALF_UP)
    sign = "−" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{' '.join(groups)},{frac} ₽"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nmck", required=True, help="НМЦК, ₽")
    p.add_argument("--delivery", required=True, choices=["1500", "3000"], help="доставка, ₽")
    p.add_argument("--line", action="append", required=True, help="ВАРИАНТ=ЦЕНАxКОЛИЧЕСТВО")
    p.add_argument("--date", help="дата расчёта ГГГГ-ММ-ДД или ДД.ММ.ГГГГ; по умолчанию сегодня")
    p.add_argument("--regime", choices=["auto", *REGIMES], default="auto",
                   help="режим налога: auto — по дате (по умолчанию), usn6 или usn15 — принудительно")
    a = p.parse_args()

    try:
        day = parse_date(a.date) if a.date else date.today()
    except ValueError:
        print(f"не разобрал --date {a.date!r}", file=sys.stderr)
        return 2
    regime = regime_for(day) if a.regime == "auto" else a.regime

    nmck = num(a.nmck)
    delivery = Decimal(a.delivery)
    purchase: dict[str, Decimal] = {}
    for line in a.line:
        try:
            variant, rest = line.split("=", 1)
            price, qty = rest.lower().replace("×", "x").split("x", 1)
            purchase[variant.strip()] = purchase.get(variant.strip(), Decimal(0)) + num(price) * num(qty)
        except Exception:
            print(f"не разобрал --line {line!r}", file=sys.stderr)
            return 2

    best = None
    how = "по дате" if a.regime == "auto" else "задан вручную"
    print(f"Режим налога: {REGIMES[regime][0]} (дата расчёта {day:%d.%m.%Y}, {how})")
    print(f"Цена тендера (выручка): {rub(nmck)}; доставка: {rub(delivery)}")
    for variant, buy in purchase.items():
        buy = buy.quantize(CENT, ROUND_HALF_UP)
        tax = tax_for(regime, nmck, buy, delivery)
        profit = nmck - buy - delivery - tax
        best = profit if best is None else max(best, profit)
        print(f"Вариант {variant}: закупка {rub(buy)}, налог {rub(tax)}, "
              f"Прибыль варианта {variant} (по ценам {variant}): {rub(profit)}")
    verdict = "рентабельно" if best is not None and best >= THRESHOLD else "нерентабельно"
    print(f"Вердикт: {verdict} (порог {rub(THRESHOLD)}; лучший вариант — {rub(best)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
