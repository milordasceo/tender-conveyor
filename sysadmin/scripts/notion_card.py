#!/usr/bin/env python3
"""Сисадмин: свойства и тело карточки Notion из папки тендера.

Читает из папки tender.json, tender.md и цены.md (если есть) и печатает:
  без ключей   — JSON {"icon", "properties"} для notion-create-pages (база «Тендеры»);
  --card       — тело карточки в markdown (разделы «Главное» … «Заказчик и закупка»);
  --summary    — короткая сводка для проверки (прибыль, расходы, откуда, куда);
  --lookup     — фильтр для notion-query-data-sources (rows) — поиск дубля по тексту «Номер тендера».

Заголовок базы (title, кнопка «Открыть» в таблице) — «Товар»; «Номер тендера» — текстовое свойство
(в таблице скрыто, в карточке первое в шапке). Дубли ищутся по «Номер тендера», не по заголовку.

Формулы «Чистая прибыль» и «Дней до подачи» Notion считает сам — в JSON их нет.
«date:Подача до:start» обязателен: по нему отсортирована таблица «Тендеры» (по возрастанию,
меньше всего дней до подачи — сверху).

Правило: прибыль и расходы — из раздела «Расчёт рентабельности» в tender.md, по варианту, который выбрал
Очкарик (решение владельца от 31.10.2026: «Писать прибыль варианта, который выбрал Очкарик»): явно отмеченный
выбор → вариант, названный лучшим в вердикте → наибольшая «Прибыль варианта X»; «Расходы» = закупка + доставка +
налог того же варианта; «Откуда забирать» и «2ГИС: откуда» — поставщик того же варианта.
Всё остальное — из tender.json. Поставщики — из цены.md.
Ссылки 2ГИС («2ГИС: откуда», «2ГИС: куда», «📍 2ГИС» в теле) — карточка здания:
  https://2gis.ru/<город>/geo/<id здания в 2ГИС>
Готовые ссылки берутся как есть: у поставщика — строка «- 2ГИС: <ссылка>» варианта в цены.md
(Черри Пикер), у адреса доставки — delivery.map_url в tender.json (Фатима). Если готовая ссылка —
только поиск (/search/), скрипт пробует сам найти id здания (кроме --offline); не нашёл — оставляет её.
Своя выдача — запасной путь, только когда готовой ссылки нет:
id берётся со страницы поиска 2ГИС (https://2gis.ru/<город>/search/<адрес>, один GET на адрес,
обычный браузерный User-Agent, пауза 1 с): в HTML есть initialState с найденным зданием
(data.entity.profile → type "building", id, address_name). id принимается, только если поиск
нашёл ровно одно здание и номер дома совпал. Не нашлось или нет сети —
https://2gis.ru/<город>/search/<адрес> (и предупреждение в stderr).
В адрес для поиска идут только город, улица и дом — без компании, индекса, телефона, этажа, офиса.
  --offline        — в сеть не ходить (id только из --gis-ids, иначе ссылка-поиск);
  --gis-ids FILE   — JSON {"адрес": "id"} с уже известными id (пример — examples/…/2gis_ids.json).
«Чистая прибыль» — свойство-формула базы, скрипт её не заполняет.
«Обеспечение» (текст, в таблице скрыто) — «Заявка: …; контракт: X% ≈ N ₽ (от «Полной цены»); гарантия: …»
плюс освобождение и антидемпинг (ст. 37 44-ФЗ), если указаны; из conditions.*_security tender.json, иначе из tender.md;
процент без суммы — N = X% от «Полной цены» до рубля; данных нет — «нет данных».
«Нацрежим» (select: Соблюдается / Не соблюдается / Не подтверждено / Не установлен) и «Нацрежим: подробно» (текст) —
из строки «Нацрежим» в расчёте Очкарика (tender.md); нет строки или статуса в ней — мера из conditions.national_regime,
tender.md или «Печатная форма извещения.html», происхождение товара лучшего варианта — из цены.md («Нацрежим:», «Страна:», «Реестр:»).
«Нацрежим обязателен» (select: Да / Нет / Нет данных; решение владельца от 31.10.2026) — из conditions.national_regime.mandatory:
true → «Да», false → «Нет», null / нет поля / national_regime строкой (старый формат) → «Нет данных».
national_regime — строка (как есть) или объект {mandatory, measure, basis, confirmation, note} → читаемый текст; словарь не выводится.
«Товар» (заголовок) — предложение обобщённого названия (1–3 слова) по subject и items из tender.json; бот может уточнить.
Форматы терпимы к вариациям: строки расчёта жирные или нет («- **Прибыль варианта А:** X ₽»,
«- Прибыль варианта А (по ценам А): X ₽», «Закупка: 700 × 59 = 41 300 ₽», ₽/руб.); суммы в tender.json —
числом, строкой или объектом {"amount": …}; tender.json — вложенная схема (delivery/supply/conditions/deadline)
или плоская (delivery_address, deliveries_count, application_deadline, links.zakupki_card, …).
Только стандартная библиотека python 3.10+. Ничего не пишет; в сеть — только к 2gis.ru (кроме --offline).

Пример:
  python3 notion_card.py /tmp/t34
  python3 notion_card.py /tmp/t34 --card --drive-path "Госзакупки / CRM / 0151100007126000034"
"""
import argparse
import json
import re
import sys
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import quote

VARIANTS = {"1": "А", "2": "Б", "3": "В"}
NUM = r"([-−–]?\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)"
RUB = r"(?:₽|руб\.?|р\.)"

ICONS = [
    (r"перчат", "🧤"), (r"бумаг|канцел|ручк|тетрад", "📎"), (r"мебел|стол|стул|шкаф", "🪑"),
    (r"компьют|ноутбук|принтер|картридж|оргтехник", "💻"), (r"продукт|питани|молок|хлеб|мяс", "🥫"),
    (r"медицин|лекарств|шприц|бинт", "💊"), (r"моющ|хозяйств|уборк|мыл|чистящ", "🧽"),
    (r"одежд|спецодежд|обув|форм", "🦺"), (r"строит|краск|цемент|ремонт", "🧱"),
    (r"электр|ламп|кабел|светильник", "💡"), (r"инструмент", "🔧"), (r"книг|учебник", "📚"),
    (r"топлив|бензин|масл", "⛽"), (r"посуд", "🍽️"),
]


GIS_CITIES = {
    "новосибирск": "novosibirsk", "москва": "moscow", "санкт-петербург": "spb",
    "екатеринбург": "ekaterinburg", "казань": "kazan", "красноярск": "krasnoyarsk",
    "омск": "omsk", "томск": "tomsk", "барнаул": "barnaul", "кемерово": "kemerovo",
    "новокузнецк": "novokuznetsk", "бердск": "berdsk", "искитим": "iskitim",
    "обь": "ob", "иркутск": "irkutsk", "челябинск": "chelyabinsk", "тюмень": "tyumen",
}
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
                "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
# части адреса, которые 2ГИС не нужны: этаж, офис, кабинет, помещение, подъезд, примечания
_GIS_DROP = re.compile(r"этаж|подъ[её]м|офис|\bоф\b|кабинет|\bкаб\b|помещ|\bпом\b|подъезд|склад|"
                       r"тел\b|телефон|\+7|разгрузк|вход|ворот", re.I)


def gis_city(city: str) -> str:
    c = (city or "").strip().lower()
    return GIS_CITIES.get(c) or "".join(_TR.get(ch, ch) for ch in c).replace(" ", "-") or "novosibirsk"


