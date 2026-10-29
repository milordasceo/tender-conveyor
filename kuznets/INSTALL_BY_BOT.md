# Установка Кузнеца ботом

Для бота, который создаёт Кузнеца. Все значения — из `kuznets/bot.yaml`. Кто такой Кузнец и как он работает — `kuznets/README.md`. Установка руками — `SETUP.md`.

Правила:

- шаги по порядку; следующий — только после контрольной точки (КТ);
- секреты не писать в чат, в репозиторий, в отчёты;
- адрес Google-аккаунта нигде не писать. Называть его «аккаунт Google, владеющий папкой Госзакупки»;
- рутины при установке не создавать: шаг 10 «Рутины» выполняется на этапе «первичная настройка» (корневой `README.md`, шаг 7.3, пункт e) по команде Тэндер Мэна, с подтверждением владельца на карточке.

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
- `old_registry` — реестр уже в репозитории; нужно подтверждение, что прежний Кузнец остановлен;
- `confirm_schedule` (время по Новосибирску, Asia/Novosibirsk).

Пока ждём ответа — шаги 4–5.

## 4. Развернуть файлы

```bash
git clone https://github.com/milordasceo/tender-conveyor.git /tmp/tender-conveyor
mkdir -p /home/box/gosplan/scripts
cp /tmp/tender-conveyor/kuznets/scripts/{gosplan_scanner.py,gosplan_lib.py,gosplan_drain.py,drain_start.sh,config.novosibirsk.yaml,config.example.yaml,README.md} /home/box/gosplan/scripts/
chmod 755 /home/box/gosplan/scripts/drain_start.sh
```

Соответствие путей — `deploy`. `/home/box/gosplan` уже есть — не затирать `scripts/state` и `.env`. Реестр кладётся на шаге 7.

КТ: `ls /home/box/gosplan/scripts` показывает 7 файлов.

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

Реестр сканера на боксе: `/home/box/gosplan/scripts/state/export_00cd167b09dc.json` (имя = sha1 строки `gosplan:Госзакупки/Сток`, первые 12 знаков). Перенесённая копия лежит в репозитории: `kuznets/state/` (вариант 0 ниже). Файл на боксе уже есть — не затирать.

Команда для варианта 0:

```bash
mkdir -p /home/box/gosplan/scripts/state
test -e /home/box/gosplan/scripts/state/export_00cd167b09dc.json || cp /tmp/tender-conveyor/kuznets/state/export_00cd167b09dc.json /home/box/gosplan/scripts/state/
```

Пустой реестр = первый прогон берёт все подходящие тендеры. Что это значит для того же «Сток»:

- папки, которые лежат в «Сток», сканер не копирует повторно: перед выгрузкой он делает `rclone lsf` и записывает такие номера в реестр (`dup: remote`). Запрос API на каждый такой номер всё равно идёт;
- папки, которые Фатима уже унесла из «Сток», выгрузятся снова. Это дубли для Фатимы.

Других способов засеять реестр в сканере нет. Варианты, по порядку предпочтения:

0. **Основной путь.** В репозитории лежит перенесённый реестр: `kuznets/state/export_*.json` (см. `kuznets/state/README.md`). Скопировать его в `/home/box/gosplan/scripts/state/` с тем же именем до первого запуска. Тогда добор (шаг 9) выгрузит очередь, дублей не будет. Остальные варианты ниже нужны только если этого файла нет или он устарел.

1. Владелец прислал старый реестр → положить файл в `/home/box/gosplan/scripts/state/` с тем же именем. Содержит только публичные номера тендеров.
2. Старого реестра нет, но прежний Кузнец выгружал в этот «Сток» → собрать реестр из номеров. Номера — имена папок в «Сток» и в папках, куда тендеры унесли следующие звенья (где они — спросить владельца или Тэндер Мэна; не угадывать). Список номеров по одному в строке — в `/tmp/known_numbers.txt`, затем:

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

Команды и ожидания — `verification` в `bot.yaml`. Идея: копия боевого реестра с 2 закупками в очереди во временном `GOSPLAN_STATE_DIR`, тестовый приёмник `gosplan:Госзакупки/_проверка_кузнеца`. Поиска нет, выгружаются ровно 2 папки. Боевой реестр и «Сток» не трогаются.

