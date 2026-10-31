# Скрипты Фатимы

Только стандартная библиотека Python 3.10+. Внешние программы: `soffice` (LibreOffice) для `.doc/.rtf/.odt/.xls(x)`, `pdftotext` (poppler-utils) для `.pdf`. С Google Диском скрипты не работают: файлы качает и заливает rclone (`gosplan:`), скрипты правят локальные копии.

На боксе: `/home/box/fatima/scripts/`.

| файл | что делает | запуск | код выхода |
|---|---|---|---|
| `check_ready.py` | готова ли папка: `docs_status.json` → `state == "done"`, `error == null`, у всех `documents[]` `status == "ok"`, файлы на месте | `check_ready.py <папка>...` или `rclone cat '.../docs_status.json' \| check_ready.py --status-file -` | 0 — все готовы, 1 — есть неготовые |
| `extract_text.py` | тексты всех документов папки в `.txt` для чтения целиком | `extract_text.py <папка> --out /home/box/fatima/txt/<номер>` | 0 — всё извлечено, 1 — есть `error`/`empty` |
| `dgis_link.py` | ссылка 2ГИС на адрес «куда привезти»: карточка здания `https://2gis.ru/<город>/geo/<id>`, не нашлось — `https://2gis.ru/<город>/search/<адрес>`; `--tender` пишет её в `delivery.map_url` | `dgis_link.py --tender tender.json` или `dgis_link.py --address '<адрес>' --city '<город>'` (`--offline`, `--html <файл>`, `--short`) | 0 — ссылка есть (geo или запасная), 2 — неверные аргументы/файл |
| `tender.schema.json` | схема `tender.json` после разбора (schema_version 1) | — | — |
| `validate_tender.py` | проверка `tender.json` по схеме + здравый смысл (`delivery.map_url` обязателен: https://2gis.ru/<город>/geo|search/…, без `?stat=`, город = `delivery.city`; запасная ссылка — предупреждение; сумма позиций = НМЦК, категория и лицензии/опыт, «не указано» в важных полях, пустые особые пометки при подъёме/разгрузке в условиях доставки; `conditions.national_regime` — объект `mandatory`/`measure`/`basis`/`confirmation`/`note`, mandatory сходится с measure: true — запрет/ограничение, false — преимущество/не установлен, null — нет данных с причиной в note) | `validate_tender.py tender.json --folder-name <номер>` | 0 — по схеме (предупреждения возможны), 1 — ошибки |
| `render_md.py` | `tender.md` из `tender.json` (строка «Нацрежим»: «Обязателен: ДА/НЕТ/нет данных — мера; основание; подтверждение»; функция `national_regime_line` — для точечной замены строки) | `render_md.py tender.json [-o tender.md]` | 0 |
| `counter.py` | `счётчик.json`: `show`, `inc`, `count`, `init` | см. ниже | 0 — ок, 1 — отказ, 2 — неверные аргументы |
| `selftest.sh` | самопроверка всех скриптов во временной папке, без rclone | `bash selftest.sh` | 0 — всё прошло |

## Ссылка 2ГИС

```bash
python3 /home/box/fatima/scripts/dgis_link.py --tender /home/box/fatima/work/<номер>/tender.json   # рутина: после записи tender.json, до validate_tender.py
python3 dgis_link.py --address '630027, г. Новосибирск, ул. Богдана Хмельницкого, д.104, этаж 7' --city Новосибирск
# → https://2gis.ru/novosibirsk/geo/141373143524501
```

Только адрес «куда привезти» (`delivery.address`, нет — `address_notice`). Ссылки «откуда забрать» делает Черри Пикер; CRM-бот Сисадмин берёт ссылку из `delivery.map_url`. Правило — как в `sysadmin/scripts/notion_card.py`. Ссылка — карточка здания `https://2gis.ru/<город латиницей>/geo/<id здания>`, без `?stat=` (пример: https://2gis.ru/novosibirsk/geo/141373143524501 — ул. Богдана Хмельницкого, 104). Скрипт сокращает адрес до города, улицы и дома (без названия, индекса, офиса, этажа), делает один GET на `https://2gis.ru/<город>/search/<адрес>` с браузерным User-Agent (пауза ~1 с между адресами), берёт id из JSON `initialState` → `data.entity.profile`, только если найдено ровно одно здание и номер дома совпал. Иначе (не совпало, 404, нет сети) — запасная ссылка `https://2gis.ru/<город>/search/<адрес>`. В сеть — только `https://2gis.ru`; `--offline` и `--html` для проверки без сети (их использует `selftest.sh`).

## Счётчик

```bash
C=/home/box/fatima/state/счётчик.json
R='gosplan:Госзакупки/Цены/Новосибирск'
rclone copyto "$R/счётчик.json" "$C"                                  # скачать
python3 counter.py inc "$C" 'В городе'                               # +1, время по Новосибирску
rclone copyto "$C" "$R/счётчик.json" && rclone cat "$R/счётчик.json"   # залить и проверить
# файла на Диске нет — создать по текущим папкам (уже перенесённый тендер посчитан, +1 не нужен):
rclone lsf -R --dirs-only "$R" | python3 counter.py init "$C"
```

`count`/`init` считают папки, чьё имя — номер тендера (6+ цифр), по первой папке пути: «В городе», «Загород», «С ограничениями» (тендеры с ограничениями лежат прямо в ней; подпапка внутри категории, если окажется, считается в категорию). Время «обновлено» — всегда Новосибирск (UTC+7, Asia/Novosibirsk), от TZ бокса не зависит; опции `--tz` нет. Папки внутри папки тендера не считаются. `init` не затирает существующий файл без `--force`. `inc` не создаёт файл.

## Проверено

29.10.2026 на тендере 0151100007126000034 (4 `.doc`/`.docx` + печатная форма `.html`): `check_ready` → ready, `extract_text` → 5 из 5 ok за ~4 с, `validate_tender` → 0 ошибок, 0 предупреждений, `render_md` совпадает с ручным `tender.md` тестового прогона по содержанию. `selftest.sh` — всё прошло. Запись на Диск скриптами не проверялась (её делает rclone).