def gis_address(text: str, city: str = "") -> str:
    """Только адрес: «г. Город, ул. Улица, дом» — без компании, индекса, телефона, этажа и примечаний."""
    t = (text or "").split(";")[0]
    t = re.sub(r"\([^()]*\)", " ", t)                     # (вариант А), (+7 ...), (с подъёмом)
    t = re.sub(r"«[^»]*»|\"[^\"]*\"", " ", t)               # «Компания»
    t = re.split(r"\bтел\.?|\+7|\b8 \(", t)[0]              # телефон и всё после
    keep = []
    for part in (p.strip(" .,—-") for p in t.split(",")):
        if not part or re.fullmatch(r"\d{6}", part) or _GIS_DROP.search(part):
            continue
        if re.search(r"российская федерация|^обл\.|область|^г\.о\.|городской округ|\bООО\b|\bИП\b|\bАО\b", part, re.I):
            continue
        keep.append(re.sub(r"\s+", " ", part))
    addr = ", ".join(keep)
    if city and city.lower() not in addr.lower():
        addr = f"г. {city}, {addr}" if addr else f"г. {city}"
    elif city:
        addr = re.sub(rf"(?<![\w.])(?:г\.\s*)?{re.escape(city)}", f"г. {city}", addr, count=1, flags=re.I)
    return addr


GIS = {"net": True, "ids": {}, "cache": {}, "last": 0.0}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/141.0.0.0 Safari/537.36")


def gis_parse_search(html: str, addr: str) -> str | None:
    """id здания из HTML страницы поиска 2ГИС: ровно одно здание, номер дома совпадает."""
    m = re.search(r"var initialState = JSON\.parse\('(.*?)'\);", html, re.S)
    if not m:
        return None
    raw = m.group(1)
    try:
        state = json.loads(raw.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    prof = (state.get("data", {}).get("entity", {}) or {}).get("profile", {}) or {}
    blds = [v.get("data", {}) for v in prof.values() if v.get("data", {}).get("type") == "building"]
    if len(blds) != 1:
        return None
    b = blds[0]
    house = re.findall(r"\d+", addr.split(",")[-1] if "," in addr else addr)
    name = b.get("address_name") or b.get("name") or ""
    if house and house[0] not in re.findall(r"\d+", name):
        return None
    bid = str(b.get("id", "")).split("_")[0]
    return bid if bid.isdigit() else None


def gis_lookup(addr: str, city: str) -> str | None:
    """Один GET страницы поиска 2ГИС на адрес (с кешем и паузой 1 с); None — не нашли/нет сети."""
    key = f"{gis_city(city)}|{addr}"
    if key in GIS["cache"]:
        return GIS["cache"][key]
    bid = None
    try:
        time.sleep(max(0.0, 1.0 - (time.time() - GIS["last"])))
        req = urllib.request.Request(f"https://2gis.ru/{gis_city(city)}/search/{quote(addr, safe='')}",
                                     headers={"User-Agent": _UA, "Accept": "text/html",
                                              "Accept-Language": "ru-RU,ru;q=0.9"})
        with urllib.request.urlopen(req, timeout=15) as r:
            bid = gis_parse_search(r.read().decode("utf-8", "replace"), addr)
    except urllib.error.HTTPError as e:                 # 404 — 2ГИС ничего не нашёл
        if e.code != 404:
            print(f"2ГИС: {addr}: HTTP {e.code}", file=sys.stderr)
    except OSError as e:
        print(f"2ГИС: {addr}: сеть — {e}", file=sys.stderr)
    finally:
        GIS["last"] = time.time()
    GIS["cache"][key] = bid
    return bid


def gis_url(text: str, city: str) -> str | None:
    """https://2gis.ru/<город>/geo/<id здания>; не нашли — https://2gis.ru/<город>/search/<адрес>."""
    addr = gis_address(text, city)
    if not re.search(r"\d", addr):                       # без номера дома 2ГИС адрес не найдёт
        return None
    bid = GIS["ids"].get(addr) or (gis_lookup(addr, city) if GIS["net"] else None)
    if bid:
        return f"https://2gis.ru/{gis_city(city)}/geo/{bid}"
    print(f"2ГИС: {addr}: id здания не найден — ссылка на поиск", file=sys.stderr)
    return f"https://2gis.ru/{gis_city(city)}/search/{quote(addr, safe='')}"


_GIS_READY = re.compile(r"https?://(?:www\.)?2gis\.ru/[^\s<>()\[\]]+", re.I)


def gis_ready(raw: str | None) -> str | None:
    """Готовая ссылка 2ГИС из строки цены.md / tender.json: url без ?stat= и хвостовой пунктуации; нет — None."""
    m = _GIS_READY.search(raw or "")
    return re.sub(r"[?#].*$", "", m.group(0)).rstrip(".,;") if m else None


def gis_resolve(ready: str | None, text: str | None, city: str) -> str | None:
    """Готовая geo/ — как есть; готовая /search/ — пробуем свою geo/ (кроме --offline), иначе готовая;
    готовой нет — своя выдача по адресу (gis_url)."""
    ready = gis_ready(ready)
    if ready and "/geo/" in ready:
        return ready
    if ready:
        addr = gis_address(text or "", city) if text else ""
        if addr and re.search(r"\d", addr) and (GIS["ids"].get(addr) or GIS["net"]):
            bid = GIS["ids"].get(addr) or gis_lookup(addr, city)
            if bid:
                return f"https://2gis.ru/{gis_city(city)}/geo/{bid}"
        return ready
    return gis_url(text, city) if text else None


def gis_link(url: str | None) -> str:
    return f" — [📍 2ГИС]({url})" if url else ""


_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]]+|"
                  r"\b(?:[\w-]+\.)+(?:рф|xn--[a-z0-9-]+|ru|com|net|org|su|онлайн|рус)(?:/[^\s<>()\[\]]*)?", re.I)


def norm_link(raw: str) -> tuple[str, str] | None:
    """Ссылка поставщика → (href, подпись). Понимает [текст](url), <url>, голый url, домен без https://,
    punycode (xn--…) и кириллические домены (экохим54.рф): href — в punycode, подпись — по-русски."""
    if not raw:
        return None
    m = re.search(r"\]\(([^)\s]+)\)", raw) or re.search(r"<([^>\s]+)>", raw) or _URL.search(raw)
    if not m:
        return None
    url = (m.group(1) if m.re is not _URL else m.group(0)).rstrip(".,;")
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    sm = re.match(r"(https?://)([^/?#]+)(.*)", url, re.I)
    scheme, host, rest = sm.groups()
    try:
        ascii_host = host.encode("idna").decode("ascii") if not host.isascii() else host
        nice_host = ascii_host.encode("ascii").decode("idna") if "xn--" in ascii_host.lower() else ascii_host
    except UnicodeError:
        ascii_host = nice_host = host
    nice_host = re.sub(r"^www\.", "", nice_host, flags=re.I)
    return scheme + ascii_host + rest, nice_host


def site_link(raw: str) -> str:
    n = norm_link(raw)
    return f"[{n[1]}]({n[0]})" if n else raw


def rub_to_float(s: str) -> float:
    return float(re.sub(r"[\s\u00a0\u202f]", "", s).replace(",", ".").replace("−", "-").replace("–", "-"))


