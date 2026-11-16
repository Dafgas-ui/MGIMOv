# Проверки V2

Дата: 4 ноября 2026, МСК. Среда: Windows, CPython 3.13, Node.js 24.21.0.
Зависимости установлены в собственную .venv; точные версии — constraints.txt.

## Завершённые проверки

- Python unittest: 11/11, без пропусков.
- Node test runner: 6/6, без пропусков.
- Python AST: backend; дополнительная проверка всего набора перед коммитом.
- node --check: все frontend JavaScript-модули.
- Реальный Uvicorn на отдельном loopback-порту: GET /api/health = 200,
  GET / = 200. Созданный тестом сервер завершён.
- Отсутствующая, повреждённая и неуправляемая база: health = 503;
  отсутствующая база не создаётся приложением.
- Все явно опубликованные assets загружаются, JavaScript имеет корректный MIME.
- /data, .env, backend и старые API-маршруты не опубликованы.
- Project-local конфигурация, отклонение внешнего пути, игнорирование старого env.
- SQLite: foreign_keys, read-only connection, commit/rollback.
- Миграции: init/status, повторный init без перезаписи, repeat/no-op,
  checksum, обязательный backup, проверка копии, rollback ошибочного SQL,
  запрет изменения истории из SQL-миграции.
- Argon2id: уникальная соль, проверка пароля, отрицательные случаи и границы.
- Даты: високосность, невозможные даты, границы года, неделя с понедельника,
  разные дни, касающиеся интервалы, окончание 24:00.
- API-клиент: локальный origin, no-store, redirect:error, контролируемый отказ.
- Четыре использованных исходных файла Dashboard: SHA-256 совпадают с началом переноса.

Первый прогон выявил незакрытые SQLite connections в тесте и Windows launcher/log
cleanup. После исправления полный прогон прошёл. В песочнице TestClient зависал;
полный успешный прогон выполнен с разрешением локального запуска вне песочницы.
Starlette выдаёт предупреждение об устаревающей поддержке httpx TestClient;
оно не мешает тестам, но обновление тестового клиента нужно оценить отдельно.

## Проверка первого Git-набора

Перед коммитом: просмотр списка, git diff --cached --check, поиск нежелательных
имён/секретоподобных значений. База, .venv, .tmp, .env, backup и логи исключены.
Сканирование шаблонов не заменяет полный независимый аудит безопасности.

## Не проверено

Визуальный запуск в настоящем браузере, размеры 360 px и реальное выполнение
DOM-модуля app.js в браузере. Нет проверки публичного HTTPS, доступности из России,
нагрузки, уязвимостей и лицензий всех зависимостей. Авторизация и конкурсные модули
не реализованы и не тестировались. Стенд не опубликован.

## V3 — проверки Sol, 4 ноября 2026 (МСК)

База: HEAD 28033fcc1133c74b1c6f4ba2b4c7203bbdb7b590 + незакоммиченные изменения V3.
Исполнитель — Sol, не независимый чат приёмки Astra.

- `.venv/Scripts/python.exe -B -m unittest discover -s tests -v`: **31/31**, exit 0.
  Это 11 регрессионных V2 + 20 V3. Без пропусков. Реальные временные SQLite внутри .tmp.
- `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js`:
  **12/12**, exit 0 (6 старых + 6 состояния кабинета).
- `node --check` для всех frontend JS: exit 0. Python AST для backend/tests: успешно.
- HTTP: тестовый Uvicorn на свободных loopback-портах; три синтетических аккаунта,
  login/profile=200, logout=204, повторное чтение после logout=401; health/page=200.
  Серверы, созданные автоматическими тестами, завершены.
- Проверены неизвестный/неактивный пользователь, неверный пароль, dummy verification,
  аноним/невалидная/истёкшая/отозванная сессия; ротация входа; CSRF login/logout,
  exact Host/Origin, JSON size/type, mass assignment и безопасные validation errors.
- A/B читают только свои разные профили; staff видит только своё ФИО/должность.
  Подмена query/body/path/header не выбирает другого владельца. Учебные ресурсы V4–V7
  не реализованы, их изоляция не заявляется как проверенная.
- Проверены upgrade V2→V3 с сохранением метки, backup, repeat/no-op и запрет повторного seed.
- HTTPS cookies проверены TestClient: Secure, HttpOnly session, SameSite=strict,
  Path=/, без Domain; HTTP non-loopback config отклоняется. Реальный TLS/прокси не проверены.
- JS: повторный вход/выход, double-submit, поздний ответ после invalidation,
  401/403/503, timeout модели, восстановление после failed logout и смены аккаунта.
  Это проверки state-controller, а не исполнение DOM в браузере.

Предварительные сообщения единственного целевого security_reviewer указали на UnicodeError (возможный 500),
повреждённые локализованные строки и failed-logout recovery. Исправлены Sol;
добавлены целевые тесты и выполнен итоговый полный набор выше. Первое формирование
surrogate-запроса было отклонено HTTPX до отправки; тест исправлен на escaped JSON,
после чего серверный ответ 422 подтверждён.

Попытка браузерной проверки: IAB webview attach timeout, затем список браузеров пуст;
резервное native-окно не удалось надёжно выбрать. UI-действия входа не выполнялись.
Поэтому 360 px/широкий viewport, отсутствие горизонтального переполнения, Enter,
клавиатурный фокус и реальное DOM-восстановление сессии V3 не объявляются проверенными.
Созданная отдельная browser-fixture .tmp/browser-v3.sqlite3 отключена (active=0,
сессии отозваны); default data/deanery.sqlite3 не затрагивалась.
Независимая динамическая приёмка V3 ещё не проведена.

SHA-256 до/после: рабочая база V2, AGENTS.md, первая миграция, Skills и конфигурации
субагентов без изменений. Исходный Dashboard не использовался. Нет новых зависимостей.
Предупреждения health/Starlette-httpx сохранены. Публичный доступ/TLS, нагрузка,
полная безопасность и конкурсное соответствие не подтверждены.

Ограничение reviewer: завершённый отчёт не получен (вызов оставался pending_init
и был остановлен); получены только предварительные сообщения. Полный независимый
статический аудит не заявляется выполненным. Дополнительных агентов не запускали.
При финальной проверке чтением порт 8023 и PID временного browser-сервера
не обнаружены, exit 0. Временная browser-база отключена, файл сохранён в .tmp.

## V3 Security Hardening — Sol, 4 ноября 2026 (МСК)

Источник новых требований — задание пользователя с выводами независимого Security
Review Astra Medium. Сам полный отчёт в проекте не найден; Sol не выдаёт это за
повторный независимый аудит. Пользователь также подтвердил независимую приёмку
V3 PASS WITH WARNINGS: 31 Python/12 JS и основные browser-сценарии; это отдельный
предыдущий результат, не приведённый ниже прогон Sol.

База HEAD: 28033fcc1133c74b1c6f4ba2b4c7203bbdb7b590 + ранее созданные V3 и новые
незакоммиченные hardening-изменения. Старые изменения не сбрасывались.

Команды и наблюдения:

- Целевой первый прогон: `.venv/Scripts/python.exe -B -m unittest tests.test_hardening -v`
  — 15/15, exit 0; `node --test tests/account-state.test.js` — 8/8, exit 0.
- После добавления forwarded-header и bounded-counter-cleanup регрессий полный
  `.venv/Scripts/python.exe -B -m unittest discover -s tests -v` — **48/48, exit 0**
  (31 исходный V2/V3 + 17 hardening), без пропусков.
- `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js`
  — **14/14, exit 0**, без пропусков. `node --check` всех frontend JS — exit 0.
- Реальные Uvicorn/HTTP проверки выполнены полным Python-набором на временных
  project-local SQLite и собственных loopback-портах. Login/profile/health=200,
  logout=204, доступ после выхода=401; серверы тестов завершены.
- Все проверки базы использовали .tmp; рабочая SQLite не подключалась для тестов.
  Управляемые часы: исчерпание pair/source budgets, независимый легитимный вход,
  отсутствие cross-source account lockout, сохранение чужих failed counters при success,
  истечение окна и сохранность счётчиков между экземплярами limiter.
