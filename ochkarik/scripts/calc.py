#!/usr/bin/env python3
"""Расчёт рентабельности тендера по правилам Очкарика (только для проверки).

Промт бота от скрипта не зависит: бот может считать и без него.

Пример (тендер 0151100007126000034, перчатки):
  python3 calc.py --nmck 40785.40 --delivery 1500 \
      --line А=25.00x380 --line Б=32.20x380

--line ВАРИАНТ=ЦЕНАxКОЛИЧЕСТВО — одна позиция одного варианта; позиций может быть
несколько, они суммируются по варианту. Запятая в числах допускается (25,00).
Налог: УСН «доходы минус расходы», 15% от (НМЦК − закупка − доставка), не меньше 0.
Минимальный налог 1% не учитывается (как и в промте).
"""
import argparse
import sys
from decimal import Decimal, ROUND_HALF_UP

THRESHOLD = Decimal("9000")
TAX_RATE = Decimal("0.15")
CENT = Decimal("0.01")


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
    a = p.parse_args()

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
    print(f"Цена тендера (НМЦК): {rub(nmck)}; доставка: {rub(delivery)}")
    for variant, buy in purchase.items():
        buy = buy.quantize(CENT, ROUND_HALF_UP)
        base = nmck - buy - delivery
        tax = (max(base, Decimal(0)) * TAX_RATE).quantize(CENT, ROUND_HALF_UP)
        profit = base - tax
        best = profit if best is None else max(best, profit)
        print(f"Вариант {variant}: закупка {rub(buy)}, налог 15% от {rub(base)} = {rub(tax)}, "
              f"Прибыль варианта {variant} (по ценам {variant}): {rub(profit)}")
    verdict = "рентабельно" if best is not None and best >= THRESHOLD else "нерентабельно"
    print(f"Вердикт: {verdict} (порог {rub(THRESHOLD)}; лучший вариант — {rub(best)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