def money(x):
    """Сумма из tender.json: число, строка «120 232,00 руб.» или объект {"amount"|"value"|"sum": …}; иначе None."""
    if isinstance(x, dict):
        x = next((x[k] for k in ("amount", "value", "sum", "total") if x.get(k) is not None), None)
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, str):
        m = re.search(NUM, x)
        if m:
            try:
                return rub_to_float(m.group(1).strip())
            except ValueError:
                return None
    return None


def as_dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def first(*vals):
    """Первое непустое значение (не None и не пустая строка/список)."""
    return next((v for v in vals if v not in (None, "", [], {})), None)


def fmt_rub(x) -> str:
    x = money(x)
    if x is None:
        return "—"
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} ₽"


_CALC_HEAD = re.compile(r"^(#{2,3})\s*Расч[её]т\s+рентабельности.*$", re.M | re.I)
_VAR_HEAD = re.compile(r"^(?:#{3,4}[ \t]*|(?:\*\*|__))Вариант[ \t]+([^\s*_:.,)]+)[.:)]?(.*)$", re.M)
_CALC_LINES = {
    "purchase": r"Закуп",
    "delivery": r"(?:Доставка|Логистика|Перевозка)",
    "tax": r"(?:Налог|УСН)",
    "profit": r"(?:Чистая\s+)?Прибыль",
}


def calc_grab(label: str, body: str):
    """Сумма из строки «- [**]Метка …: [**]X ₽[**] [(пояснение)]»: маркер списка и жирный — по желанию,
    перед суммой «:» или «=» (берётся последняя сумма строки, после которой ₽/руб. и конец строки)."""
    g = re.search(r"^[ \t]*(?:\*\*|__)?[ \t]*(?:[-*+][ \t]+)?(?:\*\*|__)?[ \t]*" + label + r"[^\n]*?[:=][ \t]*(?:\*\*|__)?[ \t]*"
                  + NUM + r"[ \t]*" + RUB + r"[ \t]*(?:\*\*|__)?[ \t]*(?:\([^()\n]*\))?[ \t]*\.?[ \t]*$",
                  body, re.M | re.I)
    return rub_to_float(g.group(1).strip()) if g else None


def parse_calc(md: str) -> dict:
    """Варианты из раздела «Расчёт рентабельности» tender.md."""
    m = _CALC_HEAD.search(md)
    if not m:
        raise SystemExit("в tender.md нет раздела «Расчёт рентабельности»")
    calc = md[m.start():]
    nxt = re.search(rf"^#{{1,{len(m.group(1))}}}\s", calc[m.end() - m.start():], re.M)
    if nxt:
        calc = calc[: m.end() - m.start() + nxt.start()]
    heads = list(_VAR_HEAD.finditer(calc))
    blocks = []
    for vm in heads:
        body = calc[vm.end():]
        stop = re.search(r"^(?:#{1,4}\s|#{3}|[ \t]*(?:\*\*|__)?Вердикт|(?:\*\*|__)Вариант\s)", body, re.M)
        blocks.append((vm.group(1), re.sub(r"[*_]+\s*$", "", vm.group(2)).strip(),
                       body[: stop.start()] if stop else body))
    if not heads:                                       # расчёт без вариантов — один вариант «А»
        blocks.append(("А", "", calc[m.end() - m.start():]))
    variants = {}
    for name, title, body in blocks:
        v = {k: calc_grab(lab, body) for k, lab in _CALC_LINES.items()}
        v["title"] = title
        if v["profit"] is None:
            continue
        variants.setdefault(name, v)
    if not variants:
        raise SystemExit("в разделе «Расчёт рентабельности» нет строк «Прибыль варианта X»")
    return {"text": calc.rstrip(), "variants": variants}


_LAT2CYR = {"A": "А", "B": "Б", "C": "В", "V": "В"}
_VAR_LETTER = r"([АБВABC]|[123])(?![\wА-Яа-яЁё])"


def _variant_letter(x: str) -> str:
    x = x.upper()
    return VARIANTS.get(x, _LAT2CYR.get(x, x))


def chosen_variant(calc: dict) -> tuple[str, str]:
    """Вариант для «Прибыли» и «Расходов» (решение владельца от 31.10.2026: «Писать прибыль варианта, который выбрал
    Очкарик»): 1) явно выбранный Очкариком в «Расчёте рентабельности» («выбранный вариант Б», «выбран вариант Б»,
    «берём вариант Б», «Выбор: вариант Б»), даже если он менее прибыльный (например, из-за нацрежима); 2) нет — вариант,
    названный лучшим в вердикте («лучший вариант А», «вердикт: … вариант А: …» или сумма прибыли одного из вариантов);
    3) нет и этого — наибольшая «Прибыль варианта X». Возвращает (имя варианта, почему он)."""
    text, variants = calc["text"], calc["variants"]
    for m in re.finditer(r"(?:выбранн\w*|выбран\w*|выбира\w*|берём|берем|выбор\s*[:—–-])\s*(?:\*\*|__)?\s*вариант\w*\s*(?:\*\*|__)?\s*"
                         + _VAR_LETTER, text, re.I):
        v = _variant_letter(m.group(1))
        if v in variants:
            return v, f"выбран Очкариком («{m.group(0).strip()}»)"
    for line in text.splitlines():
        if not re.search(r"вердикт", line, re.I):
            continue
        clean = line.replace("*", "").replace("_", " ")
        m = (re.search(r"лучш\w*\s+вариант\w*\s+" + _VAR_LETTER, clean, re.I)
             or re.search(r"вариант\w*\s+" + _VAR_LETTER + r"\s*[:—–-]", clean, re.I))
        if m and _variant_letter(m.group(1)) in variants:
            return _variant_letter(m.group(1)), "назван лучшим в вердикте"
        sums = [rub_to_float(x) for x in re.findall(r"(−?-?\d[\d\s\u00a0\u202f]*(?:,\d+)?)\s*(?:₽|руб)", clean)]
        hit = [n for n, v in variants.items() if v["profit"] in sums]
        if len(hit) == 1:
            return hit[0], "его прибыль названа лучшей в вердикте"
    best = max(variants.items(), key=lambda kv: kv[1]["profit"])[0]
    return best, "выбор не отмечен — наибольшая прибыль"


_PRICE_HEAD = re.compile(r"^(?:#{3,4}[ \t]*)?(?:\*\*|__)?Цена[ \t]+(\d+|[АБВ])[ \t]*(?:\*\*|__)?[ \t]*[:—–-]"
                         r"[ \t]*(?:\*\*|__)?[ \t]*(.+?)[ \t]*(?:\*\*|__)?[ \t]*$", re.M)


def parse_prices(md: str) -> list:
    """Позиции из цены.md: [{title, variants: {А: {price, supplier, phone, link, pack}}}]."""
    items = []
    for sec in re.split(r"^## ", md, flags=re.M)[1:]:
        title, _, body = sec.partition("\n")
        item = {"title": title.strip(), "variants": {}}
        for pm in _PRICE_HEAD.finditer(body):
            v = VARIANTS.get(pm.group(1), pm.group(1))
            rest = body[pm.end():]
            stop = _PRICE_HEAD.search(rest)
            rest = rest[: stop.start()] if stop else rest
            info = {"price": pm.group(2).strip()}
            for key, label in (("supplier", "Где купить"), ("phone", "Телефон"),
                               ("link", r"(?:Ссылка|Сайт|URL)"), ("pack", "Фасовка"),
                               ("gis", r"(?:2ГИС|2GIS)"), ("nr", r"Нацрежим"),
                               ("country", r"Страна(?:\s+происхождения)?"), ("registry", r"Реестр\w*(?:\s+запис\w*)?")):
                fm = re.search(rf"^\s*[-*]\s*(?:\*\*)?{label}(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+)$", rest, re.M | re.I)
                if fm:
                    info[key] = fm.group(1).strip()
            item["variants"][v] = info
        items.append(item)
    return items