- Контролируемая конкуренция: 3 worker threads, 7 reserve requests на pair budget 5;
  ровно 5 допущено, 2 получили 429. Проверены per-account/global in-flight caps.
  Поддельный forwarded-header клиента не сбрасывает source budget.
- Повторный 429 не вызывает Argon2 и write connection. Invalid logout token не
  открывает connection; неверный CSRF не открывает writer. Writer-lock на временной
  SQLite: такие отказы работают; правильный login/logout дают общий 503 при занятой
  базе и работают после освобождения. Транзакционная повторная проверка не снята.
- Два одновременно независимых TestClient A/B: logout A не отзывает B; A получает
  401, B продолжает видеть только свой профиль.
- Health не вызывает manager.status/inspect (spies запрещали вызов); ожидаемый 200,
  неверный checksum — 503. Старые регрессии missing/corrupt/unmanaged также прошли.
- Полная read-only diagnose CLI: корректная временная база exit 0, испорченный
  тестовый файл exit 1. Полная диагностика не опубликована по HTTP (404).
- Ограниченная очистка удаляет только expired/old-revoked строки, по batch limit;
  сохраняет live/recent-revoked и исходный expiry. Некорректный limit отклоняется.
  Старые auth counters очищаются ограниченной пачкой без изменения текущих резервов.
- Малый ASGI slow-trickle тест: общий body deadline не продлевается каждым chunk,
  ответ 408, обработчик приложения не вызван. Это не сетевой stress/connection тест.
- JS выполняет реальный account.js в минимальной DOM-fixture: ввод пароля переживает
  минутный poll и ручную проверку; явный submit получает введённый пароль и очищает поле.
  Это не браузерная проверка и не доказательство видимого фокуса/верстки.

Остаточный риск: общий NAT может исчерпать source budget; распределённые реальные IP
получают разные source quotas. Они всё ещё ограничены bounded verification в одном
процессе, но периметр не заменён. 503 при занятой verification capacity может затронуть
легитимный запрос. Старые окна 900 секунд/global lockout удалены, не гарантируется
невозможность любого DoS. Полные privacy/security/нагрузка/TLS/proxy не проверены.
Starlette/httpx предупреждение осталось; зависимости не обновлялись.
[Требования будущего периметра](deployment-security.md).

## V3 commit gate и V4 — Sol, 4 ноября 2026 (МСК)

Перед разрешённым коммитом V3 повторно выполнены 48/48 Python и 14/14 JS, exit 0.
Локальный V3 commit `be438957e3aed72002362432420b3ed8d69ea253` создан после проверки staged-состава и шаблонов секретов.
V4 проверяется как незакоммиченное рабочее дерево поверх него. Это проверки Sol,
не независимая приёмка Astra и не повторный полный Security Review. Субагентов нет.

Команды:

- `.venv/Scripts/python.exe -B -m unittest tests.test_schedule -q`: сначала 8/8,
  exit 0; один исходный сбой теста исправлен (нельзя отзывать real-clock сессию
  после перевода часов фикстуры назад; cookies очищаются перед заморозкой времени).
- Финальный `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`:
  **57/57 Python, exit 0**, включая 9 новых V4 тестов и 48 регрессий.
- `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js tests/schedule.test.js`:
  **18/18, exit 0** (4 новых V4 + 14 регрессий). `node --check` всех frontend JS: exit 0.
- Проверены today/week, московская полночь, границы недели/года и високосность,
  разные группы двух независимых клиентов, аноним=401, staff=403, подмена
  query/body/path/expected user не выбирает другую группу, недопустимые даты=422.
- Отмена, перенос со старым маркером и промежуточными датами, смена teacher/room,
  история before/after, stale version и FK/interval rollback, пустые дни/недели,
  отсутствие public write API, запрет повторного seed и локальная change CLI.
- Реальный Uvicorn/HTTP V4 на временной SQLite: два независимых клиента получают
  разные группы; локальное изменение занятия A видно в следующем GET, B не меняется.
  Login/schedule=200, anonymous=401. Собственный HTTP-сервер теста завершён.
- JS: выбор today/week, навигация дат, year boundary, Moscow today, ошибки API,
  staff/hidden, игнорирование stale response; реальный renderer в DOM-fixture
  показывает пустые дни, отмену, перенос, историю текстом (не парсит HTML).

### Браузер V4 (реальный IAB, отдельная .tmp/v4-browser.sqlite3)

В этом задании браузер подключился. Проверены 360×800 и 1280×900.
Измерение DOM: scrollWidth 345 при innerWidth 360; 1265 при innerWidth 1280 —
горизонтального переполнения в проверенных состояниях нет. Вход A → день со сменой
аудитории → неделя (7 дней, видимая отмена и перенос) → пустая следующая неделя →
возврат к сегодня → выход → вход B с другой группой/временем/дисциплиной → reload
восстанавливает B и его расписание → выход. Размер override сброшен, вкладка закрыта.
Снимки: `.tmp/v4-mobile.png`, `.tmp/v4-wide.png` (не в Git).
После проверки временные users отключены, сессии отозваны; сервер остановлен.

Это ограниченная browser-проверка, не полный accessibility/визуальный аудит.
Browser timeout/offline/полная клавиатура/все viewport не проверены. API-error/stale
проверены автоматическими JS-тестами. Настоящий TLS/proxy, публичный доступ,
нагрузка, независимый повторный аудит и лицензии пока не подтверждены.
Сохраняются остаточные NAT/распределённые/IP/concurrency риски V3 и предупреждение
Starlette/httpx. Рабочая база не мигрировалась и не использовалась для тестов.


## V5 — проверки разработчика Sol

4 ноября 2026 (МСК). База: V4 commit `313ad9d11f2f068867a4fa881ede0dd916e30c77`
+ рабочее дерево V5. Независимая приёмка V4/V5 не проводилась этим чатом.
Перед commit V4 повторно 57 Python/18 JS, exit 0; проверены 25 файлов, staged и secret patterns.
Коммит локальный, без runtime/баз/логов/паролей и без push.

### Финальные автоматические проверки

- `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`:
  **70/70, exit 0**, без пропусков (13 новых V5 + 57 регрессий).
- `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js tests/schedule.test.js tests/academics.test.js`:
  **23/23, exit 0**, без пропусков (5 новых V5 + 18 регрессий).
- Python AST backend/tests и `node --check` всех frontend/js: exit 0.
- Все тестовые SQLite — временные внутри .tmp; template/case и изолированные HTTP.
  Никаких записей в рабочую SQLite, установки библиотек и субагентов.
  Starlette/httpx выдаёт известное deprecation warning, не ошибку теста.

| Требование V5 (локальные ID по заданию пользователя) | Проверка / доказательство | Результат |
|---|---|---|
| V5-DATA: семестры, план и персональные оценки | tests/test_academics.py: personal_gradebook, constraints, migration; реальные SQLite/FK/триггеры | Подтверждено для фикстур; не официальный вузовский регламент |
| V5-OWNER: A/B, аноним/staff, подмена query/JSON/path/header | two_students, anonymous_staff_idor; HTTP A/B | Подтверждено: 200 свои, 401 аноним, 403 staff/ожидаемый чужой user, 422 query/body, 404 чужой path |
| V5-READ: запрет веб-изменения | POST/PUT/PATCH/DELETE четырёх маршрутов | 405 с валидной сессией/origin; записей оценок нет |
| V5-RULES: успех/неуспех/пересдача/неявка | retake, credit_failure, missing_future, no_data, outside_semester | Последняя попытка; общий счётчик 4; future не долг; no data percent=null |
| V5-DEBT: явный срок/проведение | missing_future_not_held_and_explicit_deadline | Нет оценки без срока — не долг; completed + прошедший deadline — долг; not_held — не долг |
| V5-HISTORY: локальная запись и целостность | local_validation, constraints, seed_and_command; subprocess CLI | Валидация форм/дат/числа попыток, rollback, append-only, отказ после успеха, нет повторного seed |
| V5-MIGRATE: пустая/существующая V4-база | все fixtures init; migration_existing_v4_database | 0004 applied, backup создан, маркер V4 сохранён, FK check пуст, повторный apply без изменений |
| V5-UI: состояния, история и безопасный текст | tests/academics.test.js | memory state, logout/staff/identity/stale/401/403/503/timeout/invalid JSON shape; DOM-fixture renderer |
| V5-BROWSER: мобильный/desktop и реальные действия | IAB 360×800/1280×900 ниже | Ограниченная проверка подтверждена; не полная доступность |