1. `md5sum` боевого реестра — запомнить.
2. `--dry-run` во временном state.
3. Тестовый реестр: `pending[:2]`, `remote` = тестовый, файл `/tmp/kuznets_check/export_0ad93d739bc6.json`.
4. `gosplan_scanner.py ... --remote 'gosplan:Госзакупки/_проверка_кузнеца' --limit 1` → в stderr «pending не пуст — поиск пропущен», `выгружено: 1`, код 3.
5. `gosplan_drain.py run` с `KUZNETS_REMOTE` тестовым и `DRAIN_INTERVAL=5` в переднем плане → выгружает последнюю, код 0.
6. `gosplan_drain.py status` → `pending: 0`, `state: done`.
7. `rclone lsf` тестовой папки → 2 папки номеров.
8. Уборка: `rclone purge 'gosplan:Госзакупки/_проверка_кузнеца'`, `rm -rf /tmp/kuznets_check`, `md5sum` боевого реестра — та же сумма.

КТ: всё по `expect`; папка проверки удалена; боевой реестр не изменился.

## 9. Запуск добора

`post_install` в `bot.yaml`:

```bash
cd /home/box/gosplan/scripts
../.venv/bin/python gosplan_drain.py status     # pending > 0
./drain_start.sh                                # «добор запущен, pid N, pending N»
sleep 150; ../.venv/bin/python gosplan_drain.py status
```

Добор — отсоединённый фоновый процесс. Выгружает по одной закупке примерно раз в 30 с. Второй копии не будет: блокировка `state/kuznets_run.lock`. systemd и cron на боксе нет: если процесс умрёт (перезагрузка бокса), его поднимет почасовая рутина.

КТ: `exported_last_hour` растёт, `drain_status.last_error` = `null`. Ошибка 401/`invalid_grant` — вернуться к шагу 6 (вход rclone).

## 10. Рутины

1. Создать обе рутины из `routines`: «Утренний скан госзакупок» (`0 7 * * *`) и «Почасовая проверка добора» (`0 * * * *`). Расписания `CRON_TZ=Asia/Novosibirsk 0 7 * * *` и `CRON_TZ=Asia/Novosibirsk 0 * * * *`; время утреннего скана — подтверждённое владельцем. Часовой пояс бокса не использовать.
2. Промт каждой — весь файл её `prompt_file`.
3. Включить. Перед этим — все `first_run.preconditions`.

КТ: обе рутины есть и включены.

## 11. Отчёт владельцу

Одно сообщение:

- бот «Кузнец» создан; какие плейсхолдеры id ещё не заменены;
- скрипты развёрнуты, версии python и rclone;
- rclone подключён к аккаунту Google, владеющему папкой «Госзакупки» (адрес не писать); раскладка «Сток»/«Бланки» найдена или создана;
- какой OAuth-клиент (готовый или новый); готовый (gosplan-rclone) опубликован, In production. Новый в режиме Testing — вход истечёт через 7 дней, нужна публикация;
- реестр: перенесённый из репозитория (выгружено N, в очереди N) или вариант 1/2/3;
- проверка: 2 тестовые папки выгружены и удалены, боевой реестр не изменился;
- добор запущен: pending N, примерно когда «Сток» догрузится (N × 30 с);
- рутины: имена, время, часовой пояс. Пока очередь не пуста, утренний поиск не идёт.

## 12. Последний шаг установки: отчёт Тэндер Мэну о готовности

SendToAgent `<id Тэндер Мэна>`: «Готов: Кузнец, мой id <id>, от владельца нужно: <список>». Список — невыполненные `owner_steps` (`oauth_client`, `google_cloud_terms`, `rclone_authorize` — пункт a; `old_registry`; `confirm_schedule` — пункт e) и коннектор Google Drive (`connectors`, пункт c); всё сделано — «ничего». Шаг, который упёрся в шаг владельца, доделать после нужного пункта этапа «первичная настройка» (корневой `README.md`, шаг 7.3) и подтвердить Тэндер Мэну.