def short_unit(unit: str) -> str:
    m = re.findall(r"\(([^()]+)\)", unit or "")
    return m[-1] if m else (unit or "")


def short_subject(subject: str) -> str:
    m = re.search(r"\(([^()]+)\)\s*$", subject or "")
    return m.group(1) if m else (subject or "")


# «Товар»: обобщённое название, 1–3 слова. Ищем по предмету и позициям, порядок — как в тексте предмета
PRODUCTS = [
    (r"перчат", "Перчатки"), (r"полотенц", "Полотенца"), (r"туалетн\w* бумаг", "Туалетная бумага"),
    (r"салфет", "Салфетки"), (r"мыл[оа]", "Мыло"), (r"моющ|чистящ", "Моющие средства"),
    (r"мешк\w* для мусора|мусорн\w* мешк", "Мусорные мешки"), (r"канцел|ручк|тетрад|карандаш", "Канцтовары"),
    (r"(офисн|писч)\w* бумаг|бумаг\w* для офисн|бумаг\w* а4", "Офисная бумага"), (r"картридж", "Картриджи"),
    (r"мебел|стол|стул|шкаф", "Мебель"), (r"компьют|ноутбук|оргтехник", "Оргтехника"),
    (r"спецодежд|одежд", "Спецодежда"), (r"обув", "Обувь"), (r"посуд", "Посуда"),
    (r"ламп|светильник", "Лампы"), (r"кабел", "Кабель"), (r"краск", "Краска"), (r"инструмент", "Инструменты"),
    (r"книг|учебник", "Книги"), (r"бензин|топлив", "Топливо"), (r"шприц", "Шприцы"), (r"бинт|перевяз", "Перевязка"),
    (r"продукт|питани", "Продукты"),
]


def product_name(subject: str, items: list) -> str:
    """Предложение для «Товар»: 1–3 слова по-русски («Перчатки», «Полотенца и туалетная бумага»).
    Бот может уточнить. Нет совпадения — первые слова предмета без «на 2027 год» и количеств."""
    subj = short_subject(subject or "")
    text = (subj + " " + " ".join(str(i.get("name", "")) for i in items or [])).lower()
    found = []
    for pat, name in PRODUCTS:
        m = re.search(pat, text)
        if m and name not in [n for _, n in found]:
            found.append((m.start(), name))
    names = [n for _, n in sorted(found)]
    if names:
        if len(names) == 1:
            return names[0]
        two = f"{names[0]} и {names[1][0].lower()}{names[1][1:]}"
        return two if len(names) == 2 and len(two.split()) <= 4 else names[0]
    base = re.sub(r"\s+на\s+\d{4}\s*(г\.?|год\w*)?.*$", "", subj, flags=re.I)
    base = re.sub(r"[,;—–(].*$|\d.*$", "", base).strip()
    base = re.sub(r"^(поставк\w*|приобретени\w*|закупк\w*|оказани\w*)\s+", "", base, flags=re.I)
    words = [w for w in base.split() if re.fullmatch(r"[А-Яа-яЁё-]{2,}", w)][:3]
    return " ".join(words)[:1].upper() + " ".join(words)[1:] if words else ""


def num(x) -> str:
    if isinstance(x, dict):
        x = first(x.get("value"), x.get("amount"), "")
    return f"{x:g}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


# города для часового пояса, если в tender.json нет готового ISO-срока
_TZ = {"москв": 3, "мск": 3, "санкт-петербург": 3, "казан": 3, "екатеринбург": 5, "челябинск": 5,
       "тюмен": 5, "омск": 6, "новосибирск": 7, "томск": 7, "барнаул": 7, "кемеров": 7, "новокузнецк": 7,
       "бердск": 7, "искитим": 7, "красноярск": 7, "иркутск": 8}


def parse_deadline(dl, city: str = "") -> dict:
    """Срок подачи: объект {local, timezone, iso} как есть; строка «26.11.2026 08:00 (время Новосибирска)» →
    {local, timezone, iso}; пояс — UTC±N, МСК±N или город (_TZ); не понятен — iso без смещения."""
    if isinstance(dl, dict):
        return dl
    if not isinstance(dl, str) or not dl.strip():
        return {}
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:[ \tT,]+(\d{1,2}):(\d{2}))?", dl)
    if not m:
        m2 = re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", dl.strip())
        return {"local": dl.strip(), "iso": dl.strip()} if m2 else {"local": dl.strip()}
    dd, mm, yy, hh, mi = m.groups()
    hh, mi = int(hh or 0), int(mi or 0)
    tz_text = dl[m.end():].strip(" ()")
    off = None
    u = re.search(r"(?:UTC|GMT)\s*([+\-−]\d{1,2})", tz_text, re.I)
    k = re.search(r"МСК\s*([+\-−]\s*\d{1,2})?", tz_text, re.I)
    if u:
        off = int(u.group(1).replace("−", "-"))
    elif k:
        off = 3 + (int(re.sub(r"\s", "", k.group(1)).replace("−", "-")) if k.group(1) else 0)
    else:
        low = (tz_text + " " + (city if not tz_text else "")).lower()
        off = next((v for c, v in _TZ.items() if c in low), None)
    iso = f"{yy}-{mm}-{dd}T{hh:02d}:{mi:02d}:00"
    if off is not None:
        iso += f"{'+' if off >= 0 else '-'}{abs(off):02d}:00"
    else:
        print(f"срок подачи: часовой пояс не понят ({dl}) — ISO без смещения", file=sys.stderr)
    out = {"local": dl[: m.end()].strip(), "iso": iso}
    if tz_text:
        out["timezone"] = tz_text
    return out


def city_of(*texts) -> str:
    """Город из адреса («г. Новосибирск») или из «location» («Новосибирск (в городе)»)."""
    for t in texts:
        if not isinstance(t, str) or not t:
            continue
        m = re.search(r"(?<![\w.])г\.\s*([А-ЯЁ][\w-]+(?:[ -][А-ЯЁ][\w-]+)?)", t)
        if m:
            return m.group(1)
    for t in texts:
        if isinstance(t, str) and t:
            m = re.match(r"\s*([А-ЯЁ][\w-]+)\s*(?:\(|$)", t)
            if m:
                return m.group(1)
    return ""


