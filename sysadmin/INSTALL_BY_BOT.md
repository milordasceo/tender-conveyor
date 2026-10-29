# Установка Сисадмина ботом

Для бота, который создаёт Сисадмина. Все значения — из `sysadmin/bot.yaml`. Кто такой Сисадмин и как работает — `sysadmin/README.md`.

Правила:

- шаги по порядку; следующий — только после контрольной точки (КТ);
- конфиг rclone (`~/.config/rclone/rclone.conf`) не читать, не показывать, не копировать, не менять;
- адреса почты, id страниц и баз Notion, id папок Диска нигде не писать — ни в чат, ни в файлы;
- Диск — только чтение, на всех шагах;
- в Notion до шага 7 — только чтение, кроме создания страницы «К рассмотрению» и базы «Тендеры», если их нет;
- рутину не создавать, пока владелец не выбрал режим.

## 1. Прочитать манифест

Прочитать `sysadmin/bot.yaml`, `sysadmin/bot/prompt.md`, `sysadmin/bot/routine_prompt.md`, `sysadmin/README.md`, `sysadmin/examples/0151100007126000034/card.md`.

КТ: известны имя, промт, плейсхолдеры `<id Кузнеца>` и `<id Тэндер Мэна>`, предложенная рутина (статус — предложение), структура Notion (`notion_layout`), шаги владельца.

## 2. Создать бота

1. Создать бота: `bot.name` = Сисадмин, `bot.title`, `bot.description`.
2. Системный промт — весь файл `sysadmin/bot/prompt.md`; `<id Кузнеца>` заменить на id бота Кузнец, `<id Тэндер Мэна>` — на id бота Тэндер Мэн. Остальное без правок.
3. Подключить боту коннектор Notion (`connectors`). Рутину не создавать.

КТ: бот «Сисадмин» существует; в промте нет плейсхолдеров `<id …>` (`grep -c '<id ' ` по вставленному тексту — 0); последняя строка промта — ссылка на папку `sysadmin/`.

## 3. Запросить у владельца сразу всё

Одним сообщением, тексты — из `owner_steps`:

- `connect_notion` — показать карточку подключения Notion; владелец входит в своё рабочее пространство;
- `rclone_ready` — нужен rclone remote `gosplan:` с доступом к Drive (настраивает Кузнец);
- `test_card` — разрешение на тестовую страницу «_проверка_сисадмина» (шаг 7);
- `choose_mode` — по команде или каждый час.

Пока ждём ответа — шаги 4–5.

КТ: сообщение отправлено; ответы записаны по мере прихода.

## 4. Файлы на боксе

```bash
rm -rf /tmp/tender-conveyor && git clone https://github.com/milordasceo/tender-conveyor.git /tmp/tender-conveyor
mkdir -p /home/box/sysadmin/work /home/box/sysadmin/scripts /home/box/sysadmin/examples /home/box/sysadmin/state/goal_sent
[ -f /home/box/sysadmin/state/daily_goal ] || echo 10 > /home/box/sysadmin/state/daily_goal
install -m 755 /tmp/tender-conveyor/sysadmin/scripts/notion_card.py /home/box/sysadmin/scripts/notion_card.py
cp -r /tmp/tender-conveyor/sysadmin/examples/0151100007126000034 /home/box/sysadmin/examples/
```

`/home/box/sysadmin/work` и `state` уже есть — не затирать.

КТ: `cat /home/box/sysadmin/state/daily_goal` — число (10, если цель не менялась); `ls /home/box/sysadmin/examples/0151100007126000034/input` — `tender.json`, `tender.md`, `цены.md`; `test -x /home/box/sysadmin/scripts/notion_card.py && echo ok` — `ok`.

## 5. Зависимости

```bash
python3 --version                                # нужно >= 3.10
command -v rclone || (curl https://rclone.org/install.sh | sudo bash)
rclone version                                   # проверено на 1.75.2
python3 /home/box/sysadmin/scripts/notion_card.py /home/box/sysadmin/examples/0151100007126000034/input --summary
```

КТ: python3 >= 3.10; `rclone version` печатает версию; скрипт печатает «прибыль 25 317,59 ₽ (вариант А), расходы 15 467,81 ₽, НМЦК 40 785,40 ₽» и «откуда: «Промышленная Площадка», г. Новосибирск, ул. Николая Островского, 49 к.1…».

## 6. Доступ к Диску (только чтение)

