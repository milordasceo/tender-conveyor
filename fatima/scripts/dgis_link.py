#!/usr/bin/env python3
"""Фатима: ссылка 2ГИС на адрес доставки («куда привезти»).

Ссылка — карточка здания: https://2gis.ru/<город латиницей>/geo/<id здания>, без ?stat=.
Правило — как у Сисадмина (sysadmin/scripts/notion_card.py):
  1. адрес сокращается до города, улицы и дома — без названия, индекса, телефона, офиса, этажа;
  2. один GET на https://2gis.ru/<город>/search/<адрес в URL-кодировке> с браузерным User-Agent
     (без него 2ГИС уводит на /museum), пауза ~1 с между адресами;
  3. из HTML берётся JSON initialState → data.entity.profile; id — только если найдено ровно
     одно здание (type "building") и номер дома совпал;
  4. иначе (не совпало, 404, нет сети) — запасная ссылка https://2gis.ru/<город>/search/<адрес>
     и предупреждение в stderr.
Ссылки «откуда забрать» делает Черри Пикер, не Фатима.

Запуск:
  dgis_link.py --address '<адрес>' --city '<город>'   — напечатать ссылку
  dgis_link.py --tender <tender.json>                  — заполнить delivery.map_url в файле
                                                         (адрес: delivery.address, иначе address_notice)
  --offline          в сеть не ходить: сразу запасная ссылка (или id из --html)
  --html FILE        разобрать сохранённую страницу поиска 2ГИС вместо GET (проверка без сети)
  --short            только напечатать сокращённый адрес
Вывод: ссылка в stdout; в stderr — «2ГИС: geo» или «2ГИС: … ссылка на поиск».
Код: 0 — ссылка есть (geo или запасная), 2 — неверные аргументы/файл.
Только стандартная библиотека python 3.10+. В сеть — только к 2gis.ru (кроме --offline/--html).
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

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
_DROP = re.compile(r"этаж|подъ[её]м|офис|\bоф\b|кабинет|\bкаб\b|помещ|\bпом\b|подъезд|склад|"
                   r"тел\b|телефон|\+7|разгрузк|вход|ворот", re.I)
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/141.0.0.0 Safari/537.36")
_LAST = [0.0]


def city_slug(city: str) -> str:
    c = (city or "").strip().lower()
    c = re.sub(r"^г\.\s*", "", c)
    return GIS_CITIES.get(c) or "".join(_TR.get(ch, ch) for ch in c).replace(" ", "-") or "novosibirsk"


def short_address(text: str, city: str = "") -> str:
    """«г. Город, ул. Улица, дом» — без названия, индекса, телефона, офиса, этажа и примечаний."""
    t = (text or "").split(";")[0]
    t = re.sub(r"\([^()]*\)", " ", t)                     # (вариант А), (+7 ...), (с подъёмом)
    t = re.sub(r"«[^»]*»|\"[^\"]*\"", " ", t)               # «Компания»
    t = re.split(r"\bтел\.?|\+7|\b8 \(", t)[0]              # телефон и всё после
    keep = []
    for part in (p.strip(" .,—-") for p in t.split(",")):
        if not part or re.fullmatch(r"\d{6}", part) or _DROP.search(part):
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


def _state(html: str):
    m = re.search(r"var initialState = JSON\.parse\('(.*?)'\);", html, re.S)
    if not m:
        return None
    raw = m.group(1)
    for dec in (lambda r: r.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8"),
                lambda r: r):
        try:
            return json.loads(dec(raw))
        except (ValueError, UnicodeError):
            continue
    return None


def parse_search(html: str, addr: str) -> str | None:
    """id здания из HTML поиска 2ГИС: ровно одно здание и номер дома совпал; иначе None."""
    state = _state(html)
    if not isinstance(state, dict):
        return None
    prof = ((state.get("data") or {}).get("entity") or {}).get("profile") or {}
    blds = [(v.get("data") or {}) for v in prof.values()
            if isinstance(v, dict) and (v.get("data") or {}).get("type") == "building"]
    if len(blds) != 1:
        return None
    b = blds[0]
    house = re.findall(r"\d+", addr.split(",")[-1] if "," in addr else addr)
    name = b.get("address_name") or b.get("name") or ""
    if not house or house[0] not in re.findall(r"\d+", name):
        return None
    bid = str(b.get("id", "")).split("_")[0]
    return bid if bid.isdigit() else None


def fetch(slug: str, addr: str) -> str | None:
    """Один GET страницы поиска (пауза ~1 с между адресами). None — 404 или нет сети."""
    time.sleep(max(0.0, 1.0 - (time.time() - _LAST[0])))
    req = urllib.request.Request(f"https://2gis.ru/{slug}/search/{quote(addr, safe='')}",
                                 headers={"User-Agent": _UA, "Accept": "text/html",
                                          "Accept-Language": "ru-RU,ru;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"2ГИС: {addr}: HTTP {e.code}", file=sys.stderr)
    except OSError as e:
        print(f"2ГИС: {addr}: сеть — {e}", file=sys.stderr)
    finally:
        _LAST[0] = time.time()
    return None


def map_url(address: str, city: str, offline: bool = False, html: str | None = None) -> str:
    """Ссылка на здание (geo) или запасная ссылка на поиск."""
    slug = city_slug(city)
    addr = short_address(address, city)
    bid = None
    if re.search(r"\d", addr):                         # без номера дома здание не найти
        if html is None and not offline:
            html = fetch(slug, addr)
        if html is not None:
            bid = parse_search(html, addr)
    if bid:
        print(f"2ГИС: {addr}: geo/{bid}", file=sys.stderr)
        return f"https://2gis.ru/{slug}/geo/{bid}"
    print(f"2ГИС: {addr}: id здания не найден — ссылка на поиск", file=sys.stderr)
    return f"https://2gis.ru/{slug}/search/{quote(addr, safe='')}"


def tender_address(d: dict) -> str:
    for k in ("address", "address_notice"):
        v = (d.get(k) or "").strip()
        if v and v.lower() != "не указано":
            return v
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address")
    ap.add_argument("--city")
    ap.add_argument("--tender", type=Path, help="tender.json: заполнить delivery.map_url")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--html", type=Path)
    ap.add_argument("--short", action="store_true")
    a = ap.parse_args()
    html = a.html.read_text(encoding="utf-8") if a.html else None
    if a.tender:
        try:
            tj = json.loads(a.tender.read_text(encoding="utf-8"))
            dl = tj["delivery"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"ОШИБКА: {a.tender}: {e}", file=sys.stderr)
            return 2
        address, city = a.address or tender_address(dl), a.city or dl.get("city") or ""
    elif a.address and a.city:
        address, city = a.address, a.city
    else:
        ap.error("нужно --tender или --address с --city")
    if a.short:
        print(short_address(address, city))
        return 0
    url = map_url(address, city, a.offline, html)
    if a.tender:
        dl["map_url"] = url
        a.tender.write_text(json.dumps(tj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"delivery.map_url записан в {a.tender}", file=sys.stderr)
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