def normalize(tj: dict, folder: Path) -> dict:
    """tender.json любой из встречавшихся схем → вложенная схема (как в examples/0151100007126000034).
    Готовые поля не трогаются: для вложенной схемы результат совпадает с входом."""
    t = dict(tj)
    t["number"] = str(first(tj.get("number"), tj.get("reg_number"), folder.resolve().name))
    links = as_dict(tj.get("links"))
    t["url"] = first(tj.get("url"), links.get("zakupki_card"), links.get("zakupki"), links.get("eis"))
    t["method"] = first(tj.get("method"), tj.get("procedure"))
    t["nmck"] = {"amount": money(tj.get("nmck"))}

    d = dict(as_dict(tj.get("delivery")))
    if isinstance(tj.get("delivery"), str):
        d.setdefault("address", tj["delivery"])
    if not d.get("address") and tj.get("delivery_address"):
        d["address"] = tj["delivery_address"]
    if not d.get("address_notice") and tj.get("delivery_address_notice"):
        d["address_notice"] = tj["delivery_address_notice"]
    if not d.get("city"):
        c = first(tj.get("city"), city_of(d.get("address"), d.get("address_notice"), tj.get("location")))
        if c:
            d["city"] = c
    if not d.get("map_url") and tj.get("map_url"):
        d["map_url"] = tj["map_url"]
    t["delivery"] = d

    sp = dict(as_dict(tj.get("supply")))
    for key, alts in (("deliveries_count", ("deliveries_count",)), ("schedule", ("deliveries_note", "schedule")),
                      ("terms", ("delivery_terms", "terms")), ("contract_period", ("contract_term", "contract_period")),
                      ("payment", ("payment", "payment_terms"))):
        if sp.get(key) in (None, ""):
            v = first(*(tj.get(a) for a in alts))
            if v is not None:
                sp[key] = v
    t["supply"] = sp

    c = dict(as_dict(tj.get("conditions")))
    for key, alts in (("application_security", ("application_security", "bid_security")),
                      ("contract_security", ("contract_security",)),
                      ("warranty_security", ("warranty_security",)),
                      ("national_regime", ("national_regime",)), ("smp_sono", ("smp_sono",)),
                      ("licenses_permits", ("licenses_permits",)), ("experience", ("experience",))):
        if c.get(key) in (None, ""):
            v = first(*(tj.get(a) for a in alts))
            if v is not None:
                c[key] = v
    if c.get("participant_requirements") in (None, "") and tj.get("special_conditions"):
        sc = tj["special_conditions"]
        c["participant_requirements"] = "; ".join(map(str, sc)) if isinstance(sc, list) else str(sc)
    t["conditions"] = c

    t["deadline"] = parse_deadline(first(tj.get("deadline"), tj.get("application_deadline")), d.get("city", ""))
    t["customer"] = as_dict(tj.get("customer")) or ({"name": tj["customer"]} if isinstance(tj.get("customer"), str) else {})
    sn = tj.get("special_notes")
    t["special_notes"] = sn if isinstance(sn, list) else ([sn] if sn else [])

    items = []
    for it in tj.get("items") or []:
        it = dict(it)
        if it.get("total_price") is None and it.get("total") is not None:
            it["total_price"] = it["total"]
        code = it.get("code")
        if code and not it.get("ktru") and not it.get("okpd2"):
            it["ktru" if "-" in str(code) else "okpd2"] = code
        if "analog_allowed" not in it and it.get("analog") is not None:
            a = it["analog"]
            if isinstance(a, bool):
                it["analog_allowed"] = a
            else:
                it["analog_allowed"] = not re.match(r"\s*(?:нет|не\b|не\s|запрещ)", str(a), re.I)
                it.setdefault("analog_note", str(a))
        items.append(it)
    t["items"] = items
    return t


SECURITY_PROPERTY = "Обеспечение"  # rich_text; в таблице скрыто, в карточке — обычное свойство (решение владельца от 31.10.2026)
_MD_SECURITY = {
    "application_security": r"Обеспечение\s+заявк\w*",
    "contract_security": r"Обеспечение\s+(?:исполнени\w*(?:\s+контракт\w*)?|контракт\w*)",
    "warranty_security": r"Обеспечение\s+гарант\w*(?:\s+обязательств)?",
}
_NO_SECURITY = re.compile(r"^\s*(?:не\s+требуется|не\s+установлен\w*|не\s+предусмотрен\w*|нет)\b", re.I)


def md_security(md: str) -> dict:
    """Обеспечение из tender.md: строки «- [**]Обеспечение заявки/контракта/исполнения/гарантийных обязательств:[**] …»."""
    out = {}
    for key, label in _MD_SECURITY.items():
        m = re.search(r"^[ \t]*[-*][ \t]*(?:\*\*)?" + label + r"[ \t]*:?[ \t]*(?:\*\*)?[ \t]*:?[ \t]*(.+)$", md, re.M | re.I)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()
    return out


def rub_int(x: float) -> str:
    return f"{round(x):,}".replace(",", " ") + " ₽"


def security_part(raw, full_price) -> tuple[str, list]:
    """Одна часть обеспечения → (текст, примечания: освобождение, антидемпинг по ст. 37).
    Процент есть, суммы нет — N = X% от «Полной цены», до рубля. Сумма есть, процента нет — процент считается по ней."""
    if raw in (None, "", [], {}):
        return "нет данных", []
    text = "; ".join(map(str, raw)) if isinstance(raw, list) else str(raw)
    notes = []
    for clause in re.split(r"[;()]", text):
        c = clause.strip(" .,—–-")
        if re.search(r"освобожд", c, re.I) and c not in notes:
            notes.append(c)
        elif re.search(r"демпинг|ст\.\s*37\b", c, re.I) and "антидемпинг по ст. 37" not in notes:
            notes.append("антидемпинг по ст. 37")
    if _NO_SECURITY.match(text):
        return "не требуется", notes
    pm = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    sm = re.search(NUM + r"\s*" + RUB, text)
    pct = float(pm.group(1).replace(",", ".")) if pm else None
    amount = rub_to_float(sm.group(1).strip()) if sm else None
    if pct is not None:
        if amount is None and full_price is not None:
            amount = full_price * pct / 100
        pct_s = f"{pct:g}".replace(".", ",")
        return (f"{pct_s}% ≈ {rub_int(amount)} (от «Полной цены»)" if amount is not None else f"{pct_s}%"), notes
    if amount is not None:
        if full_price:
            pct_s = f"{round(amount / full_price * 100, 2):g}".replace(".", ",")
            return f"{rub_int(amount)} (≈ {pct_s}% от «Полной цены»; процента в tender.json и tender.md нет)", notes
        return rub_int(amount), notes
    return text, notes


def security_text(conditions: dict, md: str, full_price) -> str:
    """Свойство «Обеспечение»: «Заявка: …; контракт: X% ≈ N ₽ (от «Полной цены»); гарантия: …[; освобождение …][; антидемпинг по ст. 37]».
    Источник — tender.json conditions.*_security (или плоские bid_security/contract_security/warranty_security),
    нет поля — строка из tender.md; нет и там — «нет данных». Ничего не додумывается."""
    from_md = md_security(md or "")
    parts, notes = [], []
    for key, label in (("application_security", "Заявка"), ("contract_security", "контракт"),
                       ("warranty_security", "гарантия")):
        text, n = security_part(first(conditions.get(key), from_md.get(key)), full_price)
        parts.append(f"{label}: {text}")
        notes += [x for x in n if x not in notes]
    return "; ".join(parts + notes)


NR_STATUS_PROPERTY = "Нацрежим"            # select; решение владельца от 31.10.2026: «Типа соблюдается или нет»
NR_DETAIL_PROPERTY = "Нацрежим: подробно"  # text: мера, ПП, реестр / страна товара
NR_MANDATORY_PROPERTY = "Нацрежим обязателен"  # select; решение владельца от 31.10.2026
NR_MANDATORY_OPTIONS = ("Да", "Нет", "Нет данных")
NR_OPTIONS = ("Соблюдается", "Не соблюдается", "Не подтверждено", "Не установлен")
_NR_MEASURE = re.compile(r"запрет|ограничен|преимуществ", re.I)
_NR_NONE = re.compile(r"^\s*(?:национальный\s+режим\s*)?(?:не\s+установлен|не\s+применя\w*|нет)\b", re.I)
_NR_EAEU = re.compile(r"росси|\bрф\b|беларус|белорус|казахстан|армени|киргиз|кыргыз|еаэс|евразийск", re.I)
_NR_NO_DATA = re.compile(r"не\s+подтвержд|нет\s+данных|не\s+указан|неизвестн|^\s*[—–-]?\s*$", re.I)