### Реальные HTTP V5

`test_real_http_personal_results_retake_and_method_denied` запускает собственный Uvicorn
на свободном loopback-порту, временная файловая SQLite, два независимых httpx клиента.
Без сессии gradebook=401. Вход A/B=200; A completed=2, B одна задолженность.
Локальная пересдача B 2→4 убирает его долг, A остаётся без изменений.
Подмена student_id=422, POST результата=405. Сервер завершается finally;
логи проверяются на отсутствие сгенерированных паролей. V2–V4 HTTP-регрессии тоже пройдены.
После финального прогона часы собственного V5 HTTP-сервера зафиксированы на дату
фикстуры, чтобы тест не зависел от года запуска; повторно 13/13 V5 Python, exit 0.

### Реальный браузер V5

IAB, `.tmp/v5-browser.sqlite3`, только синтетические данные, loopback 8045.
360×800 и 1280×900: A прогресс 50% (2/4), предстоящий диффзачёт, два семестра,
passed/not_held; logout удаляет расписание и зачётку. B имеет другую программу,
дисциплины/оценки, 25% (1/4), одну задолженность и невнесённый результат.
Через настоящий локальный record_result CLI добавлена пересдача B: после кнопки
«Обновить успеваемость» 50% (2/4), долгов нет, обе попытки видны; reload сохраняет
аккаунт и серверные результаты. Новая дата не подменяется frontend.
DOM измерения: width=360 / scrollWidth=345, width=1280 / scrollWidth=1265,
переполнения в проверенных состояниях нет. Enter на summary сворачивает семестр;
активный элемент SUMMARY, outline solid. Первоначальный поиск summary по role=button
не сработал в Playwright (AX называл его кнопкой); найден по видимому тексту,
повторная проверка успешна. Это ошибка выбора локатора, не дефект приложения.
После остановки тестового сервера кнопка обновления даёт понятную ошибку соединения,
старые оценки удалены из DOM. Скриншоты .tmp/v5-mobile.png и .tmp/v5-wide.png не в Git.
Viewport сброшен, вкладка закрыта, server PID 43480/порт 8045 завершены,
временные пользователи отключены и сессии отозваны.

Браузерный прогон выполнен до последнего усиления SQL-триггера порядка/успеха попыток
и server-проверок монотонности recorded_at/приоритета отмены; UI после него не менялся. Финальные
автоматические и HTTP-тесты выше проверяют актуальную схему и сервис.
Блокирующих функциональных дефектов в выполненных сценариях не обнаружено.
В разработке усилены защита истории на уровне SQLite и временная последовательность записи.

### Ограничения

Критерии deanery-acceptance-test использованы разработчиком; это не независимый PASS.
Полная клавиатура/порядок focus/скринридеры/контраст и визуальная QA, браузерный timeout,
настоящая offline-эмуляция, реальные мобильные устройства/другие браузеры не проверялись.
Ошибка соединения проверена остановкой сервера; JS timeout проверен с mock request,
DOM renderer — с минимальной fixture, не настоящим браузером.
Отдельное сессионное окно, назначение пересдачи на новую дату, staff editor и исправление
успешного результата вне V5. Совместимость с реальным университетским регламентом и
официальное конкурсное соответствие не установлены. Нагрузка/большие объёмы истории,
TLS/proxy/perimeter/backup recovery/лицензии/полный Security Review не проверены.
Сохраняются NAT/distributed/source/SQLite single-writer риски V3 и Starlette/httpx warning.
V5 готов к независимой функциональной приёмке; публичная готовность не заявляется.


## V6 — проверки разработчика Sol

4 ноября 2026 (МСК), база `31a8ed8f57e80577caca9e8fd91ee3465092f065`
+ рабочее дерево V6. Перед локальным commit V5 повторно 70 Python/23 JS, exit 0;
проверены 24 файла, staged/selected secret patterns, runtime/базы/логи не включены.
Независимые приёмки V4/V5/V6 не выполнялись данным чатом и не присваиваются Sol.

### Автоматические проверки

- `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`: **90/90 Python,
  exit 0**, без пропусков (20 новых V6 + 70 регрессий V2–V5).
- `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js tests/schedule.test.js tests/academics.test.js tests/requests.test.js`:
  **29/29 JS, exit 0**, без пропусков (6 новых + 23 регрессии).
- Python AST backend/tests и `node --check` всех frontend JS: exit 0.
- Первый полный Python-прогон: 88 успешных, 2 сбоя старых ожиданий. V5 upgrade-тест
  предполагал последнюю миграцию 0004 вместо новой 0005; V3-тест ожидал 404 у ещё не
  существовавшего staff/requests вместо теперь корректного 403 студенту. Assertions
  обновлены под согласованную V6-функциональность, повторный полный прогон успешен.
- Все SQLite — временные файлы в .tmp, не рабочая база. Starlette/httpx warning
  сохраняется, зависимости не менялись. Mocks используются для ошибки history и
  стоимости Argon при создании TestClient app; реальные SQLite/auth/CSRF проходят.

| Требование V6 (ID локальные по заданию пользователя) | Доказательство | Результат / граница |
|---|---|---|
| V6-CREATE: три типа, поля и server owner | tests/test_requests.py: create_own_list_details_and_server_author, validation | 201; все три типа, owner/faculty/actor из сервера; не официальные документы |
| V6-READ: свои списки/детали и изоляция | two_students_idor, anonymous_student_admin | A/B отдельны; чужой ID read/cancel=404, аноним=401, student→staff=403 |
| V6-STAFF: ограниченные полномочия | staff_scope, staff_guard, mutation_rechecks_live_identity | Пустая очередь без scope; foreign/revoked scope=404; отключение staff до writer=401 |
| V6-STATUS: обработка/решение/отмена | status_machine, cancel_only_submitted | submitted→processing→approved/rejected, submitted→cancelled; terminal/stale=409 |
| V6-HISTORY: атомарность и автор | history_failure, concurrent_two_staff | Искусственный сбой history=503 с rollback; UPDATE/DELETE истории запрещены; authors/versions сохранены |
| V6-CSRF: mutations | csrf_origin_content_type_and_staff_no_store, staff_guard | Missing/wrong token и foreign origin=403, дубли headers=400, non-JSON=415, body overflow=413 |
| V6-RETRY: повторы и лимиты | repeat_same_payload, concurrent_same_create, persistent_create_limit, daily_quota | Один owner/key → одна строка; иной payload=409; 5/600s, 20/86400s, отменённые учитываются |
| V6-PAGES: пустые и длинные списки | empty_and_pagination | empty, 20+1 записи, offset/next_offset, следующий день квоты |
| V6-MIGRATE | migration_existing_v5_preserves_data и fixtures init | Пустая новая схема и upgrade V5 с backup/сохранённым маркером, FK check пуст |
| V6-UI: текст/ошибки/identity/двойной клик | tests/requests.test.js | DOM-fixture renderer; memory state/timeout/late/roles/версии/идемпотентный retry |

### Реальные HTTP и браузер

`test_real_http_two_students_staff_and_decision`: собственный Uvicorn на свободном
loopback-порту, отдельная временная SQLite и три независимых httpx клиента.
A создаёт, повторяет тем же ключом (201/200); B получает 404 на заявку A;
A запрещён staff queue (403), сотрудник переводит в processing/approved (200),
студент получает итог и 3 события. Staff ответы no-store. Аноним=401.
Сервер завершается finally; лог проверен на отсутствие сгенерированных паролей.
V2–V5 реальные HTTP-регрессии также пройдены.

