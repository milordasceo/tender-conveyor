# Установка Кузнеца ботом

Для бота, который создаёт Кузнеца. Все значения — из `kuznets/bot.yaml`. Кто такой Кузнец и как он работает — `kuznets/README.md`. Установка руками — `SETUP.md`.

Правила:

- шаги по порядку; следующий — только после контрольной точки (КТ);
- секреты не писать в чат, в репозиторий, в отчёты;
- адрес Google-аккаунта нигде не писать. Называть его «аккаунт Google, владеющий папкой Госзакупки»;
- рутину включать последней.

## 1. Прочитать манифест

Прочитать `kuznets/bot.yaml`, `kuznets/bot/prompt.md`, `kuznets/bot/routine_prompt.md`.

КТ: известны имя, промт, рутина, файлы, секреты, шаги владельца.

## 2. Создать бота

1. Создать бота: `bot.name`, `bot.title`, `bot.description`.
2. Системный промт — весь файл `bot.prompt_file`.
3. Заменить плейсхолдеры из `bot.placeholders` на agent id ботов. Бота ещё нет — оставить плейсхолдер, записать в отчёт, заменить после его создания.
4. Рутину пока не создавать.

КТ: бот «Кузнец» существует; в промте нет чужих id старой установки.

## 3. Запросить у владельца сразу всё

Одним сообщением, тексты — из `owner_steps`:

- `oauth_client` — оба варианта на выбор;
- `google_cloud_terms` — если выбран новый клиент;
- `old_registry`;
- `confirm_schedule` (подставить часовой пояс бокса из `date`).

Пока ждём ответа — шаги 4–5.

## 4. Развернуть файлы

```bash
git clone https://github.com/milordasceo/tender-conveyor.git /tmp/tender-conveyor
mkdir -p /home/box/gosplan/scripts
cp /tmp/tender-conveyor/kuznets/scripts/{gosplan_scanner.py,gosplan_lib.py,config.novosibirsk.yaml,config.example.yaml,README.md} /home/box/gosplan/scripts/
```

Соответствие путей — `deploy`. `/home/box/gosplan` уже есть — не затирать `scripts/state` и `.env`.

КТ: `ls /home/box/gosplan/scripts` показывает 5 файлов.

## 5. Зависимости

```bash
python3 --version                       # нужно >= 3.10
python3 -m venv /home/box/gosplan/.venv
/home/box/gosplan/.venv/bin/pip install pyyaml
curl https://rclone.org/install.sh | sudo bash
rclone version                           # проверено на 1.75.2
cd /home/box/gosplan/scripts && ../.venv/bin/python gosplan_scanner.py -c config.novosibirsk.yaml --dry-run
```

КТ: `--dry-run` печатает `найдено: 0`, `новых: 0`, `выгружено: 0`, код 0.

## 6. Google Drive

