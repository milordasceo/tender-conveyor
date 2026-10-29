# Установка Кузнеца с нуля

Для человека. Бот-установщик идёт по `INSTALL_BY_BOT.md` и `bot.yaml`.

Новый бокс Grok Bot. Цель: сканер в `/home/box/gosplan/scripts`, окружение в `/home/box/gosplan/.venv`, rclone-приёмник `gosplan:` на Google Drive с папкой «Госзакупки».

## 1. Бот

1. Создать бота в Grok Bot. Имя, заголовок, описание — из `bot.yaml`. Системный промт — весь файл `bot/prompt.md`.
2. В промте заменить `<id Смотрителя>`, `<id Фатимы>`, `<id Скрипты и интеграции>` на agent id этих ботов.
3. Рутины пока не создавать. Их создают по `bot/routine.md` после проверки (шаг 8) и запуска добора.

## 2. Скрипты

```bash
git clone https://github.com/milordasceo/tender-conveyor.git /tmp/tender-conveyor
mkdir -p /home/box/gosplan/scripts
cp /tmp/tender-conveyor/kuznets/scripts/* /home/box/gosplan/scripts/
```

Состав: `gosplan_scanner.py` (сканер), `gosplan_lib.py` (HTTP, лимит API, ссылки, проверка города), `config.novosibirsk.yaml` (рабочий конфиг), `config.example.yaml` (все ключи с пояснениями), `README.md` (описание сканера). Сканер импортирует только `gosplan_lib.py`.

## 3. Python

Нужен Python 3.10+. Зависимость одна: `pyyaml`. Остальное — стандартная библиотека.

```bash
python3 -m venv /home/box/gosplan/.venv
/home/box/gosplan/.venv/bin/pip install pyyaml
```

На текущем боксе стоят `PyYAML 6.0.3`, `olefile`, `pypdf`. Последние два сканеру не нужны.

## 4. Переменные `.env`

Файл `/home/box/gosplan/.env`. В репозиторий не коммитить. Сканер `.env` сам не читает. Список имён — для справки и для других инструментов набора:

| имя | что | как получить |
|---|---|---|
| `GOSPLAN_API_KEY` | ключ прод-сервера gosplan | t.me/gosplan_project (trial 7 дней). Сканер берёт ключ из поля `api_key` yaml-конфига — вписать туда |
| `NOTION_API_TOKEN` | Notion | для других звеньев; Кузнецу не нужен |
| `COMPOSIO_ACCOUNT` | аккаунт Composio для Drive | из оригинального набора; Кузнецу не нужен |
| `GOOGLE_OAUTH_CLIENT_ID` | id OAuth-клиента Google | шаг 6 |
| `GOOGLE_OAUTH_CLIENT_SECRET` | секрет OAuth-клиента Google | шаг 6 |
| `DRIVE_ROOT_ID` | id корневой папки Drive | из оригинального набора; Кузнецу не нужен |
| `TENDERS_DIR` | локальная папка тендеров | из оригинального набора; Кузнецу не нужен |
| `CA_BUNDLE_PATH` | CA для zakupki.gov.ru | Кузнецу не нужен (режим `--collect` не используется) |

Сканер читает из окружения только `GOSPLAN_STATE_DIR` — каталог реестра. Если она задана, она важнее `state_dir` конфига. Не задана и `state_dir` нет — реестр в `scripts/state`.

## 5. gosplan API

- Тест: `https://v2test.gosplan.info`, ключ не нужен. Рабочий конфиг смотрит сюда.
- Прод: `https://v2.gosplan.info`, нужен ключ из t.me/gosplan_project. Поменять `base_url` и `api_key` в yaml.
- zakupki.gov.ru с бокса недоступен (гео). Для выгрузки это не мешает: сканер только пишет ссылки.

## 6. Свой OAuth-клиент Google

Общий client_id rclone выводится из оборота. Нужен свой. Два варианта.

