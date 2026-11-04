# Цифровой деканат будущего — V3

Конкурсный концепт. Неофициальный сервис. Все данные вымышлены.

Самостоятельное приложение: Python 3.13/FastAPI, SQLite, HTML/CSS/JavaScript ES modules.
Реализованы вход, серверные сессии, роли student/staff и собственные профили.
Расписание, оценки, заявки и уведомления ещё не реализованы. Конкурсный MVP не готов.

## Подготовка изолированной демонстрационной среды (PowerShell)

Команды выполняются из корня проекта. Новая база должна иметь новый путь;
существующие файлы не перезаписываются. Рабочую data/deanery.sqlite3 V2 не мигрировать
без отдельного решения. Для V3 по умолчанию старой базы недостаточно: health=503.

```powershell
# Только если окружение ещё не подготовлено:
python -m venv .venv
python -m pip --python .venv install -r requirements.txt

$env:MGIMOV_DB_PATH = '.tmp/demo-v3.sqlite3'
$env:MGIMOV_ORIGIN = 'http://127.0.0.1:8010'
& .\.venv\Scripts\python.exe -B -m backend.migrations init
& .\.venv\Scripts\python.exe -B -m backend.commands.seed_demo --db .tmp/demo-v3.sqlite3 --confirm-demo
& .\.venv\Scripts\python.exe -B -m uvicorn backend.app:app --host 127.0.0.1 --port 8010 --no-proxy-headers
```

Seed запускается в интерактивном терминале: оператор скрыто вводит и повторяет
три новых пароля (15–128 символов). Создаются student_a, student_b, staff_demo.
Пароли не выводятся и не записываются в документы; в базе только Argon2id.
Передать тестовые реквизиты пользователю отдельно, вне Git и публичных логов.
Команда отказывается работать с базой по умолчанию, с существующими users,
без явного --db/--confirm-demo или без интерактивного ввода. Startup не создаёт
аккаунты и не выполняет миграции. Отдельного HTTP seed/registration endpoint нет.

Открыть http://127.0.0.1:8010/; завершить сервер Ctrl+C. Не использовать file://.
Студенты имеют разные вымышленные профили и группы; сотрудник видит только
своё ФИО/должность. Общего каталога профилей нет. Вход по Enter, выход и повторный
вход поддерживаются. Профиль при обновлении запрашивается по серверной сессии.

## Конфигурация и безопасность

MGIMOV_DB_PATH — путь SQLite внутри проекта; MGIMOV_ORIGIN — точный origin без
пути, в нижнем регистре. .env не читается. Для другого локального порта измените
и origin, и --port. HTTP разрешён только на loopback. При публичном HTTPS origin
должен быть https://…: Secure и __Host- cookies включаются автоматически.
Публичное развёртывание в этом задании не выполняется; схему транспорта и доверие
к reverse proxy необходимо настраивать отдельно, не доверять произвольным forwarded headers.
Срок сессии по умолчанию 8 часов. Нет режима отключения авторизации.

API: GET /api/v1/auth/csrf, POST /api/v1/auth/login,
GET /api/v1/auth/me, GET /api/v1/me/profile, POST /api/v1/auth/logout.
Вход требует pre-login CSRF token из bootstrap и cookie + точный Origin;
выход требует CSRF header/cookie, связанные с серверной сессией.
Лимиты входа сохраняются в SQLite в окне 60 секунд: пара source/login — 5,
источник — 30 неудачных/незавершённых резервирований. Нет общего запрета по логину
для всех адресов и нет общего 15-минутного бюджета приложения. Успех возвращает
только свою резервацию. Повторный 429 не пишет в SQLite и не запускает Argon2.
Две проверки одновременно и одна на логин в одном процессе; перегрузка даёт 503.
Общий NAT и распределённые источники всё ещё требуют защиты proxy.
Сессионные токены случайны; в базе только SHA-256-хеши session/CSRF.
Профили выбираются сервером по сессии, query/GET body не выбирают владельца.
Frontend не хранит профиль/пароль/сессию в localStorage. Cookies HttpOnly для
сессии, SameSite=Strict, Path=/; CSRF-cookie доступна JS перед выходом.

## Миграции

```powershell
& .\.venv\Scripts\python.exe -B -m backend.migrations status
# Для отдельной существующей демобазы, после согласования и с новым backup:
New-Item -ItemType Directory -Force backups
& .\.venv\Scripts\python.exe -B -m backend.migrations apply --backup backups/before-v3.sqlite3
```

init создаёт новую базу и отказывается перезаписывать файл; apply существующей
базы требует новый backup. 0001_initial неизменна, V3 добавляет 0002_identity.
Startup не создаёт базу/схему; health сообщает готовность без деталей базы.
Состав схемы и ограничения описаны в docs/architecture.md.

## Проверки

```powershell
python -m pip --python .venv install -r requirements-test.txt
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js
Get-ChildItem frontend/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

Node.js 24, без npm-зависимостей. Тесты создают только временные базы внутри .tmp,
HTTP-тесты запускают собственные loopback-серверы на свободных портах и завершают их.
В ограниченной песочнице могут потребоваться разрешения локального запуска.
Hardening изменил health на лёгкую readiness (без integrity_check/проигрывания схемы).
Полная проверка: `python -B -m backend.commands.diagnose --db .tmp/demo-v3.sqlite3`.
Ограниченная явная очистка: `python -B -m backend.commands.cleanup_sessions --db .tmp/demo-v3.sqlite3 --limit 100 --confirm-cleanup`.
Использовать Python новой .venv; команды не выполняются автоматически.
Предупреждение Starlette/httpx сохраняется, зависимости не обновлялись.
Требования к будущему хостингу — [deployment-security.md](docs/deployment-security.md);
публичная конфигурация пока не проверена.
Результаты и ограничения браузерной проверки — docs/test-results.md.
Если ensurepip при создании venv не сработал, системный pip с --python .venv
может устанавливать пакеты в уже созданное окружение. Не подключать старое окружение Dashboard.

Документы: [архитектура](docs/architecture.md), [решения](docs/decisions.md),
[статус](docs/coordination/project-status.md), [проверки](docs/test-results.md).
