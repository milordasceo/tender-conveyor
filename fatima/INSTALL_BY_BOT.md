# Установка Фатимы ботом

Для бота, который создаёт Фатиму. Все значения — из `fatima/bot.yaml`. Кто такая Фатима и как работает — `fatima/README.md`.

Правила:

- шаги по порядку; следующий — только после контрольной точки (КТ);
- конфиг rclone (`~/.config/rclone/rclone.conf`) не читать, не показывать, не копировать;
- адрес Google-аккаунта нигде не писать. Называть его «аккаунт Google, владеющий папкой Госзакупки»;
- на Диске до шага 7 только чтение. Боевые «Бланки», «Цены» и счётчик при установке не менять;
- рутину включать последней и только по команде владельца.

## 1. Прочитать манифест

Прочитать `fatima/bot.yaml`, `fatima/bot/prompt.md`, `fatima/bot/routine_prompt.md`, `fatima/README.md`.

КТ: известны имя, промт, рутина, файлы, зависимости, раскладка Диска, шаги владельца.

## 2. Создать бота

1. Создать бота: `bot.name` = Фатима, `bot.title`, `bot.description`.
2. Системный промт — весь файл `bot.prompt_file` (`fatima/bot/prompt.md`), без правок. Плейсхолдеров нет.
3. Рутину пока не создавать.

КТ: бот «Фатима» существует, промт вставлен целиком.

## 3. Запросить у владельца сразу всё

Одним сообщением, тексты — из `owner_steps`:

- `rclone_ready` — нужен rclone remote `gosplan:` с доступом к Drive (настраивает Кузнец);
- `restricted_subfolders` — правило для «С ограничениями/Лицензии» и «/Опыт» (необязательно, по умолчанию — корень «С ограничениями»);
- разрешение создать и удалить тестовую папку `Госзакупки/_проверка_фатимы` (шаг 7);
- остановлена ли прежняя Фатима (две Фатимы на одни «Бланки» — двойной +1 в счётчике).

Пока ждём ответа — шаги 4–6.

## 4. Развернуть файлы

```bash
git clone https://github.com/milordasceo/tender-conveyor.git /tmp/tender-conveyor
mkdir -p /home/box/fatima/{scripts,examples,work,txt,backup,state}
cp /tmp/tender-conveyor/fatima/scripts/* /home/box/fatima/scripts/
cp -r /tmp/tender-conveyor/fatima/examples/0151100007126000034 /home/box/fatima/examples/
chmod 755 /home/box/fatima/scripts/*.py /home/box/fatima/scripts/selftest.sh
```

Соответствие путей — `deploy`. `/home/box/fatima/{work,txt,backup,state}` уже есть — не затирать.

КТ: `ls /home/box/fatima/scripts` — 8 файлов: `check_ready.py`, `counter.py`, `extract_text.py`, `render_md.py`, `README.md`, `selftest.sh`, `tender.schema.json`, `validate_tender.py`.

## 5. Зависимости

```bash
python3 --version                               # нужно >= 3.10
command -v soffice  || sudo apt-get install -y libreoffice-writer libreoffice-calc
command -v pdftotext || sudo apt-get install -y poppler-utils
command -v rclone   || (curl https://rclone.org/install.sh | sudo bash)
soffice --version; pdftotext -v; rclone version
bash /home/box/fatima/scripts/selftest.sh
```

КТ: последняя строка selftest — «selftest: всё прошло», код 0.

## 6. Доступ к Диску (только чтение)

Нужен rclone remote `gosplan:` с доступом к Drive. На новом аккаунте его настраивает Кузнец; Фатима его не создаёт.

```bash
rclone listremotes                               # есть gosplan:
rclone lsd gosplan:Госзакупки                    # Бланки, Цены, Сток
rclone lsd 'gosplan:Госзакупки/Цены/Новосибирск' # В городе, Загород, С ограничениями
rclone lsd 'gosplan:Госзакупки/Цены/Новосибирск/С ограничениями'   # Лицензии, Опыт
```

- нет `gosplan:` или 401/`invalid_grant` — стоп, владельцу текст `owner_steps.rclone_ready`;
- нет папок «Цены/Новосибирск/…» — создать `rclone mkdir 'gosplan:Госзакупки/Цены/Новосибирск/<папка>'` (только недостающие; это не удаление и не перезапись);
- «Бланки» и «Сток» не создавать и не трогать: их ведут Кузнец и загрузчик.

КТ: все папки из `drive_layout.folders` видны.

## 7. Проверка

Команды и ожидания — `verification` в `bot.yaml`:

1. `selftest.sh` — уже пройден на шаге 5.
2. Только чтение: `counter.py count` по `rclone lsf -R --dirs-only` «Цены/Новосибирск» — сверить с `rclone cat` счётчика, если он есть; `check_ready.py --status-file -` по первым папкам «Бланков».
3. С разрешения владельца — тестовая папка `gosplan:Госзакупки/_проверка_фатимы`: залить копию образца в `_проверка_фатимы/Бланки`, `rclone moveto` в `_проверка_фатимы/Цены/В городе`, `counter.py init` и `copyto` счётчика туда же.
4. Уборка: `rclone purge 'gosplan:Госзакупки/_проверка_фатимы'` — только эта тестовая папка; `rm -rf /tmp/fatima_check`.

Разрешения на тестовую папку нет — пункты 3–4 пропустить, в отчёте так и написать.

КТ: всё по `expect`; тестовая папка удалена; боевые «Бланки», «Цены» и счётчик не менялись (сверить `rclone lsf` до и после).

## 8. Рутина

1. Создать рутину из `routines`: «Разбор тендеров из Бланков», cron `0,30 8-19 * * 1-5`, часовой пояс Europe/Berlin, время гибкое ±15 минут.
2. Промт — весь файл `fatima/bot/routine_prompt.md`, дословно.
3. Создать выключенной (на паузе). Включить, только когда владелец скажет (`owner_steps.confirm_routine`) и выполнены `first_run.preconditions`.

КТ: рутина есть; включена или на паузе — по слову владельца.

## 9. Отчёт владельцу

Одно сообщение:

- бот «Фатима» создан, промт вставлен;
- скрипты в `/home/box/fatima/scripts`, selftest прошёл; версии python, LibreOffice, rclone;
- доступ `gosplan:` есть (аккаунт не называть); раскладка «Цены/Новосибирск» найдена или какие папки созданы;
- счётчик: есть на Диске (значения) или ещё нет (создастся при первом переносе);
- проверка на тестовой папке: пройдена и папка удалена / пропущена без разрешения;
- рутина: имя, расписание, включена или на паузе;
- открытые вопросы: подпапки «Лицензии»/«Опыт»; имя бота, который ищет цены.