IAB, `.tmp/v6-browser.sqlite3`, loopback 8046, только вымышленные данные.
360×800: A создаёт справку, заполненные поля сохраняются после «Проверить вход»,
содержимое `<b>…</b>` показывается буквальным текстом; отмена даёт version=2 и историю.
Logout очищает учебные данные и обращения. B видит другой список, отказ с причиной
и автором. Reload сохраняет сессию/серверные заявки. Staff видит свою факультетную
очередь, переводит новую заявку B в обработку и затем одобряет с комментарием;
B после входа получает решение и авторов/время/историю. Student/staff формы проверены
при 360 px, одобрение и детали также при 1280×900. scrollWidth 345/1265 при width
360/1280 — переполнения в проверенных состояниях нет. Enter по «Перейти к обращениям»
перемещает к разделу; проверена не вся клавиатура/доступность.
После остановки сервера «Обновить обращения» показывает безопасную ошибку и удаляет
старые карточки. Скриншоты .tmp/v6-mobile.png, .tmp/v6-wide.png не включены в Git.
Viewport сброшен, вкладка закрыта, PID 23728/порт 8046 завершены;
временные users отключены, sessions отозваны.

### Целевые регрессии безопасности V6 (восемь направлений навыка)

Проверены изменённые маршруты/общие guards и связанные регрессии. Это проверка
разработчика по deanery-security-review, не независимый полный аудит или доказательство
безопасности всей системы. Динамические операции разрешены заданием только во временной среде.

| Направление | Проверенные участки / доказательства | Граница |
|---|---|---|
| Авторизация/сессии | auth/service.py resolve; requests/service.py identity/preflight + повтор под writer; тест disable-before-write | Модель токенов/TTL не менялась, регрессии V3 пройдены |
| Пароли/credentials | passwords.py и login не менялись; V3 Argon/hash/limits тесты пройдены, selected secret patterns | Не полный аудит зависимостей или recovery |
| Изоляция A/B | read_requests, authorized_request SQL; HTTP A/B read/cancel/queue | Проверена новая поверхность заявок, будущие уведомления вне этапа |
| IDOR | owner predicate/EXISTS scopes; query/JSON/client-owner/role отрицательные тесты | UUID сам по себе не считается защитой |
| Полномочия | request_staff_scopes, identity(role), TRANSITIONS; no-scope/foreign/revoked scope | Веб-редактор scopes и staff доступ к оценкам отсутствуют |
| CSRF/cookies/API | staff prefix IdentityGuard + validation, verify_csrf в mutation; Origin/JSON/body/no-store тесты | TLS/reverse proxy не проверены; параметры cookies V3 сохранены |
| Утечки | public_request/details исключают key/hash/owner ID/credentials; textContent renderer; generic 422/503 и логи HTTP | Staff видит имя/группу только в контексте разрешённого обращения |
| Регрессии | 90 Python/29 JS, реальные SQLite/HTTP; mutation history rollback и два сотрудника | Не нагрузочная приёмка и не публичная инфраструктура |

Подтверждённых нарушений изоляции/CSRF или блокирующих функциональных ошибок в
выполненных сценариях не обнаружено. Исправлено стирание незавершённой формы при
refresh identity: теперь она сохраняется только для того же подтверждённого владельца.
Восемь направлений не заменяют отложенный независимый аудит V3/V4/V5/V6.

### Ограничения

Нет независимого PASS, полной визуальной/клавиатурной/скринридер QA, реальных мобильных
устройств/других браузеров, browser timeout/сетевой offline-эмуляции и нагрузки.
Ошибку соединения проверяли остановкой сервера, JS timeout — mock request с abort.
DOM-fixture не объявляется браузером. Одновременное cancel/decision не тестировалось
отдельным гоняющим нагрузку сценарием; version/writer-путь общий с проверенными гонками.
Offset-пагинация при новых поступлениях может смещать страницы. Ключ отправки только
в памяти: после reload/новой вкладки или изменения содержания сначала проверить список,
автоматической дедупликации с прежним ключом нет. Черновики/needs_info/вложения/официальные
справки/назначение staff scopes через web вне V6. Комментарий сотрудника, ещё не
отправленный, не сохраняется при обновлении деталей.
SQLite остаётся single-writer, NAT/distributed/source risks и Starlette/httpx warning
сохраняются. TLS/proxy/backup recovery/публичный периметр/лицензии не проверены.
Рабочая SQLite и старые SQL не менялись. V6 готов к независимой функциональной приёмке,
не к публичному размещению; V7 не начат.


## AUD-01 / AUD-02 — 5 ноября 2026

Источник находок и независимых результатов — задание пользователя от 5 ноября:
Astra High, V3/V6 PASS WITH WARNINGS, V4/V5 PASS, 90 Python/29 JS; P0/P1 не найдены,
public deploy NOT VERIFIED. Точные дата/ревизия аудита не предоставлены. Ниже — новые
проверки Sol в V5 HEAD 31a8ed8 + рабочем дереве V6/AUD, а не независимый повторный аудит.

Причины подтверждены: requests.js пересоздавал staff textarea без памяти ввода;
requests-state.js хранил retry key лишь в instance. Server owner/key/payload_hash
и атомарность корректны и не изменялись.

### Выполнено

1. Целевой `node --test tests/requests.test.js`: **13/13, exit 0**, включая 7 новых AUD.
   Owner/request staff draft при manual/background suspend, network/409, switch/logout,
   success; actual DOM renderer восстанавливает value, terminal conflict read-only.
   Потеря результата после simulated commit + новый controller + те же sessionStorage
   metadata = одна запись; изменённый текст конфликтует, другая форма не отправляется
   молча, явная новая операция создаётся отдельно. Account switch/logout/TTL/corruption/
   denied storage, metadata shape без текста/raw account ID, отсутствие ключа в URL.
2. Целевой `.venv/Scripts/python.exe -B -m unittest tests.test_requests.RequestTests.test_real_http_two_students_staff_and_decision -q`:
   **1/1, exit 0**. Дополнен Node bridge tests/request-recovery-http.mjs: настоящий
   frontend controller/crypto и Uvicorn/SQLite, cookie/CSRF передаются только stdin,
   не argv/логи. Ответ первого сохранённого POST намеренно не передаётся контроллеру;
   новый controller восстанавливает old key, изменённый текст=409, исходный=200,
   новая намеренная заявка=201. Совпадение key проверяется без вывода его значений.
3. Полный `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`:
   **90/90, exit 0**, без пропусков; сохранены A/B/faculty/CSRF/IDOR/atomic history/
   concurrency/quotas. Python-тестов не добавлялось, расширен существующий real HTTP.
4. Полный `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js tests/schedule.test.js tests/academics.test.js tests/requests.test.js`:
   **36/36, exit 0**, без пропусков (29 прежних + 7 новых).
5. Python AST backend/tests и node --check frontend/tests JS/MJS; Git diff/check,
   ссылки и protected hashes рабочей SQLite/SQL/AGENTS/Skills/config проверяются перед commit.
   Известное Starlette/httpx warning осталось; установки зависимостей нет.

### Реальный браузер

IAB, временная .tmp/aud-browser.sqlite3, loopback 8047, только синтетические данные.
Middleware исключительно тестового стенда оборвал тело HTTP 201 после commit (часть
JSON и закрытие соединения). Студент увидел ошибку и сообщение о неподтверждённой
отправке. После reload маркер восстановился без текста, повтор введённых тех же полей
вернул прежний request/version=1; прямое чтение тестовой SQLite подтвердило **одну** запись.

Staff: комментарий пережил «Проверить вход». Затем без ручного действия прошли 73 секунды;
access log зарегистрировал новый GET auth/me от минутного poll, поле сохранило текст.
Другая заявка имела пустое поле, возврат восстановил прежнее. После подтверждённого
успешного действия ни editable, ни retained draft нет; после logout/login поле пусто.
360×800 и 1280×900: scrollWidth 345/1265 при width 360/1280, переполнения в проверенных
состояниях нет. Screenshot .tmp/aud-staff.png без технических ключей, не в Git.
Viewport сброшен, вкладка закрыта; временный сервер и аккаунты отключены после проверки.

### Ограничения и остаточные риски