**Готовый клиент.** Сейчас клиент есть в другом Google-аккаунте (проект gosplan-rclone). Владелец даёт его client_id и client_secret как секреты. Приложение там в режиме Testing: вход истекает через 7 дней. Чтобы не истекал — OAuth consent screen → Publish app (homepage и privacy policy — `https://github.com/milordasceo/tender-conveyor`).

**Новый клиент** в любом Google-аккаунте:

1. Google Cloud Console → принять условия → новый проект.
2. APIs & Services → Library → включить Google Drive API.
3. OAuth consent screen: тип External. Homepage и privacy policy: `https://github.com/milordasceo/tender-conveyor`.
4. Publish app → In production.
5. Credentials → Create credentials → OAuth client ID → Desktop app.
6. client_id и client_secret — в `.env` (шаг 4). JSON клиента не коммитить.

Аккаунт клиента и аккаунт Drive могут быть разными. Вход в rclone (шаг 7) — всегда аккаунтом Google, владеющим папкой «Госзакупки».

## 7. rclone

На текущем боксе rclone `v1.75.2`.

```bash
curl https://rclone.org/install.sh | sudo bash
rclone version
rclone config create gosplan drive scope=drive client_id=<CLIENT_ID> client_secret=<CLIENT_SECRET>
```

Авторизация — аккаунтом Google, которому принадлежит папка «Госзакупки». На боксе без браузера: `rclone authorize "drive" "<CLIENT_ID>" "<CLIENT_SECRET>"` на машине с браузером, полученный токен вставить в `rclone config` на боксе. Либо пройти вход в браузере рабочего стола бокса.

Раскладка Drive:

```
Госзакупки/
  Сток/     # папки тендеров от Кузнеца
  Бланки/
```

Проверка:

```bash
rclone lsd gosplan:Госзакупки
```

Должны быть видны `Сток` и `Бланки`. Есть — использовать как есть, не пересоздавать и не чистить. Нет — `rclone mkdir 'gosplan:Госзакупки/Сток'`, `rclone mkdir 'gosplan:Госзакупки/Бланки'`. Id папок нигде не записывать.

Реестр выгрузки: перед первым запуском скопировать `kuznets/state/export_00cd167b09dc.json` в `/home/box/gosplan/scripts/state/` (см. `kuznets/state/README.md` и `INSTALL_BY_BOT.md`, шаг 7). Прежнего Кузнеца остановить. `rclone.conf` (`~/.config/rclone/rclone.conf`) содержит токен — не коммитить.

## 8. Проверка работы

Пробный прогон в отдельную папку, не в «Сток». Реестр — во временный каталог, чтобы не испортить рабочий.

```bash
cd /home/box/gosplan/scripts
../.venv/bin/python gosplan_scanner.py -c config.novosibirsk.yaml --dry-run
GOSPLAN_STATE_DIR=/tmp/kuznets_check ../.venv/bin/python gosplan_scanner.py -c config.novosibirsk.yaml \
  --remote 'gosplan:Госзакупки/_проверка_кузнеца' --limit 1; echo "exit=$?"
rclone lsf 'gosplan:Госзакупки/_проверка_кузнеца' --dirs-only
rclone cat "gosplan:Госзакупки/_проверка_кузнеца/<номер>/tender.md"
```

Ожидается:

- `--dry-run`: URL запросов в stderr, на stdout `0 / 0 / 0`;
- пробный прогон: `выгружено: 1`, код `3` (в очереди остальные) или `0`;
- в папке проверки одна папка с номером, внутри `tender.md` и `tender.json` по `FORMAT.md`.

Убрать следы:

```bash
rclone purge 'gosplan:Госзакупки/_проверка_кузнеца'
rm -rf /tmp/kuznets_check
```

Первый боевой прогон делает рутина (`bot/routine.md`). Он выгружает все подходящие тендеры и может идти больше часа.
