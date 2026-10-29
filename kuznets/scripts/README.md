> Копия из `/home/box/gosplan/scripts` (бокс Кузнеца). На Grok Bot набор лежит в `/home/box/gosplan/scripts`, окружение — `/home/box/gosplan/.venv`. Пути ниже относительные: `scripts/` — эта папка, `..` — каталог уровнем выше (`/home/box/gosplan`). Установка с нуля — `../SETUP.md`.

# Сканер закупок gosplan.info

Консольный сборщик закупок 44-ФЗ и 223-ФЗ через API [gosplan.info](https://gosplan.info). Читает фильтры из yaml-конфига, умеет перекрыть их аргументами командной строки. Публичной HTML-карточки у gosplan.info нет: «ссылка gosplan» — это URL API детали.

Два режима записи:

- обычный (`--collect`) — комплекты в каталог `output.dir` из конфига (`tenders/с найденными/<номер>/`, `seen.json`, отчёты `run_*.json|csv`);
- `--export DIR` — только `DIR/<номер>/tender.md` и `tender.json`, без скачивания файлов и без записи в `tenders/`.

## Требования

- Python 3.10+ и `pip install pyyaml` (виртуальное окружение — `.venv` на уровень выше папки `scripts`)
- доступ к API gosplan.info (тестовый сервер `https://v2test.gosplan.info` — без ключа; прод `https://v2.gosplan.info` — ключ в `api_key`)
- для `--collect` (скачивание файлов с zakupki.gov.ru) — российский CA, см. runbooks

## Запуск

```bash
cd scripts
python gosplan_scanner.py -c config.novosibirsk.yaml --help
```

Логи — в stderr. В конце на stdout всегда ровно три строки:

```
найдено: N
новых: N
выгружено: N
```

- **найдено** — кандидаты поиска этого запуска (0, если шла только очередь `pending`). `--limit` это число не режет;
- **новых** — из найденных те, кого ещё нет в реестре `tenders` (0, если шла только очередь). В обычном режиме — ещё не закрытые в `seen.json`;
- **выгружено** — сколько папок записано в этом прогоне (`--export`); в остальных режимах всегда `0`.

Код выхода: `0` очередь пуста, `3` выгрузка не закончена (её продолжит следующий запуск), `2` ошибка конфига. При коде `3` в stderr строка «Выгрузка не закончена, продолжится при следующем запуске». В конце прогона выгрузки пишется `run_report.json` в `state_dir` и в `logs/` рядом со скриптом: `remote` (строка приёмника или `null`) и `rclone_failures` (сколько раз `rclone copy` не записал папку). В stderr также `pending: осталось N`.

`--dry-run` api не вызывает, печатает URL запросов в stderr и сводку `0 / 0 / 0`.

## Аргументы CLI

| аргумент | по умолчанию | смысл |
|---|---|---|
| `-c`, `--config` | `config.yaml` рядом со скриптом | yaml с базовым url, источниками, фильтрами, лимитами |
| `--dry-run` | выкл. | показать URL списков и выйти |
| `--collect N` | `0` | скачать документы первых N новых закупок в `tenders/с найденными` |
| `--export DIR` | `export.dir` из конфига | выгрузка в `DIR`. Если в конфиге задан `export.dir` и нет `--collect` и `--no-export`, выгрузка включается сама. Относительный `export.dir` считается от папки файла конфига |
| `--no-export` | выкл. | не выгружать, даже если в конфиге есть `export.dir` (прежний режим `seen` / `--collect`) |
| `--limit N` | `run.limit`, иначе `0` | в `--export`: сколько папок записать за этот запуск по очереди `pending`. `0` = всю очередь. Статус `outside` в лимит не входит. Ошибка API оставляет закупку в очереди. В `--collect` игнорируется |
| `--city-strict` | `export.city_strict`, иначе выкл. | в `--export`: не писать закупки вне города (статус `outside`, отсев ещё и по списку `delivery_places`). Без флага и без `export.city_strict` такие закупки выгружаются с пометкой. `--collect` всегда строгий |
| `--kind KIND` | `filters.kinds` | вид закупки: `auction`, `zk`, `ok`, `zp`, `ep`. Можно повторять и через запятую. Коды `purchase_type` берутся из блока `purchase_kinds` конфига и **перекрывают** `filters.purchase_types`. Пустой список по закону — этот источник не запрашивается. Нет блока или вида в конфиге — выход 2 |
| `--region CODE` | `filters.regions` | код региона KLADR; можно повторять и через запятую (`54`, `54,22`) |
| `--price-min N` | `filters.min_budget` | нижняя граница НМЦК, руб |
| `--price-max N` | `filters.max_budget` | верхняя граница НМЦК, руб |
| `--stage N` | `filters.stage` | этап `1`..`4` (1 — приём заявок); можно через запятую |
| `--types LAW` | `filters.types`, иначе `sources` | `44` и/или `223`; можно повторять и через запятую. Коды процедур — `filters.purchase_types`, если не задан `--kind` |
| `--deadline-from ДАТА` | `filters.deadline_from` | окончание подачи заявок **с** (`YYYY-MM-DD` или ISO datetime). На сервер: 44-ФЗ `collecting_finished_after`, 223-ФЗ `submission_close_after`. Повторная проверка на клиенте по нормализованному `collecting_finished_at`. Закупки без даты окончания отбрасываются |
| `--deadline-to ДАТА` | `filters.deadline_to` | то же **по** (`collecting_finished_before` / `submission_close_before`) |
| `--since ДАТА` | `filters.since`, иначе `auto` | `auto`: пустой реестр — без фильтра публикации; иначе дата `last_completed_at` в `Europe/Moscow` минус 1 день. Явная дата и `today` перекрывают `auto`. Эффективное значение пишется в stderr |

Приоритет: аргумент CLI, затем поле конфига, затем умолчание. Кроме флагов выше, в конфиге работают `filters.kinds`, `filters.since`, `filters.deadline_from`, `filters.deadline_to`, `filters.types` (`[44, 223]`), `run.limit`, `export.dir`, `export.city_strict`. `sources` по-прежнему список законов `fz44` / `fz223`.

После списка записи с чужим `purchase_type` отбрасываются ещё раз на клиенте (и для `--kind`, и для `filters.purchase_types`): сервер иногда игнорирует фильтр.

### `--kind` → коды

| вид | 44-ФЗ | 223-ФЗ |
|---|---|---|
| `auction` аукцион | `epNotificationEF2020` (электронный аукцион) | `purchaseNoticeAE` (аукцион в электронной форме), `purchaseNoticeAESMBO` (аукцион в электронной форме среди субъектов мсп), `purchaseNoticeOA` (открытый аукцион), `purchaseNoticeAE94FZ` (электронный аукцион (по 94-фз)) |
| `zk` котировки | `epNotificationEZK2020` (запрос котировок в электронной форме), `epNotificationEZK` (запрос котировок в электронной форме (до 2020)) | `purchaseNoticeZK` (запрос котировок), `purchaseNoticeZKESMBO` (запрос котировок в электронной форме среди субъектов мсп) |
| `ok` конкурс | `epNotificationEOK2020` (открытый конкурс в электронной форме), `epNotificationEOK` (открытый конкурс в электронной форме (до 2020)), `epNotificationEOKD` (двухэтапный конкурс в электронной форме), `epNotificationEOKOU` (конкурс с ограниченным участием в электронной форме) | `purchaseNoticeOK` (открытый конкурс), `purchaseNoticeKESMBO` (конкурс в электронной форме среди субъектов мсп) |
| `zp` предложения | `epNotificationEZP` (запрос предложений в электронной форме) | `purchaseNoticeZPESMBO` (запрос предложений в электронной форме среди субъектов мсп) |
| `ep` ед. поставщик | нет кода извещения в API | `purchaseNoticeEP` (закупка у единственного поставщика) |

В `tender.md`: `- тип закупки: код (имя)`. В `tender.json` код остаётся в `purchase_type`, имя — в `purchase_type_name`. Неизвестный код пишется как есть.

## Нормализация 223-ФЗ

В списках 223-ФЗ нет `collecting_finished_at` и список заказчиков — строка `customer`. Сканер приводит к общему виду:

- `submission_close_at` → `collecting_finished_at`
- `customer` → `customers = [customer]`

Ссылка на ЕИС — поиск `https://zakupki.gov.ru/epz/order/extendedSearch/results.html?searchString=<номер>`. Прямая карточка, если известен тип:

- 44-ФЗ `epNotificationEF2020` → `.../notice/ea20/view/common-info.html?regNumber=N`
- 44-ФЗ `epNotificationEZK2020` → `.../notice/zk20/view/common-info.html?regNumber=N`
- 223-ФЗ → `.../notice/notice223/common-info.html?noticeInfoId=ID` (id из `docs[].source.urlEIS`)

Документы: вложения 44-ФЗ (`attachmentsInfo.attachmentInfo`) и 223-ФЗ (`attachments.document`), плюс печатная форма извещения (`printFormInfo.url`), если есть. Файлы в `--export` **не** скачиваются.

## Режим `--export DIR`

После списка и клиентских фильтров (город по списку **не** режется, если нет `--city-strict`) для каждой новой закупки:

1. запрос детали API;
2. проверка города (`delivery_cities`): в файл пишется `city_check` — `в городе`, `вне города` или `нет данных` (если города в конфиге нет — `не проверялось`);
3. без `--city-strict` выгрузить всех, в том числе вне города. В состоянии `status: exported` и `city`: `inside` / `outside` / `unknown`. Старые записи `status: outside` от строгого прогона в мягком режиме выгружаются сейчас;
4. с `--city-strict` вне города не писать, в состоянии `status: outside`, в `--limit` не входят; такие же отсекаются по `delivery_places` ещё на списке;
5. атомарно записать `DIR/<номер>/tender.json` и `tender.md` (`файл.tmp` + `os.replace`, до 5 попыток);
6. ошибка API на одной закупке — в лог, в состояние не писать (повтор в следующем прогоне); после 5 сбоев подряд — стоп.

Идемпотентность решает только реестр `state_dir/export_<sha1 пути>[:12].json`, не наличие папки. В каталоге выгрузки остаются только папки номеров. Если там лежит старый `.export_state.json`, записи вливаются в реестр, файл удаляется. Повтор по уже решённому номеру (статус `exported` или `outside`) ничего не пишет. Непустой `pending` добирается без нового поиска. Пустой `pending` в конце прогона ставит `last_completed_at`. `--collect` город не ослабляет: вне города в `tenders/` не кладётся.

`state_dir`: ключ конфига (путь от папки конфига), иначе `GOSPLAN_STATE_DIR`, иначе `scripts/state`. Каталог создаётся. Там же слот API и `run_report.json`.

### Выгрузка через rclone

Настройка диска делается снаружи сканера, конфиг rclone в поставку не входит. Ключ `export.remote` (или `--remote`) — приёмник вида `gosplan:Госзакупки/Сток`. `export.dir` тогда не обязателен. `export.rclone` — путь к бинарю, по умолчанию `rclone`. Реестр называется по sha1 строки remote, не по локальной папке.

За прогон один раз: `rclone lsf <remote>/ --dirs-only`. Папка с номером уже есть — в реестре `{"status":"exported","dup":"remote"}`, без копирования. Иначе карточка собирается во временной папке `state_dir/tmp` и уходит командой `rclone copy`. Запись в реестре только после кода 0. Ошибка copy оставляет номер в `pending`, хвост stderr в логе, счётчик `rclone_failures`; пять сбоев подряд останавливают прогон. Временная папка удаляется и после успеха, и после ошибки. Код 3 у `lsf` или текст `directory not found` значит, что каталога ещё нет: список папок пустой, `copy` создаёт его. Другой ненулевой код `lsf` выгрузку не начинает, `pending` не трогается, код выхода 3. Без remote поведение локальной папки прежнее.

### Формат `tender.md`

```markdown
# 0351300082326000377

- закон: 44-ФЗ
- тип закупки: epNotificationEF2020 (электронный аукцион)
- предмет: Поставка лекарственного препарата …
- нмцк: 81402.3 RUB
- регион: 54
- место поставки: город Новосибирск, улица Ленина
- город: в городе (Новосибирск)
- этап: 1
- окончание этапа: 2026-11-06T01:00:00
- опубликовано: 2026-10-28T15:25:10.335000
- заказчики: 5434100769
- поиск на zakupki: https://zakupki.gov.ru/epz/order/extendedSearch/results.html?searchString=0351300082326000377
- карточка zakupki: https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0351300082326000377
- api gosplan: https://v2test.gosplan.info/fz44/purchases/0351300082326000377

## Документы

1. [НМЦК.docx.zip](https://zakupki.gov.ru/...) — НМЦК.docx.zip
2. [Печатная форма извещения](https://zakupki.gov.ru/epz/order/notice/printForm/view.html?regNumber=0351300082326000377) — печатная форма извещения
```

Те же поля в `tender.json`, плюс `delivery_places` (список текстов места поставки) и `city_check`. Остальное: `number`, `law`, `purchase_type`, `purchase_type_name`, `subject`, `initial_price`, `currency`, `region`, `stage`, `stage_end`, `published_at`, `customers`, `zakupki_search`, `zakupki_card`, `gosplan`, `documents: [{name, description, url, size}]`.

## Лимит API

Базовый интервал **10 с** между запросами gosplan (6 в минуту, с запасом). Слот общий у CLI и панели.

- Файл `scripts/gosplan_api.slot` — JSON `{"next_ts", "interval", "penalty_until"}` (старый формат «голое число» тоже читается).
- Блокировка `fcntl.flock` на `gosplan_api.slot.lock` только на время чтения и записи слота, не на время паузы и не на время HTTP. На Windows — `msvcrt.locking` одного байта, при ошибке короткая пауза и повтор. Каталог слота — `state_dir` (см. выше). Счётчик HTTP 429 попадает в `run_report.json`.
- Процесс берёт слот: если `now >= next_ts`, пишет `next_ts = now + интервал` и идёт в запрос; иначе отпускает блокировку, спит не дольше 2 с и пробует снова. Интервал — свой, а пока `now < penalty_until` — максимум из своего и `interval` в слоте.
- HTTP 429 (один разбор в `get_with_backoff`, и список, и деталь): интервал процесса ×1.5, потолок **20 с**, до конца прогона. В слот: `interval`, `penalty_until = now + 600`, `next_ts` не раньше `now + пауза`. Пауза — `Retry-After` (секунды или HTTP-дата), иначе удвоенный новый интервал. До 4 повторов, дальше ошибка. Параллельные процессы ждут тот же `Retry-After`.
- Если к концу прогона интервал вырос — строка об этом в stderr.

Сетевой обрыв на странице списка по-прежнему повторяется с паузами 10/20/30 с.

## Примеры

Новосибирск, 30–150 тыс., этап 1, выгрузка:

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --export /tmp/tenders_nsk --limit 20
```

Несколько регионов:

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --region 54 --region 22 --export /tmp/tenders_54_22
```

Только 44-ФЗ:

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --types 44 --export /tmp/tenders_44
```

Окно окончания подачи заявок:

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --deadline-from 2026-11-01 --deadline-to 2026-11-15 --export /tmp/tenders_dl
```

Публикация с конкретной даты (не «сегодня»):

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --since 2026-10-28 --export /tmp/tenders_since
```

Только посмотреть URL запросов:

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --region 54 --region 22 --types 44 --deadline-from 2026-11-01 --since 2026-10-28 --dry-run
```

Только запрос котировок (коды из `purchase_kinds`):

```bash
python gosplan_scanner.py -c config.novosibirsk.yaml --region 54 --kind zk --stage 1 --dry-run
```

## Windows

Консоль в cp866/cp1251 не роняет процесс: stdout/stderr переключаются на `errors=replace`, кодировка консоли сохраняется. Файлы пишутся в utf-8. Пути только через `pathlib`. Если Google Drive держит файл, `os.replace` повторяется до 5 раз.

`output.dir: "../tenders"` в `config.novosibirsk.yaml` считается от папки скрипта.

## Первый запуск на новом box

Нужны rclone, Python и свой конфиг. Файл конфигурации rclone сканер не привозит.

1. Поставить rclone: `curl https://rclone.org/install.sh | sudo bash`. Либо скачать zip со страницы rclone и положить бинарь в `PATH`.
2. Приёмник Google Drive: `rclone config create gosplan drive scope=drive`.
3. Вход Google — в браузере. rclone сам откроет авторизацию (`rclone authorize` или автонастройка `rclone config`). Дойти до конца, пока команда не запросит подтверждение.
4. Проверить, что папка видна: `rclone lsd gosplan:Госзакупки`.
5. Окружение рядом с репозиторием: `python3 -m venv .venv`, затем `.venv/bin/pip install pyyaml`.
6. В yaml сканера указать `state_dir` (каталог реестра) и `export.remote`, например `gosplan:Госзакупки/Сток`. `export.rclone` — только если бинарь не называется `rclone`.

Пример cron, раз в сутки. Код 3 значит, что очередь не пуста и следующий запуск её продолжит:

```cron
15 7 * * * cd /путь/к/scripts && ../.venv/bin/python gosplan_scanner.py -c config.novosibirsk.yaml --remote 'gosplan:Госзакупки/Сток' >> ../logs/cron.log 2>&1
```

```bat
@echo off
chcp 65001
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
"..\.venv\Scripts\python.exe" gosplan_scanner.py -c config.novosibirsk.yaml --export "G:\Мой диск\Госзакупки\Сток"
```