Browser 409/network для staff, второй сотрудник, blocked storage/TTL и закрытие с
повторным восстановлением вкладки не проверялись вручную; соответствующие логические
сценарии покрыты JS, права/конкуренция двух сотрудников — Python. Реальный minute poll
и потеря тела ответа проверены отдельно от mocks. Browser sessionStorage после закрытия
вкладки/перезапуска зависит от браузера; без доступного маркера нельзя доказать исход
прежней отправки, UI предлагает сначала проверить список. Staff draft не переживает
reload и не сохраняется на диск. Технический marker не является auth credential,
доступ к чужим заявкам по нему не предоставляется. Данные/пароли/cookies не пишутся
в хранилище; localStorage не используется. При отказе записи нового marker POST не идёт.

Это исправления Sol; независимая повторная проверка AUD-01/02 не выполнена. Нагрузка/DoS
не запускались. Полная accessibility, TLS/proxy/public perimeter, восстановление backups
и эксплуатационные настройки не подтверждены; public deploy остаётся NOT VERIFIED.


## UX-01 — 5 ноября 2026

Sol, база `334a86d2f8dae9669ad8f84c388afe57ff211e5c` + UX diff. Источник P1 UX-находки —
пользователь/Astra: visibilitychange(hidden) вызывал account.clear, который через
requestsIdentity(null) стирал owner-bound Map и reset студенческой формы.
Теперь suspend сохраняет текст в RAM, скрывает UI, блокирует действия; visible снова
проверяет identity/profile и доступ к выбранному обращению. Logout/pagehide/невалидная
identity очищают, server scope refusal удаляет draft выбранной заявки.

### Выполненные проверки

- `node --test tests/visibility.test.js`: **9/9, exit 0**. Реальные account.js handlers
  исполняются в VM, реальные mountRequests/state/render — с минимальным DOM, backend/fetch
  подменён. Это интеграция frontend-модулей с fake DOM, не настоящий браузер.
- Скрытие/возврат того же сотрудника: текст сохранился, пока ответ identity задержан —
  профиль/заявки скрыты, textarea отсутствует, student fields disabled. До и после
  восстановления administrative POST=0. Повторный refresh, hidden посреди refresh,
  late reply и online(hidden) не открывают UI.
- Expired 401, changed user 403 и role change очищают staff draft; faculty scope 404
  не восстанавливает поле и стирает draft выбранного обращения. Сетевая 503 сохраняет
  текст скрытым до успешной проверки. Неуспешный logout с дальнейшим hide/show остаётся
  закрытым, старый draft не появляется.
- Студенческие purpose/message сохраняются при hide/show; pagehide и logout очищают.
  Редактирования профиля нет (dl read-only); другие учебные модули только читают данные.
  Пароль при скрытии очищается. Существующие AUD-01/error/409/success и AUD-02 reload/
  nonce/quotas/account binding проверки сохранены.
- После сообщения пользователя о выключении ноутбука повторно выполнен полный набор:
  `.venv/Scripts/python.exe -B -m unittest discover -s tests -q` — **90/90, exit 0**,
  без пропусков, временные SQLite + реальные HTTP в существующих тестах;
  `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js tests/schedule.test.js tests/academics.test.js tests/requests.test.js tests/visibility.test.js`
  — **45/45, exit 0**, без пропусков (36 прежних + 9 UX).
- Python/JS синтаксис, Git diff/check, ссылки, выбранные secret patterns и protected
  hashes проверены при завершении. Зависимости не менялись, Starlette/httpx warning остаётся.

### Реальный браузер и ограничения

До выключения был открыт только экран входа временного стенда — это не успешный
сценарий смены вкладок. После выключения попытки открытия/подключения IAB закончились
тайм-аутом и ошибкой инициализации браузерного сервиса. Поэтому **реальный браузерный
тест UX-01 не проводился до результата**. Требуется ручной/независимый прогон, включая
настоящий tab switch в целевых браузерах/мобильную выгрузку страницы. Прежние браузерные
результаты AUD/V6 относятся к прежним изменениям и не присваиваются UX-01.

Pagehide, перезагрузка, закрытие вкладки, выгрузка браузером или выключение устройства
по-прежнему могут терять текст: новой системы автосохранения нет. Технический marker
AUD-02 сохраняет только retry metadata по прежним правилам. Независимая проверка UX-01
не выполнялась. Public deploy/TLS/proxy/backup recovery/полная доступность — NOT VERIFIED.

Временные UX-стенды остановлены: порты 8048/8049 без listener; демопользователи
отключены, сессии отозваны. Рабочая база не менялась.


## Локальная диагностика 8030 — 5 ноября 2026

Sol, HEAD 41ccc0dcac30565897d0c5455f7b003e84fff346; функциональный код не менялся.
Проверены config.py, app.py, IdentityGuard, migration/seed CLI и README.
System/venv Python 3.13.1; .venv активна, fastapi 0.162.0, uvicorn 0.54.0,
argon2-cffi 25.1.0, httpx 0.28.1 импортируются. Установок нет.
MGIMOV_DB_PATH/MGIMOV_ORIGIN в окружении не заданы: реальные defaults —
data/deanery.sqlite3 и http://127.0.0.1:8010. Read-only чтение migration IDs рабочей
базы показало только 0001_initial. Её хеш сохранён и сравнен после диагностики;
никаких apply/init/seed рабочей базы не выполнялось.

Socket bind+close на 127.0.0.1 подтвердил свободность 8001 и 8030; выбран 8030.
Настройки только дочернего проверочного процесса: MGIMOV_ORIGIN=http://127.0.0.1:8030,
MGIMOV_DB_PATH=.tmp/local8030-check-20261105.sqlite3, Uvicorn backend.app:app,
host 127.0.0.1, port 8030, proxy_headers=False. Новая временная SQLite с пятью миграциями
и всеми четырьмя demo seeds, случайные пароли только в памяти процесса, не в отчёте.
Проверка через три независимых httpx клиента trust_env=False:

- GET / — 200, MGIMO AI Challenge 2026/V6, login form и разделы модулей;
- все 15 явно перечисленных assets — 200 (включая корень, CSS и ES modules);
- /api/health — 200, status ok;
- профиль без сессии — 401; bootstrap/login трёх вымышленных аккаунтов — 200;
- у A/B профиль/расписание/зачётка/exams/debts/progress/requests — 200,
  группы и академические результаты различаются;
- staff requests — 200, student→staff queue — 403;
- изменённый Host localhost:8030 — 400, Origin другого порта — 403;
- CSRF logout всех трёх клиентов — 204. Ни пароли, ни cookies не выводились;
  лог проверен на отсутствие сгенерированных паролей.

Сервер завершён в finally. Демо-пользователи проверочной фикстуры отключены,
сессии отозваны. Это новые временные аккаунты, существующие аккаунты не сбрасывались.
Порты 8000/8027 и проекты Dashboard/Design Lab не использовались и не останавливались.