1. Секреты от владельца (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`) записать в `/home/box/gosplan/.env`, `chmod 600`.
2. rclone: `owner_steps.rclone_authorize`. Бот запускает `rclone config create ...` в фоне, открывает ссылку входа в браузере бокса, владелец входит через рабочий стол бокса аккаунтом Google, владеющим папкой «Госзакупки».
3. Раскладка `drive_layout` через коннектор Google Drive (тот же аккаунт) или `rclone lsd`:
   - «Госзакупки», «Госзакупки/Сток», «Госзакупки/Бланки» есть — использовать как есть;
   - нет — создать (`rclone mkdir 'gosplan:Госзакупки/Сток'`, `rclone mkdir 'gosplan:Госзакупки/Бланки'`);
   - «Сток» не пересоздавать, не чистить, папки в нём не трогать. Id папок не записывать.

КТ: `rclone lsd gosplan:Госзакупки` показывает `Сток` и `Бланки`.

## 7. Реестр выгрузки

Реестр с репозиторием не едет. Он лежит на боксе: `/home/box/gosplan/scripts/state/export_00cd167b09dc.json` (имя = sha1 строки `gosplan:Госзакупки/Сток`, первые 12 знаков).

Пустой реестр = первый прогон берёт все подходящие тендеры. Что это значит для того же «Сток»:

- папки, которые лежат в «Сток», сканер не копирует повторно: перед выгрузкой он делает `rclone lsf` и записывает такие номера в реестр (`dup: remote`). Запрос API на каждый такой номер всё равно идёт;
- папки, которые Фатима уже унесла из «Сток», выгрузятся снова. Это дубли для Фатимы.

Других способов засеять реестр в сканере нет. Варианты, по порядку предпочтения:

0. **Основной путь.** В репозитории лежит перенесённый реестр: `kuznets/state/export_*.json` (см. `kuznets/state/README.md`). Скопировать его в `/home/box/gosplan/scripts/state/` с тем же именем до первого запуска. Тогда первый прогон догрузит очередь и не будет дублей. Остальные варианты ниже нужны только если этого файла нет или он устарел.

1. Владелец прислал старый реестр → положить файл в `/home/box/gosplan/scripts/state/` с тем же именем. Содержит только публичные номера тендеров.
2. Старого реестра нет, но прежний Кузнец выгружал в этот «Сток» → собрать реестр из номеров. Номера — имена папок в «Сток» и в папках, куда тендеры унесли следующие звенья (где они — спросить владельца или Смотрителя; не угадывать). Список номеров по одному в строке — в `/tmp/known_numbers.txt`, затем:

   ```bash
   mkdir -p /home/box/gosplan/scripts/state
   /home/box/gosplan/.venv/bin/python - <<'PY'
   import json, pathlib
   nums = [l.strip() for l in open('/tmp/known_numbers.txt', encoding='utf-8') if l.strip()]
   reg = {"export_dir": "", "remote": "gosplan:Госзакупки/Сток",
          "tenders": {n: {"status": "exported", "dup": "seed"} for n in nums},
          "pending": [], "pending_since": None, "last_completed_at": None}
   p = pathlib.Path('/home/box/gosplan/scripts/state/export_00cd167b09dc.json')
   assert not p.exists(), 'реестр уже есть — не затирать'
   p.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding='utf-8')
   print(len(nums))
   PY
   ```

   `last_completed_at: null` → поиск без фильтра даты, но известные номера в очередь не попадут.
3. Владелец подтвердил, что прежний Кузнец в этот «Сток» не выгружал → реестр пустой.

Во всех вариантах: рутина прежнего Кузнеца остановлена. Два Кузнеца на один «Сток» дают дубли.

КТ: выбран и выполнен один вариант; ответ владельца записан в отчёт.

## 8. Проверка

Команды и ожидания — `verification`. Коротко:

```bash
cd /home/box/gosplan/scripts
GOSPLAN_STATE_DIR=/tmp/kuznets_check ../.venv/bin/python gosplan_scanner.py -c config.novosibirsk.yaml \
  --remote 'gosplan:Госзакупки/_проверка_кузнеца' --limit 1; echo "exit=$?"
rclone lsf 'gosplan:Госзакупки/_проверка_кузнеца' --dirs-only
rclone lsf "gosplan:Госзакупки/_проверка_кузнеца/<номер>"
rclone purge 'gosplan:Госзакупки/_проверка_кузнеца'
rm -rf /tmp/kuznets_check
```

`GOSPLAN_STATE_DIR` обязателен: проверка не должна писать в боевой реестр. Прогон может идти до 30 минут (лимит API, 429).

КТ: `выгружено: 1`; код 3 или 0; в папке проверки одна папка с `tender.md` и `tender.json`; папка проверки удалена; боевой реестр не изменился.

## 9. Рутина

1. Создать рутину для бота Кузнец: `routines[0].name`, расписание `routines[0].cron` во времени, подтверждённом владельцем.
2. Промт — весь файл `routines[0].prompt_file`.
3. Включить. Перед этим — все `first_run.preconditions`.

КТ: рутина есть и включена.

## 10. Отчёт владельцу

Одно сообщение:

- бот «Кузнец» создан; какие плейсхолдеры id ещё не заменены;
- скрипты развёрнуты, версии python и rclone;
- rclone подключён к аккаунту Google, владеющему папкой «Госзакупки» (адрес не писать); раскладка «Сток»/«Бланки» найдена или создана;
- какой OAuth-клиент (готовый или новый); если приложение в режиме Testing — вход истечёт через 7 дней, нужна публикация;
- реестр: вариант 1, 2 (сколько номеров) или 3;
- проверка: номер тестового тендера, код выхода, папка проверки удалена;
- рутина: имя, время, часовой пояс; первый прогон возьмёт все подходящие тендеры и может идти больше часа (код 3 — доберёт на следующий день).