def nr_mandatory(nr) -> str:
    """«Нацрежим обязателен» (решение владельца от 31.10.2026) из conditions.national_regime.mandatory:
    true → «Да», false → «Нет»; null, нет поля, старый строковый формат или что-то иное → «Нет данных»."""
    if not isinstance(nr, dict):
        return "Нет данных"
    m = nr.get("mandatory")
    if isinstance(m, str):  # на случай «true»/«false» строкой
        m = {"true": True, "да": True, "false": False, "нет": False}.get(m.strip().lower())
    return {True: "Да", False: "Нет"}[m] if isinstance(m, bool) else "Нет данных"


def nr_text(nr) -> str | None:
    """conditions.national_regime: старый формат — строка (как есть); новый — объект Фатимы
    {mandatory, measure, basis, confirmation, note} → читаемый русский текст
    «Обязателен: да/нет/нет данных — мера: …; основание: …; чем подтверждать: …; примечание: …».
    Сырой словарь никуда не выводится."""
    if nr is None or isinstance(nr, str):
        return nr.strip() if isinstance(nr, str) and nr.strip() else None
    if isinstance(nr, list):
        return "; ".join(t for t in (nr_text(x) for x in nr) if t) or None
    if not isinstance(nr, dict):
        return str(nr)
    mand = nr_mandatory(nr).lower()
    out = f"Обязателен: {mand} — мера: {str(nr.get('measure') or '').strip() or 'нет данных'}"
    for key, label in (("basis", "основание"), ("confirmation", "чем подтверждать"), ("note", "примечание")):
        v = nr.get(key)
        v = "; ".join(map(str, v)) if isinstance(v, list) else str(v or "").strip()
        if v and v.lower() not in ("нет", "-", "—"):
            out += f"; {label}: {v}"
    return out


def _nr_status_word(text: str) -> str | None:
    """Статус в строке Очкарика «Нацрежим: <что установлено>; выбранный вариант <А/Б> — <статус>»:
    берётся из части после «выбранный вариант … —», без неё — из всей строки."""
    m = re.search(r"выбранн\w*\s+вариант\w*\s*\S*\s*[—–-]+\s*(.+)$", text, re.I)
    low = (m.group(1) if m else text).lower()
    for pat, st in ((r"не\s+соблюда", "Не соблюдается"), (r"не\s+подтвержд", "Не подтверждено"),
                    (r"не\s+установлен", "Не установлен"), (r"(?<!не )соблюда", "Соблюдается")):
        if re.search(pat, low):
            return st
    return None


def _calc_span(md: str) -> tuple[int, int] | None:
    """Границы раздела «Расчёт рентабельности» в tender.md."""
    m = _CALC_HEAD.search(md or "")
    if not m:
        return None
    nxt = re.search(rf"^#{{1,{len(m.group(1))}}}\s", md[m.end():], re.M)
    return m.start(), (m.end() + nxt.start()) if nxt else len(md)


def calc_nr_line(md: str) -> str | None:
    """Строка Очкарика «- Нацрежим: …» (без жирного) в разделе «Расчёт рентабельности» tender.md."""
    span = _calc_span(md)
    if not span:
        return None
    body = md[span[0]:span[1]]
    g = re.search(r"^[ \t]*[-*]?[ \t]*(?:\*\*|__)?Нацрежим(?:\*\*|__)?[ \t]*:[ \t]*(?:\*\*|__)?[ \t]*(.+?)[ \t]*$", body, re.M | re.I)
    return g.group(1).strip() if g else None


def md_nr_line(md: str) -> str | None:
    """Строка Фатимы «- **Нацрежим:** …» (или «- Национальный режим (…): …») — что сказано в извещении; ищется вне расчёта."""
    span = _calc_span(md or "")
    md = (md[:span[0]] + md[span[1]:]) if span else (md or "")
    g = re.search(r"^[ \t]*[-*][ \t]*(?:\*\*)?(Нацрежим|Национальный\s+режим)([^:\n]*):[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$",
                  md or "", re.M | re.I)
    if not g:
        return None
    extra = g.group(2).replace("*", "").strip()
    return f"{g.group(3).strip()} {extra}".strip() if extra else g.group(3).strip()


def notice_nr(html_text: str) -> str | None:
    """Мера нацрежима из «Печатная форма извещения.html»: таблица после «о мерах по предоставлению национального режима»:
    позиция — вид требования. Нет таблицы — None; таблица без запретов/ограничений/преимуществ — «не установлен»."""
    import html as _html
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html_text or "", flags=re.S | re.I)
    lines = [x.strip() for x in _html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if x.strip()]
    start = next((i for i, x in enumerate(lines) if "о мерах по предоставлению национального режима" in x), None)
    if start is None:
        return None
    end = next((k for k in range(start, len(lines)) if re.search(r"Обеспечение заявки|Перечень прикрепл", lines[k])), len(lines))
    rows, item = [], None
    for x in lines[start + 1:end]:
        if re.match(r"^(Объект закупки|Вид требования|Обоснование невозможности)", x) or re.fullmatch(r"[\d.\-]+", x):
            continue
        mm = re.match(r"^(Запрет|Ограничение|Преимущество)\b", x)
        if mm and item:
            rows.append(f"{item} — {mm.group(1).lower()}")
            item = None
        elif not mm and not re.match(r"^(оказываемых|услуг|Запрет, не применяется|Правительства|при осуществлении|муниципальных)", x):
            item = x
    if not rows:
        return "не установлен"
    return "по извещению (ст. 14 44-ФЗ, ПП РФ № 1875): " + "; ".join(rows)