Для самостоятельного запуска подготовлена другая новая .tmp/demo-local-8030.sqlite3:
5 миграций, 0 пользователей, без паролей. Пользователь однократно интерактивно запускает
seed_demo (скрыто задаёт свои пароли), затем seed_schedule/seed_academics/seed_requests.
Повторная инициализация/сброс существующих пользователей не требуются и не рекомендуются.
[Точные команды](../README.md#локальный-запуск-windows-11-на-порту-8030).

Это диагностика HTTP, не новый полный unit-прогон или независимая приёмка. Клики
и реальная работа Chrome/Edge в этом задании не проверялись. Свободность порта
действует на момент проверки. Public/TLS/proxy по-прежнему NOT VERIFIED.


## LUNA-UI-01 — этап 1 — 5 ноября 2026

Исполнитель: Luna. Исходный HEAD `41ccc0dcac30565897d0c5455f7b003e84fff346`;
проверки выполнены на нём с текущим рабочим diff до коммита. Design Lab G утверждён
пользователем; использованы `HANDOFF-G.md`, `REPORT.md` (раздел G), `hybrid.js`,
`hybrid.css`, `theme.js`, `tokens.css`, `verify-hybrid.cjs` и актуальные HTML-оболочки.
G — новая передача после исходного A–F scope; отчёт лаборатории отдельно фиксирует
864 браузерных представления, 14 тестов выбора занятия и 8 220 проверок цвета.
Эти цифры относятся только к Design Lab, не к интеграции MGIMOv.

Проверки MGIMOv:

- `node --test tests/dates.test.js tests/api.test.js tests/account-state.test.js tests/appearance.test.js tests/schedule.test.js tests/academics.test.js tests/requests.test.js tests/visibility.test.js` — **53/53, exit 0**.
- `.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — **90/90, exit 0**. Разрешён loopback для Starlette TestClient; все test DB — временные фикстуры, рабочая SQLite не использовалась. Есть предупреждение о deprecated связке Starlette TestClient/httpx.
- `node --check frontend/js/account.js` и `node --check frontend/js/account-state.js` — exit 0.
- Python HTMLParser для `frontend/index.html` — OK.
- Контраст: JS-регрессии проверяют все 6 палитр в Light/Dark и custom black/white/yellow/gray; минимальный контраст ссылки и текста кнопки — 4.5:1.
- JS-регрессии также проверяют reload/account separation/reset, System OS switch, повторную identity-refresh без сброса темы, авторизованную сессию, существующий server logout, отсутствие API-запроса при смене оформления и сохранность незавершённого staff-комментария.

Ограничения: реальная браузерная проверка этого diff не выполнена. CUA прервался до загрузки стенда; DOM-тесты не считаются браузерной проверкой. Мобильное отображение, реальный `prefers-reduced-motion`, клавиатура и скринридер здесь не принимались. AUD-02 и UX-01 остаются без новой независимой браузерной пере-приёмки. Astra ещё не вернула независимый результат по этому diff.

Из Design Lab перенесена только система оформления и настройки; G-оболочка,
поисковая строка и блок занятия в этапе 1 не интегрировались. API, backend, SQLite,
авторизация/CSRF, storage черновиков и Design Lab не менялись. Этап 2 не начат.


## RC1 — стабилизация MVP-01/02/03, Sol, 6 ноября 2026

На базе df94743 + проверяемые рабочие/untracked-файлы. Команды:
`.venv\Scripts\python.exe -B -m unittest discover -s tests -q` и
`node --test tests/*.test.js`. В исходнике: 105 Python / 65 JS; в чистом RC с новой
.venv: 105 Python / 65 JS. Все PASS, exit 0; failures/errors/skips 0.
Новые test_rc.py: четыре регрессии с SQLite и реальным HTTP, rc.test.js: четыре
контроллерных/DOM-регрессии; rc-http.mjs включён в Python HTTP-сценарий, не отдельный
unit test. pip check: No broken requirements found. Существующее предупреждение
Starlette/httpx сохраняется. Первоначальный ensurepip в sandbox завершился exit 1;
после разрешённого расширенного запуска окружение создано и установка повторена
успешно из локального wheelhouse. Ошибка среды не засчитана как успех первого запуска.

Реальный IAB Chromium, 360×800, отдельная SQLite чистого RC: 36 обращений, выпуск и
передача старой справки из деталей второй страницы, получение A; B имеет только
свой документ, прямой чужой доступ 404 в HTTP. 129 уведомлений A → страница старых →
прочтение самого старого → unread 128; страница сохраняется. Снимки и полные
ограничения — [отчёт RC1](coordination/rc-stabilization-2026-11-06.md).
Рабочая SQLite/старые DPAPI не менялись; проверочные процессы завершены.


## RC2 Design — 7 ноября 2026, Sol

В рабочем дереве: `python -B -m unittest discover -s tests` — 105/105;
`node --test tests/*.test.js` — 71/71. В отдельной копии окончательного RC2
с новой venv: 105/105 Python (с реальными локальными HTTP-сценариями),
71/71 JS и `pip check` успешно. Везде exit 0 для итоговых прогонов.
Известное предупреждение Starlette/httpx сохраняется. В браузере проверены
Student и Staff на отдельной SQLite, включая выдачу справки, изменение
аудитории и уведомления. [Объём браузерного прогона, артефакт и оставшиеся
проверки](coordination/design-rc2-handoff-2026-11-07.md).


## RC2-01 — 7 ноября 2026, Sol

Целевая регрессия двух Staff-сессий: реальный HTTP 409, до исправления
поле отсутствовало, после исправления 1/1. Проверен production-рендерер
с DOM-фикстурой. В чистой копии RC2-01: `python -B -m unittest discover -s tests`
106/106; `node --test tests/*.test.js` 71/71; `pip check` успешно; exit 0.
[Метод, артефакт и ограничения](coordination/review-handoff.md#rc2-01--sol--astra-7-ноября-2026).


## RC2-02 — 7 ноября 2026, Sol

Целевой набор `node --test tests/design.test.js tests/appearance.test.js`
прошёл 13/13. В копии релиза `python -B -m unittest discover -s tests`
106/106, `node --test tests/*.test.js` 72/72, `pip check` успешно. Exit 0.
Встроенный браузер 1280×900 и 360×800 с тёмной системной темой и отдельной
демобазой подтвердил доступ по роли, смену и сброс оформления, сохранение
предпочтений и выход. Первый кадр отдельно не записывался.
[Объём проверки](coordination/review-handoff.md#rc2-02--sol--luna-и-astra-7-ноября-2026).

## RC3 Foundation

Sol, 10 ноября 2026, HEAD `df94743dfc8f5114f76c09ac67f881c6dc982238`
с локальной дельтой [Foundation](coordination/review-handoff.md#rc3-foundation).
`python -B -m unittest discover -s tests` — 106/106, exit 0;
`node --test tests/*.test.js` — 75/75, exit 0. Предупреждение о совместимости
Starlette TestClient/httpx сохраняется. Python включает настоящий loopback HTTP,
изоляцию четырёх Student, CSRF, регистрацию по приглашению и конфликты Staff.

Встроенный браузер на отдельной синтетической SQLite и FastAPI на 127.0.0.1,
`GET /api/health` — 200. При 1280×900 проверены горизонтальная навигация,
недельная сетка и детали события. При 360×800 и 390×844 проверены выбор дня
и меню; дополнительно зачётка, профиль, отдельные настройки и тема. В браузере
Staff изменил аудиторию на 405; Student получил уведомление, открыл расписание
и увидел 405 в деталях недели. Student создал заявку, Staff ответил, взял в
обработку, одобрил, подписал и передал справку; Student открыл её из уведомления.
Другой Student увидел свой профиль и не увидел выданную первому справку.
После финальной правки повторно проверены мобильный календарь, меню и выход.
Сервер остановлен. Полный аудит клавиатуры, реальный телефон и публичный сервер
не проверялись; точечные проверки конфликтов и прямого чужого ID выполнены тестами.

## RC3 Foundation — исправления после проверки Astra

11 ноября 2026, Sol. HEAD `df94743dfc8f5114f76c09ac67f881c6dc982238`
с локальной дельтой. Полные наборы:
`python -B -m unittest discover -s tests` — 106/106, exit 0.
`node --test tests/*.test.js` — 77/77, exit 0.
Миграция сохранённых настроек проверена JS-тестом с записью V1.
Предупреждение Starlette TestClient/httpx сохраняется.

Встроенный Chromium на синтетической SQLite, viewport 1280×900, 360×800
и 390×844. До входа зачётка скрыта. После первого входа Student из
`#academics` открылась зачётка, повторный reload её сохранил. В Staff
эта ссылка открыла очередь, а reload собственного расписания сохранил
его. Проверены выход, вход другого Student, новый светлый синий стандарт,
сохранение тёмной темы после reload и сброс. В браузере открыты расписание
с недельным переключателем, обращения, документ и уведомления Student.
У Staff открыты очередь, расписание, справки и уведомления. HTTP health 200,
тестовый сервер остановлен. Сценарий миграции V1 в браузере не повторялся.

## RC3 Foundation — Final UI QA

11 ноября 2026, Sol. `node --test tests/*.test.js` — 77/77, exit 0.
Серверная логика не затронута. 106 Python/HTTP PASS — переданный
пользователем результат Astra, отдельный прогон в этой задаче не требовался.

Chromium IAB, локальный стенд на копии синтетической SQLite, HTTP health 200.
До правок шесть замеров на главной Student и расписании Student/Staff:
до конца 0 px, до панели от нижней строки 49 px. После правок восемь
замеров, включая очередь Staff: до конца 0 px, зазор 49–50 px. На 360×800
ширины документа 345/345 px, на 390×844 — 375/375 px.
Проверены меню и Escape, reload расписания с тёмной темой, сброс темы,
прямая ссылка и reload зачётки, выход и смена роли. На 1280×900
подтверждены скрытые стрелки на коротком списке и прокрутка длинного
списка Staff клавишами, колёсиком и кнопкой. При 1920×900 весь список
Staff поместился и стрелки скрылись, при возврате на 1280 снова появились.
Стенд остановлен. Физические устройства и другие браузеры не проверялись.

## RC3.1 БРС — этап 1

`python -B -m unittest discover -s tests` — 115/115, exit 0.
`python -B -m unittest tests.test_brs_foundation -v` — 9/9, exit 0.
`node --test tests/*.test.js` — 77/77, exit 0.
Проверены инициализация новой SQLite, обновление заполненной базы 0006
с резервной копией и повторный запуск. `integrity_check` вернул `ok`,
`foreign_key_check` не нашёл нарушений. Проверены конкурентная фиксация
и откат перевода при сбое аудита. Использованы временные синтетические базы.
Сохраняется предупреждение совместимости Starlette TestClient/httpx.

## RC3.1 БРС — исправление после аудита

На временной SQLite с 0007 одна строка сменила владельца. Alice/Bobby
получили 404/200 вместо 200/404. После 0008 SQL отклонён, доступ 200/404.
Отдельный прогон SQL/API, перевода и обновления 0007 — 3/3.
`python -B -m unittest discover -s tests` — 117/117, exit 0.
`node --test tests/*.test.js` — 77/77, exit 0.
В предварительном Python-прогоне один HTTP-тест расписания не дождался
старта сервера. Итоговый полный прогон прошёл. Проверки целостности
и внешних ключей прошли для временных баз, включая резервную копию 0007.
[Передача Astra](coordination/review-handoff.md#rc31-брс--исправление-после-аудита).

## RC3.1 БРС — исправление вставки курса

На SQLite 3.45.3 сценарий 0008 завершился ошибкой при recursive_triggers
OFF и ON. На 0009 в обоих режимах прошли автоматическая вставка рядом с
rowid = -1, запрет явного REPLACE, откат многорядной операции и вставка
после VACUUM. Проверены доступ Alice/Bobby, законный перевод, обновление
заполненной 0008, резервная копия и повторный запуск. integrity_check —
ok, foreign_key_check — пусто. Только временные SQLite.

`python -B -m unittest tests.test_brs_foundation -v` — 12/12, exit 0.
`python -B -m unittest discover -s tests` — 118/118, exit 0.
`node --test tests/*.test.js` — 77/77, exit 0.
[Передача](coordination/review-handoff.md#rc31-брс--исправление-вставки-курса).

## RC3.1 БРС — этап 2

`python -B -m unittest discover -s tests` — 127/127, exit 0.
`python -B -m unittest tests.test_brs_results -v` — 9/9, exit 0.
`node --test tests/*.test.js` — 77/77, exit 0.

На временных SQLite проверены приватность черновиков, публикация и исправление,
пересдачи вокруг полуночи по Москве, повторы и конкурентные запросы,
откат при сбое аудита и квитанции, SQL-защита версий, права после перевода
и сохранение зачётки. Заполненная база 0009 обновилась до 0010. Резервная
копия и обновлённая база сохранили прежние данные. Повторное применение
не нашло ожидающих миграций. integrity_check — ok, foreign_key_check — пусто.
[Передача](coordination/review-handoff.md#rc31-брс--этап-2).

## RC3.1 Phase 3

Рабочее дерево при HEAD `df94743dfc8f5114f76c09ac67f881c6dc982238`.
`python -B -m unittest discover -s tests` — 137/137, exit 0.
`node --test tests/*.test.js` — 78/78, exit 0.
Чистая синтетическая SQLite и обновление отдельной базы с 0011 прошли
проверки целостности и внешних ключей. Через API проверены приватность
черновика, публикация, повтор, защита ролей, Origin и CSRF, конкурентное
назначение и откат при сбое аудита. В Edge проверены публичный переключатель,
reload, вход S06, раздел аттестаций при 390 px, выход и открытие истории
сотрудником при 1280 px. Проверка Edge выполнена до последних усилений SQL.
[Передача Phase 3](coordination/review-handoff.md#rc31-phase-3).

### Phase 3 — история попыток

`python -B -m unittest discover -s tests -v` — 142/142, exit 0.
`node --test tests/*.test.js` — 78/78, exit 0.
Специализированный модуль `tests.test_legacy_assessment_identity` — 5/5.
На изолированных SQLite проверены воспроизведение на 0013, перенос всех строк
на 0014, повтор мигратора, четыре комбинации foreign_keys и recursive_triggers,
атомарность конфликтующей вставки и штатная пересдача. Отдельно сверены три
записи аудита разрешённого исправления Phase 3 на синтетическом курсе.

### Phase 3 — применение согласованного исправления

`python -B -m unittest discover -s tests -v` — 143/143, exit 0.
`node --test tests/*.test.js` — 79/79, exit 0.
API-регрессия прошла на синтетической SQLite. DOM-тест подтвердил, что
для кнопки достаточно номера применимого пересмотра.

## RC3.1 — браузерная приёмка

- P1 и комиссии S02/S05 — 3/3 PASS в Google Chrome.
- Полномочия, RU/EN и адаптивность при 390×844 и 1280×900 — 8/8 PASS
  в отдельном прогоне Google Chrome.

Итого 11/11 по двум отчётам Sol. Единый прогон всех 11 тестов не подтверждён.
Причина одного предварительного тайм-аута RU/EN осталась неизвестной.
Финальный сценарий прошёл с перезагрузкой перед повторным входом.
Геометрию проверяли на выбранных элементах, а визуально сравнили главную
Student на обеих ширинах. Пользователь принял дизайн и отложил дальнейшие
визуальные изменения до следующего обновления.

## RC4.1 — резервное копирование

База сравнения `d1c24df84baea88d8e7a50608ff4b676d71d939a`.
`python -B -m unittest tests.test_backup_database -q` — 3/3, exit 0.
Проверены SQLite-снимок и диагностика восстановленной копии, ротация,
защита старых файлов при ошибке, квота и блокировка повторного запуска.
`python -B -m unittest discover -s tests -q` — 146/146, exit 0, с локальными HTTP-тестами.
`npm test` — 79/79, exit 0. Cron на VPS и запуск приложения на восстановленной
копии в рамках этой итерации не проверялись.

После аудита Luna целевой прогон резервирования и создания черновика — 6/6,
exit 0. Проверены сохранение постороннего ежедневного файла, учёт остатков и
ручных копий, отказ при недостатке места, освобождение блокировки после
принудительной остановки процесса в Windows и отказ преподавателю с истёкшим
назначением. Интеграция cron и проверка приватного каталога на Linux ожидаются.
Полный Python-прогон после миграции 0015 и исправлений — 149/149, exit 0.

## RC4.1 — жизненный цикл учебных работ

База сравнения `d1c24df`. Полный Python-прогон на локальных временных
SQLite с HTTP-тестами — 151/151, exit 0. `npm test` — 79/79, exit 0.
Проверены параллельный повтор сдачи, конфликт версии и ключа, просрочка,
возврат и очная попытка, независимое копирование, перенос в другой поток,
граница семестра и истечение назначения преподавателя.

## RC4.1 — повторная стабилизация резервирования

Рабочее дерево поверх `d1c24df`, временные SQLite внутри проекта.
Профильный прогон `python -B -m unittest tests.test_backup_database -v` — 13/13,
exit 0. Подтверждены восстановление после сбоя записи SHA-256 и переименования,
карантин незавершённого снимка и частичной суммы, снимок при активной записи в
WAL, ротация, квота и освобождение блокировки после завершения процесса.
Три целевых теста миграций прошли, включая диагностику `SQLITE_AUTH` и атомарный
откат. `python -B -m unittest discover -s tests -k coursework -v` — 3/3, exit 0.
`npm test` — 79/79, exit 0.
Полный прогон `python -B -m unittest discover -s tests -q` с разрешёнными
локальными сокетами Windows — 160/160, exit 0.

## RC4.1 — оценивание и история, 15 ноября

Рабочее дерево поверх `d1c24df`, только временные SQLite внутри проекта.

- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -k coursework -v` — 6/6, exit 0.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v` — 163/163, exit 0.
- `npm test` — 79/79, exit 0.

Python запускался с разрешённым loopback Windows, который требуется для
инициализации asyncio Proactor и локальных HTTP-тестов. Обходы в коде и тестах
не добавлялись. Проверены переходы с 0014 по 0017, сохранение черновика и старой
проверки, откат 0017 при ошибке, запрет UPDATE/DELETE/REPLACE для истории,
три режима, границы баллов, конфликт публикации и перевод между потоками.

## RC4.1 — защита публикации и попыток, 15 ноября

База сравнения `d1c24df`, изолированные временные SQLite, разрешённые
локальные сокеты Windows.

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_brs_foundation tests.test_brs_results -q` — 32/32, exit 0.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 164/164, exit 0, на итоговой версии 0018.
- `npm test` — 79/79, exit 0.
- `git diff --check` — exit 0.

Проверены оба порядка конфликта, прямые SQL-записи, независимые потоки и
семестры, сохранность черновика БРС при отказе, законное исправление прежней
попытки, история сдач и метаданные проверок. Цепочка с 0014 до 0018 проверена
на заполненной синтетической базе, включая искусственный сбой 0018,
повторный запуск, `integrity_check` и `foreign_key_check`.

Первый полный прогон пересёкся с правкой локальной 0018: при проверке
созданной до правки временной БД мигратор сообщил о несовпадении SHA-256.

## RC4.1 — защита родительских строк coursework

Рабочее дерево поверх `d1c24df`, временные синтетические SQLite внутри
проекта, разрешённые локальные сокеты Windows.

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_brs_foundation tests.test_brs_results -q` — 33/33, exit 0.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 165/165, exit 0.
- `npm test` — 79/79, exit 0.
- `git diff --check` — exit 0.

Проверены запреты DELETE, UPDATE и REPLACE, включая конфликт альтернативного
уникального ключа, при всех сочетаниях `foreign_keys` и `recursive_triggers`.
Проверены чтение прежней истории, создание новой версии и повторной сдачи,
удаление черновика без связей, обновление заполненной базы с 0014 до 0019,
откат ошибочной 0019, повторный запуск мигратора и обе проверки SQLite.

## RC4.1 — HTTP API учебных работ

Локальное дерево поверх `b0e6097`, синтетические временные SQLite и разрешённый
loopback Windows. HTTP-тесты отправляют запросы через FastAPI TestClient с
реальными сессиями фикстур и middleware.

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_coursework_http -v` — 4/4, exit 0.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 169/169, exit 0.
- `npm test` — 79/79, exit 0.
- `git diff --check` — exit 0.

Проверены Student/Staff, отсутствие назначения и его истечение, недоступность
чужой работы, Origin/CSRF, повтор и конфликт версии, просрочка, история и
повторная сдача, код конфликта БРС, очная сдача, копирование между потоками,
исторический семестр, ошибки JSON и временная блокировка SQLite.

### Повторная проверка HTTP API после замечаний Luna

Рабочее дерево поверх `b0e6097`, временные синтетические SQLite и разрешённый loopback.

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_coursework_http -v` — 7/7, exit 0.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 172/172, exit 0.
- `npm test` — 79/79, exit 0.
- `git diff --check` — exit 0.

Проверены 4000/4001 кодовых точек ASCII, кириллицы и emoji, 32768/32769
байт на сдаче, прежний лимит Staff, оба вида конкурентного повтора, изоляция
новых полей, фактический перевод, отзыв назначения, смена серверной роли и
истечение сессии. Запросы выполнялись через FastAPI TestClient и HTTP middleware.

## RC4.2 — Coursework UI

Рабочее дерево поверх `904c48a`, Windows, только синтетические SQLite.

- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 172/172, exit 0.
- `npm test` — 84/84, exit 0.
- Из каталога `tests/browser`: `.\node_modules\.bin\playwright.cmd test coursework.spec.js --reporter=list` — 1/1, exit 0.

Chrome прошёл реальный Uvicorn и SQLite на 1280 px для Staff и 390 px для
Student. Проверены создание, редактирование, публикация, Unicode-сдача,
конфликт устаревшей вкладки, сохранение ввода, ручное обновление, возврат,
вторая версия проверки, повторная сдача и пустой список другого студента.
Скриншоты сохраняются в `.tmp/playwright-p1/results/`. Остальные браузерные
наборы в этом прогоне не запускались.

### RC4.2 — повторная проверка сессии и Coursework E2E

Дерево на базе `904c48a`, временные синтетические SQLite и Windows loopback.

- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 172/172.
- `npm test` — 84/84, включая отдельное сообщение 415.
- Из `tests/browser`: `.\node_modules\.bin\playwright.cmd test coursework.spec.js --reporter=list` — 3/3.
- `git diff --check` — exit 0.

Chrome проверил Student 390 px, Staff 1280 px и Student 768 px. Реальные
401 Student и Staff доставлены после перехода на профиль. После ответа
формы входа видны, данные других разделов очищены. Запоздавший 200,
выход во время запроса, смена аккаунта и серверной роли, очистка введённого
и новый ключ повтора проверены через интерфейс. Smoke прошёл для главной,
расписания, зачётки, аттестаций, профиля, настроек и защищённого чтения БРС.

При ограниченном loopback отдельный TestClient завис в AnyIO/Proactor на
`socket.socketpair()`. Контрольный вызов с доступом к loopback завершился.
Chrome-фикстура больше не поднимает TestClient. Uvicorn использует реальный
HTTP и по-прежнему требует доступных локальных сокетов.

### RC4.2 — запоздавший 401 после второго входа

Рабочее дерево поверх `904c48a`, Chrome и реальный Uvicorn с временной SQLite.
Студент A начал сдачу, его сессия истекла, а реальный ответ 401 удерживался
до входа B. После доставки B остался в системе со своей работой и черновиком.
Ответ B сохранён с HTTP 201 и другим ключом. Название работы и черновик A
отсутствовали в DOM.

- Полная Python-регрессия — 172/172, exit 0.
- `npm test` — 84/84, exit 0.
- `playwright test coursework.spec.js --reporter=list` — 4/4, exit 0.
- `git diff --check` — exit 0.

Логи `.tmp/rc42-late-401-*.log` и снимок `student-b-after-late-401.png`
в каталоге Coursework-теста предназначены для независимого просмотра.

### RC4.2 — финальные UX и E2E, 16 ноября

Дерево поверх `904c48a`, Windows с доступным loopback, реальный Chrome,
Uvicorn и временная синтетическая SQLite.

- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 172/172, exit 0.
- `npm test` — 84/84, exit 0.
- `playwright test coursework.spec.js --reporter=list` — 5/5, exit 0.
- `git diff --check` — exit 0.

Клавиатурный прогон Student на 390, 768 и 1280 px подтвердил Tab, Shift+Tab,
изменение обоих фильтров стрелками, стабильный фокус и отсутствие
горизонтального переполнения при длинном названии. Staff 1280 px проверен
в сквозном сценарии. Сохранены empty, loading, error и conflict. Ошибка
чтения вызвана управляемым обрывом соединения в браузерном тесте.

Контрольная мутация на одноразовой браузерной копии убрала проверку поколения
сессии. Тест достиг барьера завершения обработки 401 и упал на проверке роли:
ожидалось `student`, получено `anonymous`. Обычный тест прошёл.
Логи сохранены в `.tmp/rc42-final-*.log`, снимки — в `.tmp/playwright-p1/results/`.