Нужен rclone remote `gosplan:` с доступом к Drive. Его настраивает Кузнец; Сисадмин его не создаёт.

```bash
rclone listremotes                                         # есть gosplan:
rclone lsf 'gosplan:Госзакупки'                            # К рассмотрению/
rclone lsf --dirs-only 'gosplan:Госзакупки/К рассмотрению' # номера тендеров или пусто
N=$(rclone lsf --dirs-only 'gosplan:Госзакупки/К рассмотрению' | head -1 | tr -d /)
[ -n "$N" ] && rclone copy "gosplan:Госзакупки/К рассмотрению/$N" "/tmp/sysadmin_check/$N" --include 'tender.*' --include 'цены.md' \
  && python3 /home/box/sysadmin/scripts/notion_card.py "/tmp/sysadmin_check/$N" --summary
```

- нет `gosplan:` или 401 / `invalid_grant` — стоп, владельцу текст `owner_steps.rclone_ready`;
- нет «К рассмотрению» — не создавать, сообщить владельцу: папку наполняют предыдущие звенья.

КТ: виден `К рассмотрению/`; записано, сколько там тендеров; сводка по одному живому тендеру напечатана без ошибок (или папка пуста).

## 7. Notion

Нужно: владелец подключил Notion (`owner_steps.connect_notion`).

1. `search` «К рассмотрению». Есть страница — `fetch`, найти внутри базу «Тендеры», `fetch` базы, сверить свойства и раскладку с `notion_layout`.
2. Нет страницы — создать в корне рабочего пространства страницу «К рассмотрению», значок 📋. Нет базы — создать в ней полностраничную базу «Тендеры» (свойство-заголовок «Номер тендера»).
3. Свойства: один вызов `update_data_source` со `statements` из `notion_layout.ddl` (только недостающие; у существующих select — перечислять все старые варианты).
4. Раскладка: **отдельный** вызов `update_data_source` с `page_layout`: `main` = title с `pinnedProperties` из `notion_layout.page_layout_header`, затем editor и discussions.
5. С разрешения `owner_steps.test_card`: создать в корне страницу «_проверка_сисадмина», тело — `examples/0151100007126000034/card.md`; `fetch`; затем убрать её в корзину. Разрешения нет — пропустить, в отчёте так и написать.

КТ: `fetch` базы «Тендеры» показывает 12 свойств в порядке `notion_layout.properties`, «Категория» с тремя вариантами (зелёный / оранжевый / красный), «Подача до» — дата; раскладка — шапка в порядке `page_layout_header`; тестовая страница удалена (или шаг пропущен); строк в «Тендеры» не прибавилось.

## 8. Проверка целиком

`verification` в `bot.yaml`: шаги 1–3 уже сделаны на шагах 5–6, шаги 4–5 — на шаге 7. Уборка: `rm -rf /tmp/sysadmin_check`.

КТ: все шаги `verification` с ожидаемым результатом; `/tmp/sysadmin_check` удалена; Диск не менялся.

## 9. Режим работы

По ответу владельца на `owner_steps.choose_mode`:

- **по команде** — рутину не создавать. Владелец пишет «перенеси тендеры», Сисадмин делает шаги `bot/routine_prompt.md`;
- **каждый час** — создать рутину из `routines`: «Перенос тендеров в Notion», расписание `CRON_TZ=Europe/Madrid 0 * * * *`, время гибкое ±15 минут, промт — весь файл `sysadmin/bot/routine_prompt.md`, дословно. Включить после `first_run.preconditions`.

Ответа нет — ничего не создавать, оставить режим «по команде» и напомнить в отчёте.

КТ: рутины нет (по команде) или рутина есть с расписанием `0 * * * *` Europe/Madrid, гибко ±15 минут.

## 10. Отчёт владельцу

Одно сообщение:

- бот «Сисадмин» создан, промт вставлен, `<id Кузнеца>` и `<id Тэндер Мэна>` подставлены; цель дня — 10;
- `/home/box/sysadmin` создан, скрипт на образце даёт 25 317,59 ₽ / 15 467,81 ₽; версии python, rclone;
- доступ `gosplan:` есть (аккаунт не называть); сколько тендеров сейчас в «К рассмотрению»;
- Notion: страница «К рассмотрению» и база «Тендеры» найдены или созданы, свойства и раскладка сверены (id не писать);
- тестовая страница: создана и удалена / пропущена без разрешения;
- режим: по команде или рутина каждый час.