def national_regime(conditions: dict, md: str, prices: list, best_name: str, notice_html: str | None = None) -> tuple[str, str]:
    """(«Нацрежим», «Нацрежим: подробно»).
    В tender.md две строки о нацрежиме: «- **Нацрежим:** …» от Фатимы (что в извещении) и «- Нацрежим: …» без жирного
    от Очкарика в «Расчёте рентабельности». Статус — из строки Очкарика, «подробно» — строка Фатимы (+ текст Очкарика).
    Строки Очкарика нет или статус в ней не назван — запасной путь: мера из строки Фатимы / conditions.national_regime /
    извещения, происхождение товара лучшего варианта — из цены.md («Нацрежим:», «Страна:», «Реестр:»).
    Статус запасного пути: не установлен → «Не установлен»; у всех позиций РФ/ЕАЭС или номер реестровой записи →
    «Соблюдается»; хоть одна позиция явно иностранная → «Не соблюдается»; иначе → «Не подтверждено». Ничего не додумывается."""
    och = calc_nr_line(md)
    measure = first(md_nr_line(md), nr_text(conditions.get("national_regime")), notice_nr(notice_html) if notice_html else None)
    measure = "; ".join(map(str, measure)) if isinstance(measure, list) else (str(measure).strip() if measure else None)
    if och and _nr_status_word(och):
        return _nr_status_word(och), f"{measure or 'мера: нет данных'}; Очкарик: {och}"
    if not measure or re.fullmatch(r"(?i)нет\s+данных\.?", measure):
        return "Не подтверждено", "мера: нет данных (нет в tender.md, tender.json и извещении); товар: нет данных"
    nr_obj = conditions.get("national_regime")
    if (isinstance(nr_obj, dict) and str(nr_obj.get("measure", "")).strip().lower() == "не установлен") or \
            ((_NR_NONE.match(measure) or re.search(r"не\s+установлен", measure, re.I)) and not _NR_MEASURE.search(measure)):
        return "Не установлен", f"в извещении не установлен ({measure})"
    goods, verdicts = [], []
    for it in prices:
        info = it["variants"].get(best_name) or {}
        nr = info.get("nr") or ""
        country = info.get("country") or (re.search(r"страна\s*[:—–-]?\s*([^,;]+)", nr, re.I) or [None, None])[1]
        reg = info.get("registry") or (re.search(r"реестр\w*\s*[:—–-]?\s*([^,;]+)", nr, re.I) or [None, None])[1]
        country, reg = (country or "").strip(), (reg or "").strip()
        reg_ok = bool(reg) and not _NR_NO_DATA.search(reg) and bool(re.search(r"\d", reg))
        if reg_ok or (country and _NR_EAEU.search(country)):
            verdicts.append("ok")
        elif country and not _NR_NO_DATA.search(country):
            verdicts.append("foreign")
        else:
            verdicts.append("unknown")
        goods.append(f"{it['title']}: страна — {country or 'нет данных'}, реестровая запись — {reg if reg_ok else 'нет данных'}")
    if verdicts and all(v == "ok" for v in verdicts):
        status = "Соблюдается"
    elif "foreign" in verdicts:
        status = "Не соблюдается"
    else:
        status = "Не подтверждено"
    src = f"товар варианта {best_name} (цены.md): " + "; ".join(goods) if goods else "товар: нет данных (цены.md)"
    if status == "Не подтверждено" and goods and all("нет данных" in g for g in goods):
        src = f"товар варианта {best_name}: страна происхождения и реестровая запись — нет данных (в цены.md не указаны)"
    return status, f"{measure}; {src}"


def build(folder: Path, drive_path: str | None):
    tj = normalize(json.loads((folder / "tender.json").read_text(encoding="utf-8")), folder)
    md = (folder / "tender.md").read_text(encoding="utf-8")
    calc = parse_calc(md)
    prices_file = folder / "цены.md"
    prices = parse_prices(prices_file.read_text(encoding="utf-8")) if prices_file.exists() else []

    best_name, best_why = chosen_variant(calc)  # вариант, выбранный Очкариком (см. chosen_variant)
    best = calc["variants"][best_name]
    parts = [best[k] for k in ("purchase", "delivery", "tax")]
    expenses = round(sum(p for p in parts if p is not None), 2) if all(p is not None for p in parts) else None
    notice = folder / "Печатная форма извещения.html"
    nr_status, nr_detail = national_regime(tj.get("conditions", {}), md, prices, best_name,
                                           notice.read_text(encoding="utf-8", errors="replace") if notice.exists() else None)
    nmck = money(tj.get("nmck"))
    if expenses is None and nmck is not None:            # строк закупки/доставки/налога нет — НМЦК − прибыль
        expenses = round(nmck - best["profit"], 2)

    sources, first_supplier, first_gis = [], None, None
    for it in prices:
        info = it["variants"].get(best_name)
        if info and info.get("supplier"):
            if not first_supplier:
                first_supplier, first_gis = info["supplier"], info.get("gis")
            s = info["supplier"] + (f", тел. {info['phone']}" if info.get("phone") else "")
            if s not in sources:
                sources.append(s)
    pickup = "; ".join(sources) if sources else "нет в цены.md"

    d = tj.get("delivery", {})
    city = d.get("city") or ""
    dest = d.get("address") or d.get("address_notice") or ""
    gis_to = gis_resolve(d.get("map_url"), dest, city)
    gis_from = gis_resolve(first_gis, first_supplier, city) if first_supplier else None
    if d.get("notes"):
        dest += f"; {d['notes']}"

    items = tj.get("items", [])
    if len(items) == 1:
        subj = f"{short_subject(tj.get('subject', ''))} — {num(items[0].get('quantity'))} {short_unit(items[0].get('unit'))}".strip()
    else:
        subj = f"{short_subject(tj.get('subject', ''))} — {len(items)} позиций"

    text = (tj.get("subject", "") + " " + " ".join(i.get("name", "") for i in items)).lower()
    icon = next((e for pat, e in ICONS if re.search(pat, text)), "📦")

    props = {
        "Товар": product_name(tj.get("subject", ""), items),  # title: кнопка «Открыть» в таблице
        "Номер тендера": str(tj["number"]),  # text: ключ дублей, в таблице скрыт
        "Полная цена": nmck,
        "Прибыль": best["profit"],
        "Расходы": expenses,
        "Город": d.get("city"),
        "Категория": tj.get("category"),
        "Количество поставок": tj.get("supply", {}).get("deliveries_count"),
        "Откуда забирать": pickup,
        "Куда везти": dest,
        "2ГИС: откуда": gis_from,
        "2ГИС: куда": gis_to,
        "date:Подача до:start": tj.get("deadline", {}).get("iso"),
        "date:Подача до:is_datetime": 1,
        "Предмет": subj,
        "Ссылка": tj.get("url"),  # обычное имя: префикс userDefined: только для свойств id/url
        SECURITY_PROPERTY: security_text(tj.get("conditions", {}), md, nmck),  # text: в таблице скрыто
        NR_STATUS_PROPERTY: nr_status,  # select: Соблюдается / Не соблюдается / Не подтверждено / Не установлен
        NR_DETAIL_PROPERTY: nr_detail,  # text: мера, ПП, реестр / страна товара
        NR_MANDATORY_PROPERTY: nr_mandatory(tj.get("conditions", {}).get("national_regime")),  # select: Да / Нет / Нет данных
    }
    ctx = dict(tj=tj, calc=calc, prices=prices, best_name=best_name, best=best, best_why=best_why,
               expenses=expenses, pickup=pickup, dest=dest, drive_path=drive_path,
               gis_from=gis_from, gis_to=gis_to, city=city)
    return {"icon": icon, "properties": props}, ctx


DEDUP_PROPERTY = "Номер тендера"  # текстовое свойство; заголовок базы — «Товар»


def lookup_filter(number: str) -> dict:
    """Фильтр notion-query-data-sources (mode rows) для поиска строки по номеру тендера."""
    return {"type": "group", "operator": "and", "filters": [
        {"type": "property", "property": DEDUP_PROPERTY, "propertyType": "text",
         "operator": "string_is", "value": {"type": "exact", "value": str(number)}}]}


