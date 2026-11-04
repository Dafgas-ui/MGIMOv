# Цифровой деканат будущего — V2

Конкурсный концепт. Неофициальный сервис. Все данные вымышлены.

Самостоятельная основа для MGIMO AI Challenge 2026. Стек: Python 3.13, FastAPI,
SQLite, HTML/CSS/JavaScript ES modules. Один сервер выдаёт страницу и API.
Авторизация, расписание, успеваемость, заявки и уведомления на V2 не реализованы.

## Запуск в PowerShell из корня проекта

```powershell
python -m venv .venv
python -m pip --python .venv install -r requirements.txt
& .\.venv\Scripts\python.exe -B -m backend.migrations init
& .\.venv\Scripts\python.exe -B -m uvicorn backend.app:app --host 127.0.0.1 --port 8010 --no-proxy-headers
```

Страница: http://127.0.0.1:8010/; проверка готовности: http://127.0.0.1:8010/api/health.
Команда `init` выполняется один раз и отказывается перезаписывать существующую базу.
Если окружение уже подготовлено, достаточно последней команды. Остановка — Ctrl+C.
Если `venv` сообщает ошибку ensurepip, но создал интерпретатор, установка через
системный `python -m pip --python .venv ...` работает без pip внутри окружения.
Не использовать Python или site-packages исходного Dashboard.

По умолчанию база: `data/deanery.sqlite3`, относительно корня этого проекта.
`MGIMOV_DB_PATH` задаёт другой путь **внутри проекта**. `.env` не читается.
Вложенные каталоги для `init` создаются явно этой командой; при запуске сервера
таблицы, база и миграции не создаются. Без подготовленной схемы health возвращает
503 с общим сообщением; страница остаётся доступной. При готовой схеме — 200.
Не открывать index.html через file://: ES modules и API обслуживаются FastAPI.

## Миграции

```powershell
& .\.venv\Scripts\python.exe -B -m backend.migrations status
# Перед будущими изменениями существующей базы подготовить каталог backups:
New-Item -ItemType Directory -Force backups
& .\.venv\Scripts\python.exe -B -m backend.migrations apply --backup backups/before-next.sqlite3
```

Новый backup-файл не должен существовать. Менеджер проверяет схему и контрольные
суммы, выполняет SQL в транзакции, проверяет копию. Старые миграции Dashboard
не используются. Сейчас схема содержит только app_metadata и schema_migrations.

## Проверки

```powershell
python -m pip --python .venv install -r requirements-test.txt
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --test tests/dates.test.js tests/api.test.js
Get-ChildItem frontend/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

Node.js 24 использован для тестирования; npm-пакеты не требуются. Все тестовые базы
находятся в отдельных временных каталогах `.tmp/` внутри проекта. Реальный HTTP-тест
занимает свободный loopback-порт и завершает только созданный им процесс.
В ограниченной песочнице сетевые/поточные тесты могут требовать разрешения локального запуска.

Документы: docs/architecture.md, decisions.md, component-migration.md,
ai-development-log.md и test-results.md. Репозиторий локальный; публикация не выполнена.
