# Схема `bot.yaml`

Каждое звено кладёт в свою папку `<звено>/bot.yaml`. По нему звено пересоздаётся без догадок. Пример — `kuznets/bot.yaml`.

Правила:

- пути `from`, `prompt_file` — от корня репозитория; пути на боксе — абсолютные;
- значения секретов не писать никогда; только имя, назначение, как получить;
- другие боты — только по имени; id подставляются при создании;
- id папок Drive, адреса почты, токены не писать;
- тексты промтов — в отдельных файлах, файл целиком = текст для вставки.

## Ключи

| ключ | обяз. | что |
|---|---|---|
| `schema_version` | да | `1` |
| `link` | да | имя папки звена |
| `order_hint` | нет | место в конвейере словами, как его знает звено |
| `docs` | нет | `{readme, install, setup, format, ...}` — пути к описаниям звена |
| `bot.name` | да | имя бота |
| `bot.title` | да | заголовок |
| `bot.description` | да | одна-две фразы |
| `bot.prompt_file` | да | файл с системным промтом целиком |
| `bot.placeholders` | нет | `"<плейсхолдер>": {bot: <имя>, note: ...}` — что заменить в промте |
| `teammates[]` | нет | `{name, relation}` — с кем звено работает |
| `routines[]` | нет | `{name, cron, timezone, prompt_file, enable}`; `enable: last` — включать после проверки |
| `deploy[]` | нет | `{from, to}` — файлы из репозитория на бокс |
| `dependencies` | нет | `python: {min_version, venv, create, packages, install}`, `<инструмент>: {version, install, check}` |
| `config` | нет | `{file, current, owner}` — рабочий конфиг, текущие значения, кто меняет |
| `secrets[]` | нет | `{name, required, purpose, store, how}`; файл без секрета — `secret: false` |
| `connectors[]` | нет | `{name, required, account, purpose}`; аккаунт — описанием, не адресом |
| `drive_layout` | нет | `{account, root, folders, rule, rclone_paths}` |
| `owner_steps` | нет | `<id>: {why, say, options[], bot_does}` — то, что бот сделать не может; `say` — готовый текст владельцу |
| `verification` | да | `{state_dir, steps[{cmd, expect, duration}], cleanup[]}` — проверка без следов в боевых данных |
| `first_run` | нет | `{preconditions[], notes[]}` — что должно быть до включения рутины |

Новые ключи — можно. Тогда описать их здесь.