def card(ctx) -> str:
    tj, best, bn = ctx["tj"], ctx["best"], ctx["best_name"]
    c, s, d, cust = tj.get("conditions", {}), tj.get("supply", {}), tj.get("delivery", {}), tj.get("customer", {})
    nm = money(tj.get("nmck"))
    L = []
    L += ["## Главное",
          '<callout icon="💰" color="green_bg">',
          f"**Чистая прибыль: {fmt_rub(best['profit'])}**",
          "</callout>", "",
          f"- **Номер:** {tj['number']}",
          f"- **НМЦК:** {fmt_rub(nm)}",
          f"- **Прибыль:** <span color=\"green_bg\">**{fmt_rub(best['profit'])}**</span> (вариант {bn})"]
    for other, v in ctx["calc"]["variants"].items():
        if other != bn:
            L.append(f"  - вариант {other}: {fmt_rub(v['profit'])}")
    if ctx["expenses"] is not None and None in (best["purchase"], best["delivery"], best["tax"]):
        L.append(f"- **Расходы:** {fmt_rub(ctx['expenses'])} = НМЦК − прибыль")
    elif ctx["expenses"] is not None:
        L.append(f"- **Расходы:** {fmt_rub(ctx['expenses'])} = закупка {fmt_rub(best['purchase'])} + доставка {fmt_rub(best['delivery'])} + налог {fmt_rub(best['tax'])}")
    L += [f"- **Количество поставок:** {s.get('deliveries_count', '—')}",
          f"- **Откуда забирать:** {ctx['pickup']}{gis_link(ctx['gis_from'])}",
          f"- **Куда везти:** {ctx['dest']}{gis_link(ctx['gis_to'])}",
          f"- **Город и категория:** {d.get('city', '—')}, {tj.get('category', '—')}", ""]
    L += ["## Особые условия",
          f"- **Лицензии / разрешения:** {c.get('licenses_permits', '—')}",
          f"- **Опыт:** {c.get('experience', '—')}",
          f"- **СМП / СОНО:** {c.get('smp_sono', '—')}",
          f"- **Нацрежим:** {nr_text(c.get('national_regime')) or '—'}"]
    for i, it in enumerate(tj.get("items", []), 1):
        a = "да" if it.get("analog_allowed") else "нет"
        note = f" — {it['analog_note']}" if it.get("analog_note") else ""
        L.append(f"- **Аналог допускается{'' if len(tj.get('items', [])) == 1 else f' (позиция {i})'}:** {a}{note}")
    L += [f"- **Обеспечение заявки:** {c.get('application_security', '—')}",
          f"- **Обеспечение контракта:** {c.get('contract_security', '—')}",
          f"- **Обеспечение гарантии:** {c.get('warranty_security', '—')}",
          f"- **Требования к участникам:** {c.get('participant_requirements', '—')}",
          f"- **Прочее:** {c.get('other', '—')}", "",
          "### Особые пометки"]
    L += [f"- {n}" for n in tj.get("special_notes", [])] or ["- нет"]
    dl = tj.get("deadline", {})
    L += ["", "## Сроки",
          f"- **Подача до:** {dl.get('local', '—')} ({dl.get('timezone', '—')})",
          f"- **Срок поставки:** {s.get('terms', '—')}",
          f"- **График:** {s.get('schedule', '—')}",
          f"- **Срок исполнения контракта:** {s.get('contract_period', '—')}",
          f"- **Оплата:** {s.get('payment', '—')}", "",
          "## Что поставляем"]
    for i, it in enumerate(tj.get("items", []), 1):
        L.append(f"### {i}. {it.get('name', '')}")
        L.append(f"- {num(it.get('quantity'))} {short_unit(it.get('unit'))} × {fmt_rub(it.get('unit_price', 0))} = {fmt_rub(it.get('total_price', 0))}")
        for ch in it.get("characteristics", []):
            unit = f" {ch['unit']}" if ch.get("unit") else ""
            L.append(f"- {ch.get('name')}: {ch.get('value')}{unit}")
        L.append(f"- ОКПД2: {it.get('okpd2', '—')}; КТРУ: {it.get('ktru', '—')}")
    L += ["", "## Где купить"]
    if not ctx["prices"]:
        L.append("- цены.md нет")
    for it in ctx["prices"]:
        L.append(f"### {it['title']}")
        for v, info in it["variants"].items():
            mark = " — лучший" if v == bn else ""
            L.append(f"- **Вариант {v}{mark}:** {info['price']}")
            for key, label in (("supplier", "где"), ("phone", "телефон"), ("link", "сайт"), ("pack", "фасовка")):
                if info.get(key):
                    val = site_link(info[key]) if key == "link" else info[key]
                    extra = gis_link(gis_resolve(info.get("gis"), info[key], ctx["city"])) if key == "supplier" else ""
                    L.append(f"  - {label}: {val}{extra}")
            if not info.get("link"):
                L.append("  - сайт: нет в цены.md")
    calc_text = ctx["calc"]["text"]
    calc_text = _CALC_HEAD.sub("## Расчёт рентабельности", calc_text, count=1)
    L += ["", calc_text, "",
          "## Заказчик и закупка",
          f"- **Заказчик:** {cust.get('name', '—')}" + (f" ({cust['short_name']})" if cust.get("short_name") else ""),
          f"- **ИНН:** {cust.get('inn', '—')}",
          f"- **Адрес поставки (извещение):** {d.get('address_notice') or d.get('address') or '—'}",
          f"- **Закон / способ:** {tj.get('law', '—')}, {tj.get('method', '—')}",
          f"- **Площадка:** {tj.get('platform', '—')}",
          f"- **Ссылка:** {tj.get('url', '—')}",
          f"- **Папка на Диске:** {ctx['drive_path'] or 'Госзакупки / CRM / ' + tj['number']}"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", type=Path, help="папка с tender.json, tender.md, цены.md")
    ap.add_argument("--card", action="store_true", help="печатать тело карточки (markdown)")
    ap.add_argument("--summary", action="store_true", help="печатать короткую сводку")
    ap.add_argument("--lookup", action="store_true", help="печатать фильтр поиска дубля по «Номер тендера»")
    ap.add_argument("--drive-path", help="путь папки тендера на Диске для раздела «Заказчик и закупка»")
    ap.add_argument("--offline", action="store_true", help="не ходить в 2ГИС за id зданий (ссылки-поиск или --gis-ids)")
    ap.add_argument("--gis-ids", type=Path, help='JSON {"адрес": "id здания 2ГИС"} с уже известными id')
    a = ap.parse_args()
    GIS["net"] = not a.offline
    if a.gis_ids:
        GIS["ids"] = json.loads(a.gis_ids.read_text(encoding="utf-8"))
    for f in ("tender.json", "tender.md"):
        if not (a.folder / f).exists():
            sys.exit(f"нет {a.folder / f}")
    out, ctx = build(a.folder, a.drive_path)
    if a.lookup:
        print(json.dumps(lookup_filter(out["properties"]["Номер тендера"]), ensure_ascii=False, indent=2))
    elif a.card:
        print(card(ctx), end="")
    elif a.summary:
        p = out["properties"]
        print(f"{p['Номер тендера']} ({p['Товар']}): прибыль {fmt_rub(p['Прибыль'])} (вариант {ctx['best_name']}: {ctx['best_why']}), "
              f"расходы {fmt_rub(p['Расходы'])}, НМЦК {fmt_rub(p['Полная цена'])}")
        print(f"откуда: {p['Откуда забирать']}")
        print(f"куда: {p['Куда везти']}")
        print(f"2ГИС откуда: {p['2ГИС: откуда'] or '—'}")
        print(f"2ГИС куда: {p['2ГИС: куда'] or '—'}")
        print(f"обеспечение: {p[SECURITY_PROPERTY]}")
        print(f"нацрежим: {p[NR_STATUS_PROPERTY]} (обязателен: {p[NR_MANDATORY_PROPERTY]}) — {p[NR_DETAIL_PROPERTY]}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
