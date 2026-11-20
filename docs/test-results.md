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

## RC4 — P0.1 конкурсная демосреда

Дерево поверх `494007a`. Проверки выполнялись на временных синтетических
SQLite с доступом к Windows loopback.

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_contest_demo -v` — 1/1, exit 0.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 173/173, exit 0.
- `npm test` — 84/84, exit 0.
- Полный существующий Chrome-набор Playwright — 16/16, exit 0. Тесты RC3.1
  использовали копии синтетической базы Astra, её SHA-256 осталась прежней.
- Отдельный запуск Uvicorn на БД новой команды — 200 для страницы, ассетов и
  health, 401 для анонимного чтения Coursework. Сервер остановлен.
- `git diff --check` — exit 0.

Новый HTTP-тест дважды готовит демосреду и подтверждает неизменность первой
базы, схему до 0019, integrity/FK, вход трёх учёток, чтение расписания, БРС и
зачётки, сдачу и возврат с повтором, сохранение баллов и изоляцию. Полный
Chrome-набор использует свои фикстуры. Ручной показ новой базы в Chrome
остаётся проверкой для независимой приёмки.

### P0.1 — блокер наследуемой Windows ACL

Проверено на Windows на временных SQLite. DACL каталога снята отдельно от
проверки seed: `D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;CURRENT_USER_SID)`.
DACL базы: `D:(A;ID;FA;;;CURRENT_USER_SID)(A;ID;FA;;;SY)(A;ID;FA;;;BA)`.
Проверенный SID пользователя в записи заменён на метку. SYSTEM имеет
SID `S-1-5-18`, Builtin Administrators — `S-1-5-32-544`. Все три имеют
FullControl. В каталоге наследование от родителя отключено. SQLite наследует
ровно эти разрешения. ACL проектной `.tmp` до и после совпала.

Постоянный тест проверил фактические права живых SQLite `-journal`, `-wal`,
`-shm`. Отрицательный тест создал временную папку с реальным небезопасным
наследованием. Проверка ACL отклонила её до SQLite и вернула путь папки.
Повторная подготовка и HTTP-сценарий Student/Staff прошли. Linux/macOS в этом
прогоне не проверялись.

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_contest_demo -v` — 3/3.
- `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q` — 175/175.
- `npm test` — 84/84.
- Полный Chrome Playwright — 16/16. Синтетическая исходная SQLite Astra
  сохранила SHA-256. Лог — `.tmp/p01-acl-full-chrome.log`.
- `git diff --check` — exit 0.

### P0.1 — защита родительского пути Windows

Рабочее дерево поверх `494007a`. Проверка ACL исходного пути отказала на
`C:\Projects`, где у Authenticated Users (`S-1-5-11`) действует Modify.
Прямой вызов seed отказал до SQLite. DACL исходной `.tmp` до и после совпала.
Цепочка через `C:\Users` и профиль пользователя прошла проверку. В приватной
копии у каталога запуска защищённая DACL `D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;CURRENT_USER_SID)`.
SQLite наследует `D:(A;ID;FA;;;CURRENT_USER_SID)(A;ID;FA;;;SY)(A;ID;FA;;;BA)`.
Те же три SID проверены на живых `-journal`, `-wal` и `-shm`.

Профильный тест выдал `DELETE_CHILD` на реальном предке после первой проверки
checkout и получил отказ до SQLite. Реальный junction тоже получил отказ.
В отдельной непривилегированной сессии Windows гонка после последней
проверки не воспроизводилась. После этой проверки защита опирается на DACL
объекта и его предков, включая право `DELETE_CHILD` у каждого родителя.

- `python -B -m unittest tests.test_contest_demo -v` в приватной копии — 6/6.
- `python -B -m unittest discover -s tests -q` в приватной копии — 178/178.
- `npm test` — 84/84.
- `playwright.cmd test --reporter=list --output ../../.tmp/playwright-p01-path/results`
  из `tests/browser` — 16/16 в Chrome на штатных временных фикстурах.
- `git diff --check` — без замечаний.

### P0.1 — повторная проверка двух Windows-фикстур

Sol, рабочее дерево поверх `494007a`, одноразовая приватная копия проекта
на Windows. Тест `DELETE_CHILD` прочитал фактическую DACL и подтвердил
действующий Allow ACE с `0x40` для Authenticated Users (`S-1-5-11`).
После проверки восстановлена DACL тестовой папки. Тест junction подтвердил
атрибут reparse point, тег mount point и совпадение с назначенной целью.
Генератор отклонил обе подтверждённые фикстуры до записи SQLite.

При контролируемой проверке отсутствие нужного ACE и отказ команды создания
junction дали по одному SKIP. Этот прогон проверяет только отчётность тестов.
**NOT VERIFIED** — отказ самой ОС в другой Windows-среде и конкурентная
подмена после финальной проверки из отдельной учётной записи.

| Прогон | PASS | FAIL / ERROR | SKIP |
| --- | ---: | ---: | ---: |
| `python -B -m unittest tests.test_contest_demo -v` | 6 | 0 / 0 | 0 |
| Обе фикстуры в обратном порядке | 2 | 0 / 0 | 0 |
| Контролируемая недоступность двух фикстур | 0 | 0 / 0 | 2 |
| `python -B -m unittest discover -s tests -q` | 178 | 0 / 0 | 0 |

`git diff --check` — exit 0.

## RC4 — P0.2a: ротация и тестовое восстановление

Рабочее дерево поверх `5955371`. Прогон Windows в отдельной приватной
копии проекта на синтетических SQLite. `python -B -m unittest
tests.test_backup_database tests.test_restore_database -v` — 27 PASS,
0 FAIL, 0 ERROR, 0 SKIP. Проверены пропуски дат, идемпотентный повтор,
повреждённая копия, неверный SHA-256, нарушение FK, схема старого релиза,
существующие файл и sidecar, гонка за имя, отказ из-за прав, реальный
junction, рубеж публикации и сохранность прежних комплектов.

Выполнен реальный CLI restore. Готовый тестовый файл совпал с исходным
снимком побайтно, прошёл диагностику и проверку Windows DACL.
`python -B -m unittest discover -s tests -q` — 192 PASS, 0 FAIL,
0 ERROR, 0 SKIP. `git diff --check` — exit 0.
Фактический ENOSPC, остановка процесса с незавершённой записью на Linux,
запуск службы из восстановленной базы и откат — NOT VERIFIED для P0.2a.

## RC4 — P0.2b: репетиция восстановления и отката

Основа `6601c05`, приватная одноразовая копия на Windows.
`python -B -m unittest tests.test_recovery_rehearsal -v` — 1 PASS.
Прошли штатные CLI backup, restore и `diagnose` с миграциями до 0019.
SHA-256 восстановленного файла до входа совпал со снимком. Проверки
целостности и внешних ключей прошли. Исходная SQLite после фиксации точки
восстановления, снимок и квитанция сохранили SHA-256.

Uvicorn на loopback вернул 200 для исходной базы, восстановленной базы
и двух повторных запусков предыдущей пары. Кандидат с ожидаемой схемой
0020 и тестовой БД схемы 0019 вернул 503. После остановки проверены выход
процесса, исключительная транзакция и состояние WAL. Активный WAL-писатель
заблокировал проверку готовности к переключению. CLI restore отклонил
неверный SHA-256 на отдельной копии, занятое имя и остаточные WAL/SHM.

Сохранены 20 учёток и их роли. Реальный вход s01, s02 и t01 подтвердил
расписание группы g-a, БРС 100 баллов, официальную оценку 5, две попытки
Coursework и две проверки с итогом 8/10. После каждого отката контрольные
ответы совпали. Изменение в БД кандидата после снимка осталось в кандидате.

`python -B -m unittest discover -s tests -q` — 193 PASS, 0 FAIL, 0 SKIP.
Полная регрессия стартовала до добавления проверок конкретных оценок, баллов
и причин отказа CLI. Итоговый целевой прогон с ними — 1 PASS за 47.460 с.
`npm test` — 84 PASS. `git diff --check` — exit 0.
Реальный Ubuntu/systemd, ENOSPC, доставка уведомлений и эксплуатационный
откат — NOT VERIFIED.

### P0.2b — контрольный прогон Windows

HEAD `6601c0563362c0b179c1854e75a057ca0b8303a2`, рабочая версия теста P0.2b,
изолированная приватная копия проекта. TCP-клиент подключился к собственному
listener на `127.0.0.1` и передал контрольный байт. У файла в каталоге с
проверенной DACL создана жёсткая ссылка. `samefile` подтвердил общий файл,
`st_nlink` вернул 2. Оба тестовых имени удалены.

```text
python -B -m unittest -v tests.test_recovery_rehearsal
test_restore_and_repeated_rollback (tests.test_recovery_rehearsal.RecoveryRehearsalTest.test_restore_and_repeated_rollback) ... ok
Ran 1 test in 51.897s
OK
UNITTEST_EXIT_CODE=0
```

Тест выполнялся без правок. Временный наблюдатель в одноразовой копии
собрал коды возврата, HTTP-статусы, контрольные значения и SHA-256.

| Стадия | Результат |
| --- | --- |
| Backup CLI | Exit 0, опубликован `daily-2026-11-16` |
| Первый restore и два rollback | `restore_database` и `diagnose` завершились с exit 0 на каждом из трёх новых файлов |
| Целостность | `integrity_check=ok`, `foreign_key_check` без нарушений, схема и контрольные суммы миграций совпали, последняя миграция `0019_coursework_parent_guards` |
| FastAPI, сессии и данные | HTTP 200 у источника и всех трёх восстановленных баз. Каждый раз входы `s01`, `s02` и `t01` дали 200 с ожидаемыми ролями. Сохранены 20 учёток, расписание `g-a`, БРС 100, официальная оценка 5, две сдачи и две проверки Coursework с итогом 8/10 |
| Несовместимая схема | Кандидат, ожидающий `0020`, вернул HTTP 503 на тестовой базе `0019` |
| Ошибки restore | Exit 1 для неверного SHA-256 на отдельной копии, занятого имени, остаточного WAL и остаточного SHM |

| Контроль SHA-256 | Значение |
| --- | --- |
| `demo.sqlite3` после фиксации точки и в конце прогона | `47ee766f6b5cb26bd6345a9004a79ce1e87f17694eb2ff2ec25e54651ddd293e` |
| `daily-2026-11-16.sqlite3` до и после восстановлений | `096f809ebc310f903426c849f4faa56eb28f740841b4e901aa960c132855062f` |
| `daily-2026-11-16.sha256` как файл, до и после восстановлений | `14758013dab75e6936769e25b19b7900b9fd74b70f5af5787f10b7456caa0388` |
| `restored.sqlite3`, `rollback.sqlite3`, `rollback-repeat.sqlite3` до входа | `096f809ebc310f903426c849f4faa56eb28f740841b4e901aa960c132855062f` |

Каждый дочерний Uvicorn завершил работу после EOF на управляющем stdin.
Коды выхода всех пяти процессов равны 0. Тест ждёт выхода нужного процесса
с тайм-аутом и аварийно завершает только его при превышении тайм-аута,
фиксируя FAIL. После штатного выхода проходит `BEGIN EXCLUSIVE` с нулевым
тайм-аутом и `wal_checkpoint(TRUNCATE)` с `busy=0`. Контрольный активный
писатель на базе кандидата вызвал ожидаемый отказ проверки. Этот прогон
подтверждает состояние только собственных процессов и синтетических БД.

## RC4 — P0.2c.2: мониторинг ежедневного backup

Рабочее дерево поверх `b7962f6`. `python -B -m unittest
tests.test_check_backup -v` — 10 PASS, 0 FAIL, 0 ERROR, 0 SKIP в приватной
копии на Windows. Реальный CLI подтвердил опубликованный комплект и его
побайтную неизменность. Проверены пропущенная UTC-дата, неверный SHA-256,
повреждённая SQLite и нарушение FK с соответствующей квитанцией,
несовместимость с миграциями, исключение staging и карантина, отказ по DACL
и отсутствие чувствительных деталей в сообщении об ошибке доступа.

Git Bash проверил синтаксис двух примеров cron и шесть сценариев с подставными
командами. При успехе вывод для `MAILTO` пуст. При ошибке задания или `logger`
выводится только фиксированное сообщение и код 1. Linux cron, реальный
Linux CLI и доставка уведомления — NOT VERIFIED. Расписание не включалось.

Полная Windows-регрессия `python -B -m unittest discover -s tests -q` —
203 PASS, 0 FAIL, 0 ERROR, 0 SKIP. `git diff --check` — exit 0.

## Coursework V

Этап 1, рабочее дерево поверх `070d324`. Windows HTTP Coursework — 8/8,
целевые JS — 5/5, Chrome Coursework — 7/7. Лабораторная и контрольная
прошли очную сдачу, возврат, текстовую пересдачу и выставление баллов.
Отдельный HTTP-тест проверил версию получателя, повтор команды и отказ
чужому студенту и преподавателю без полномочий.

Этап 2. Coursework HTTP и BRS foundation — 28/28, JS Coursework — 5/5,
Chrome Coursework — 7/7. Оба типа прошли загрузку материала, скачивание
и текстовую пересдачу с файлом. Backup/restore и два rollback — 1/1 в
приватной Windows-копии: вложение скачал владелец, чужая сессия получила 404.
Промежуточная полная Windows-регрессия `python -B -m unittest discover -s tests -q`
до этапа 3 — 205/205.

Этап 3. Целевые Coursework, БРС и аттестации — 50/50. Отдельно повторён
HTTP-сценарий публикации, исправления и пересдачи на итоговом коде — 1/1.
Обычная публикация в зарезервированную область отклонена. Пересдача требует
штатной регистрации, `highest` сохраняет лучший балл, зачётка сохраняет
официальную оценку. Полная JS-регрессия `npm test` — 84/84. Полный Chrome
Playwright `playwright test` — 19/19, в том числе 8/8 Coursework.
Итоговая Windows-регрессия `python -B -m unittest discover -s tests -q`
в приватной копии с синтетическими SQLite — 206/206, exit 0 (570.631 с).
`git diff --check` — exit 0. Эксплуатационная проверка Linux — NOT VERIFIED.

### Повторная проверка Coursework V после замечания Luna

Windows, рабочее дерево поверх `070d324`. На 0021 воспроизведена прямая
вставка с автором без назначения и без аудита. На 0022 целевой запуск
`python -B -m unittest tests.test_coursework_http tests.test_brs_results -q` —
27/27, exit 0. Проверены отказ без функции соединения при разных PRAGMA,
атомарный откат при пропуске записи аудита, конкурентное исправление,
идемпотентность, отзыв назначения и сохранение проверенных записей 0021.
`npm test` — 84/84, exit 0. Chrome `playwright test coursework.spec.js` —
8/8, exit 0. Артефакты — `.tmp/coursework-v-luna-chrome`.
Отдельная команда `python -B -m unittest -v tests.test_recovery_rehearsal`
в приватной копии — 1/1, exit 0. Проверены CLI backup и restore, запуск
FastAPI из копии и два отката. Использовались только синтетические SQLite.
Полная Windows-регрессия `python -B -m unittest discover -s tests -q`
в приватной копии — 209/209, exit 0 (391.997 с). `git diff --check` — exit 0.

### Coursework V — серверный аудит, схема 0023

Windows, рабочее дерево поверх `070d324`. `python -B -m unittest
tests.test_coursework_http tests.test_brs_results -q` — 28/28, exit 0.
Проверены чистая схема 0023, обновление заполненных 0021 и 0022, защита
штатного API, включая актуальное зачисление до возврата повтора, конкурентные
команды и откат при пропуске аудита обычного БРС и Coursework.
`npm test` — 84/84, exit 0. Chrome `playwright test coursework.spec.js` —
8/8, exit 0. Артефакты — `.tmp/coursework-v-server-audit-chrome`.
`python -B -m unittest -v tests.test_recovery_rehearsal` в отдельной приватной
копии — 1/1, exit 0. Пройдены backup, restore, FastAPI и два отката.
Полная Windows-регрессия `python -B -m unittest discover -s tests -q`
в приватной копии — 210/210, exit 0 (360.403 с). `git diff --check` — exit 0.
Права Linux под разными учётными записями и Nginx — NOT VERIFIED.

## Базовая посещаемость — 18 ноября 2026

Рабочее дерево `main` поверх `a1e348c`. Только синтетические SQLite.
`python -B -m unittest tests.test_attendance tests.test_coursework_http
tests.test_brs_results tests.test_schedule -q` — 43/43, exit 0. Дополнительно
повторён итоговый `tests.test_attendance` — 6/6, exit 0, включая устаревший
состав после перевода, откат миграции и сравнение прежних данных.
`npm test` — 87/87, exit 0. Три новых JS-теста проверяют очистку при смене
аккаунта/роли, запоздавший ответ, 401 и явное обновление после 409.
Полный Chrome Playwright — 20/20, exit 0. После уточнения прямого перехода
из Staff-расписания повторён `attendance.spec.js` — 1/1, exit 0.
Артефакты — `.tmp/attendance-final-chrome`, скриншоты Student 390 и Staff 1280.
Скриншоты просмотрены. Проверены диалог, история, прокрутка и отсутствие
горизонтального переполнения диалога на 390 px.
Первый полный Chrome-прогон дал 19 PASS и 1 FAIL из-за непереведённой кнопки
в английском расписании. Перевод добавлен, повторный полный прогон прошёл.
Полная Windows-регрессия `python -B -m unittest discover -s tests -q` в
отдельной приватной копии — 216/216, exit 0 (427.802 с). Включены действующие
backup/restore и репетиция rollback. Лог — `.tmp/attendance-python-regression.log`.
`git diff --check` — exit 0. Независимая приёмка Luna ещё не выполнена.

### Исправления посещаемости после REJECT Luna — 18 ноября 2026

Рабочее дерево поверх `a1e348c`, только синтетические SQLite.
`python -B -m unittest tests.test_attendance -q` — 6/6, exit 0. Проверены
разные сообщения для пустого кандидата и отсутствующего потока, отсутствие
побочных записей при отказе и сохранность прежней истории после перевода.
`npm test` — 91/91, exit 0. В том числе семь JS-тестов посещаемости с
сетевым отказом, закрытием/открытием, сменой занятия/аккаунта, приостановкой,
конфликтом и явным решением о применении либо отмене черновика. Отдельно
проверено сохранение нового ввода, сделанного до прихода успешного ответа
на предыдущие значения формы.
Chrome `playwright test attendance.spec.js` — 1/1, exit 0. Реальные HTTP и
сессии использованы для создания, исправления и конкурирующей записи.
Сетевой отказ воспроизведён отменой одного запроса в браузере. После 409
GET и явное принятие новой версии не отправляют POST. Передача результата
требует нового нажатия «Сохранить». Проверены Staff 1280 и Student 390.
Скриншоты — `.tmp/attendance-luna-chrome`.

`python -B -m tests.attendance_demo_coverage` в приватной копии — exit 0.
По каждому подходящему занятию выполнено пробное подтверждение через
штатный сервис с откатом savepoint. Генераторы сохранены.

| Набор | Занятий | Можно подтвердить | Заблокировано |
|---|---:|---:|---:|
| seed_contest_demo | 8 | 8 | 0 |
| seed_attestations | 8 | 8 | 0 |
| seed_demo + seed_schedule | 14 | 0 | 14 |

У последнего набора во всех 14 нет подходящего потока БРС и подтверждённой
привязки преподавателя к Staff. Одно занятие также отменено. Агрегаты без
учётных данных сохранены в `.tmp/attendance-demo-coverage.log`.
Полная Windows-регрессия `python -B -m unittest discover -s tests -q` в
приватной копии — 216/216, exit 0 (415.491 с), лог `.tmp/attendance-luna-python.log`.
В итоговом Chrome-сценарии также проверены переход к другой ведомости без
переноса ввода и возврат к исходному черновику. Дополнительный предварительный
запуск завершился тайм-аутом из-за вложенного локатора `has`, ищущего диалог
внутри карточки. Локатор исправлен, итоговый запуск прошёл 1/1, exit 0.
Очистка тестовой фикстуры теперь останавливает собственный сервер и при
исключении закрытия браузерного контекста. `git diff --check` — exit 0.

## RC4.1 №28 — учебные сроки, 18.11.2026

Sol, Windows, база `f9bda9928cbb757e0c40c4ea5ac75a685feb8cde` + рабочее дерево.
Использованы только синтетические временные SQLite. На момент этих прогонов
независимая приёмка новой функции ещё не была проведена.

- `.venv/Scripts/python.exe -B -m unittest tests.test_deadline_sources tests.test_coursework_http -q`
  — 15/15 PASS, exit 0. Реальные HTTP-маршруты: владельцы, отсутствие
  Staff-доступа к Student API, скрытые черновики, очная работа, закрытое зачисление.
- `python -B -m unittest discover -s tests -q` в отдельной приватной копии
  проекта — 218/218 PASS, exit 0, 440.380 с. Лог `.tmp/deadlines-python.log`.
  Приватное расположение необходимо действующим Windows ACL-тестам.
- `npm test` — 95/95 PASS, exit 0. Новые четыре теста покрывают проекцию,
  отмену/перенос, отсутствие влияния черновых оценок, границу дня МСК,
  незавершённое испытание, поздний ответ прежнего пользователя и защищённый 401.
- Из `tests/browser`: `npm test -- --output=../../.tmp/deadlines-full-chrome`
  — Chrome 21/21 PASS, exit 0. Включены существующие P1, комиссии,
  отрицательные полномочия, RU/EN, адаптивность, Coursework и посещаемость.
  Новый тест `deadlines.spec.js` выполнен в настоящем Chrome: Student 390 px,
  второй Student 1280 px, просрочка, пустой список, даты без времени,
  переход к конкретной работе и аттестации, перенос, отмена и изоляция.
  Перенос и отмена подготовлены штатным сервисом синтетической фикстуры;
  новый экран использует настоящие авторизованные HTTP-запросы.
- `git diff --check` — exit 0. Миграции, посещаемость и БРС не менялись.

Первоначально новый браузерный тест остановился при подготовке фикстуры:
несуществующее полномочие `policy`, затем несогласованная шкала синтетического
плана. Исправлены только данные фикстуры; целевой повтор прошёл 1/1, затем
полный набор 21/21. Эти ошибки не засчитываются как успешные прогоны.
Есть прежнее предупреждение Starlette об устаревающей поддержке httpx TestClient.

Скриншоты просмотрены визуально, переполнения нового блока не обнаружено:
`.tmp/deadlines-full-chrome/deadlines-Student-academic-47595-hedule-cancel-and-isolation/deadlines-student-390.png`
и `deadlines-empty-1280.png` в том же каталоге. Результаты Playwright находятся
в `.tmp/deadlines-full-chrome`; артефакты не входят в Git.
Отдельный браузерный переход в карточку прежней зачётки не проверялся.
Это локальные проверки Sol, а не независимая приёмка или проверка production.

После прогонов пользователь сообщил о завершении независимой приёмки Luna:
ACCEPT WITH CONDITIONS, локальный checkpoint разрешён. Новые независимые
численные результаты не заявляются. Перед checkpoint повторно выполнен
`git diff --check`; функциональные тесты заново не запускались, код не менялся.

## RC4.1 №7/26 — прогноз БРС и прогресс, 18.11.2026

Sol, Windows, база `4959669b1565503f080b8c142fae66f052eac62c` + рабочее дерево.
Проверки записи — только на синтетических временных SQLite. Миграций нет,
исторические планы и официальные оценки не обновлялись этой функцией.

До реализации прочитаны 112 локальных SQLite, в том числе приватная демокопия:
64 со схемой целочисленной БРС, 12 записей утверждённых планов обычного зачёта.
Противоречивых шкал утверждённых/черновых планов — 0; SHA-256 файлов не изменились.
Это число записей по разным копиям, не уникальных планов. Непустых WAL и ошибок
доступа не было. Дополнительно проверены две локальные базы со старыми таблицами:
утверждённых обычных зачётов до целочисленной схемы в них нет. Production/VPS
не проверены. Чтение выполнялось mode=ro&immutable=1 без изменения sidecar-файлов.

- `.venv/Scripts/python.exe -B -m unittest tests.test_brs_forecast tests.test_brs_results tests.test_attestations -q`
  — 29/29 PASS, exit 0, 14.907 с. Новый набор проверяет 49/50/51 и границы
  64/65/79/80/100; 20/20/20/40; экзамен без вычисленной оценки, обычный зачёт,
  дифзачёт, отсутствие данных и приватный черновик, владельцев, highest/latest,
  перевод с тем же и другим планом, закрытое зачисление, отказ при шкале 70.
  Новые HTTP-проверки проходят через настоящее приложение и файловую SQLite.
- `npm test` — 100/100 PASS, exit 0. Пять новых постоянных тестов: фактический
  текст и числа renderer, причины недоступности, reduced motion и неизменность
  значений, запоздалые success/401 прежнего владельца, ошибки без старых данных.
- Из `tests/browser`: `npm test -- forecast.spec.js --output=../../.tmp/forecast-chrome`
  — Chrome 1/1 PASS, exit 0.
- Там же: `npm test -- --output=../../.tmp/forecast-full-chrome`
  — Chrome 22/22 PASS, exit 0, 1.4 мин. Включены все прежние сценарии и
  новый реальный Student-сценарий: без опубликованных баллов → публикация 49 →
  исправление до 50 → обновление UI; верные условия допуска и зачёта,
  реальные progress.value, изоляция второго студента, скрытие Staff, 390 px,
  reduced motion 1280 px. Данные меняет штатный сервис синтетической фикстуры,
  браузер обращается к настоящему GET с реальными серверными сессиями.
  Обёртка Element.animate только наблюдает вызовы и вызывает исходный метод.
- Python AST изменённых файлов и `git diff --check` — PASS.

Первый новый Python-запуск: 5 PASS, 1 FAIL — тест ожидал 401 при несовпадении
владельца, существующий IdentityGuard возвращает 403. Ожидание приведено к
действующему контракту, серверная защита не менялась. Затем добавлен седьмой
тест перевода между планами и получен целевой результат 29/29.
Сохраняется прежнее предупреждение Starlette о поддержке httpx TestClient.

Снимки 390 и 1280 px просмотрены визуально, горизонтального переполнения нового
блока не обнаружено. Файлы `forecast-student-390.png` и `forecast-reduced-1280.png`
находятся в `.tmp/forecast-full-chrome/forecast-BRS-forecast-publ-5cbc3-solation-and-reduced-motion/`.
Playwright HTML-отчёт: `.tmp/playwright-p1/report/`. Артефакты не включены в Git.
Это собственные проверки Sol; независимая приёмка Luna, Linux и production
для данного изменения ещё не выполнены. Достижимый будущий итог не заявляется;
базовые 50 не отменяют действующие дополнительные требования допуска плана.

Предварительная полная Python-регрессия: 225 выполнено, 224 PASS / 1 FAIL,
exit 1 (410.775 с). `test_missing_ambiguous_and_empty_rosters` создавал
синтетический зачёт с порогом 60. В его фикстуре заменено только 60 → 50;
проверки неоднозначного состава и остальные assertions сохранены. Генераторы
демоданных и код посещаемости не менялись. После этого команда
`python -B -m unittest tests.test_brs_forecast tests.test_brs_results tests.test_attestations tests.test_attendance -q`
— 35/35 PASS, exit 0 (23.211 с).
При чтении предварительного лога обёртка также получила UnicodeDecodeError
из-за кодировки вывода дочернего Windows Python; журнал сохранён. Итоговый
прогон пишет UTF-8 через PYTHONIOENCODING. Это не маскирует падение теста.

Итоговая полная Windows-регрессия после исправления фикстуры:
`python -B -m unittest discover -s tests -q` в отдельной приватной копии —
225/225 PASS, без пропусков, exit 0 (402.658 с).
Полный журнал: `.tmp/forecast-python-final.log`; предварительный неуспешный
прогон сохранён в `.tmp/forecast-python.log`. Тестовые копии создавались в
приватном каталоге текущего пользователя для настоящих проверок Windows ACL;
после завершения удалена только созданная текущим запуском копия.
Итог: Python 225/225, JS 100/100, полный Chrome 22/22 — собственные прогоны Sol.

При подготовке локального checkpoint пользователь сообщил результат
независимого аудита Luna: ACCEPT WITH CONDITIONS. Прежние числа Sol не
обозначаются как независимо подтверждённые. Перед фиксацией повторяется
`git diff --check` и проверка состава; функциональные тесты заново не
запускаются, код и тесты не меняются. Материалы диагностики Luna сохраняются
в игнорируемой `.tmp` и не входят в коммит.

## P1 времени учебных сроков, 18.11.2026

База 7aa98fc + рабочее дерево, собственные проверки Sol, синтетические базы.
Целевые: python -B -m unittest tests.test_deadline_sources tests.test_coursework_http -q
— 15/15 PASS, exit 0. npm test — 103/103 PASS, exit 0.
Из tests/browser: npm test -- --output=../../.tmp/deadlines-time-full-chrome
— Chrome 22/22 PASS, exit 0. Предварительный целевой Chrome — 1/1 PASS.
Проверены 390 px, часы ±24 часа и правильные, отсутствие исчезновения будущего
испытания, перенос/отмена, изоляция Student, отказ API времени и восстановление.
Возврат вкладки проверяется управляемыми visibility-событиями и сдвигом часов
синтетического сервера, не физическим сном Windows. Валидность тестовых сессий
при сдвиге поддерживает только фикстура. JS проверяет полночь МСК, точный срок
до/после, дату без времени, неправильное/отсутствующее время и RTT >5 секунд.
Семантика: снимок с точностью серверной секунды и доставкой до 5 секунд;
обновляется каждые 30 секунд. Это не непрерывный секундный таймер. Нет fallback
на часы устройства. Независимая проверка Luna и production не выполнены.

Полная Python-регрессия: python -B -m unittest discover -s tests -q в отдельной
приватной копии — 225/225 PASS, exit 0 (428.807 с). Лог .tmp/deadlines-time-python.log.
После уточнения подписи полной датой выполнен целевой Chrome повтор:
1/1 PASS, exit 0, .tmp/deadlines-time-final. Полный набор ранее прошёл 22/22.
Итоговый JS — 103/103. git diff --check — PASS. Это собственные прогоны Sol.

Доработка после Luna: прежний ACCEPT WITH CONDITIONS сохранён как история.
Теперь общий бюджет всех источников и времени — 5 секунд от начала загрузки,
а не RTT последнего GET. Это объединение отдельных ответов, не атомарный снимок.
Один watchdog 1 с обнаруживает задержку исполнения более 2 с и обновляет данные;
периодическое обновление 30 с. Pageshow/focus/visibility очищают список до
загрузки, повторные события объединяются во время свежего запроса и 250 мс
после завершения. Смена владельца отменяет старую операцию и таймер.
Во время полной остановки JS скрыть уже нарисованное невозможно; проверка
выполняется при следующем обработанном событии или таймере. Часы сервера должны
быть корректны. Физический сон Windows не подтверждён.

Итог текущей доработки после Luna: Python tests.test_deadline_sources — 2/2,
JS npm test — 105/105, целевой Chrome — 1/1, повторный полный Chrome — 22/22,
все exit 0. Полная Python-регрессия в этой клиентской итерации не повторялась;
225/225 относится к предыдущей проверке. Первый полный Chrome: 21 PASS /
1 timeout RU/EN (90000 мс), exit 1; причина не установлена. Приложение и
RU/EN-тест для повторного прогона не менялись. Артефакты сохранены в
.tmp/deadlines-lifecycle-full; успешный повтор — .tmp/deadlines-lifecycle-repeat.
В браузере pageshow/focus проверены серией реальных событий с одним запросом
времени; окно 250 мс пройдено виртуальными часами, без sleep. Задержка
watchdog и смена аккаунта проверены детерминированным JS-тестом.
Физический сон Windows не проверялся; нет гарантии скрытия до первой
отрисовки при возобновлении браузера или во время полной остановки JS.
13 исходных изменённых файлов сохранены, commit не создавался.

## Коммит P1 и подготовка релизной документации

Пользователь сообщил Luna ACCEPT WITH CONDITIONS и разрешил один локальный
commit P1: ea4abbca210387e4137d95c5e5f212497b332aaf, ровно 13 файлов.
Ветка main, база 7aa98fc; индекс до фиксации пустой, после неё дерево чистое.
Staged check и проверка артефактов пройдены. Новые функциональные прогоны
в операции фиксации/документации не выполнялись: сохраняются прежние
целевые Python 2/2, JS 105/105, Chrome повтор 22/22; RU/EN timeout не скрыт.

Отдельная незакоммиченная документация: README/RELEASE актуализированы
для 24 миграций; полный порядок остановки, backup, копии, apply, прав,
запуска, proxy/TLS/cookies, health и login, restore/отзыва сессий и rollback.
Отзыв сессий — операторский шаг на проверенной восстановленной копии,
не новая возможность CLI; Linux-проверка ещё требуется. Отдельно обозначена
несовместимость текущего restore CLI со старым snapshot 0014 и отсутствие
этой команды в RC3.1. Старая инструкция тестовой миграции 0020 заменена
новой после последней (сейчас 0025). Конкурсный комплект — docs/contest-kit.md;
короткий вариант и критические действия есть в RELEASE, который включается
в ZIP, в отличие от docs. Архив не создавался.

Диагностика среды: wsl --status вернул exit 50 «подсистема не установлена»;
Docker executable не найден. Ничего не устанавливалось и не настраивалось.
Нет подтверждённого доступного Linux-стенда. CLI/HTTP/Linux/systemd/cron/MAILTO
и текущий VPS — NOT VERIFIED для этой операции. Подготовлен только план.
Не запускались миграции/seed/backup/restore, не использовались реальные данные.
Gemini worktree и infra/vps-deployment не читались и не менялись.

## 19.11.2026 — №8, поиск свободных аудиторий

База main `7f5e6c5d48fb65f8d88a819042698c3db709d405`, текущий незакоммиченный
patch. Только временные синтетические SQLite. Контракт: room-availability.md.

Фактически выполнено в Windows:

- `.venv/Scripts/python.exe -B -m unittest tests.test_rooms -q`: 7/7 PASS,
  exit 0. API Student/Staff, отсутствие сессии, whitelist полей/no writes,
  границы и фильтры, отмены/переносы занятий, аттестация/отмена/новая аудитория,
  правила/ограничения, обновление заполненной 0024 и повтор, откат ошибочной 0025,
  integrity_check и foreign_key_check.
- `.venv/Scripts/python.exe -B -m unittest tests.test_rooms tests.test_attendance -q`:
  13/13 PASS, exit 0. Дополнительный тест обновления Coursework с 0021: 1/1 PASS.
- `npm test`: 108/108 PASS, 0 FAIL/SKIP, exit 0. Новые постоянные тесты проверяют
  фильтры, ошибки, центральный 401, поздние success/401 прежнего владельца,
  очистку при смене роли, разделение known/unknown и безопасный вывод текста.
- `node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/playwright.config.js`:
  **23/23 PASS**, exit 0, реальный Chrome/Uvicorn. Новый rooms.spec.js отдельно
  также 1/1 PASS. Student 390/768 px, реальные HTTP, клавиатурная отправка,
  RU/EN, вместимость, known/unknown, пустой результат, ошибка сети,
  отсутствие горизонтального overflow, отсутствие Student-раздела у Staff.
  Существующие Coursework, БРС, сроки, посещаемость и остальные сценарии прошли.
- Python AST и `node --check` изменённых модулей: PASS. `git diff --check`: PASS.

Диагностика не скрыта: начальный Python-запуск с ограниченным loopback прерван;
повтор с доступным loopback прошёл целевые тесты. Первая новая миграционная
фикстура не закрывала sqlite3.connect: исправлено явным closing, затем 7/7 PASS.
Промежуточная полная регрессия: 232 теста, 5 FAIL и 1 ERROR из-за старых ожиданий
последней миграции и реконструкции исторической схемы. Исправлены ожидания
(0024 сохранена, 0025 добавлена), фикстуры удаляют обе новые схемы только на своих
синтетических копиях. Все пять соответствующих миграционных тестов отдельно PASS.
Окончательный общий результат приведён ниже.
Первый Chrome-запуск из корня выбрал другую версию CLI; успешные прогоны выполнены
существующим локальным CLI из tests/browser/node_modules, зависимости проекта
не изменены. Ошибка нового E2E при смене языка устранена повторным заполнением
фильтров после существующего центрального обновления сессии.

Артефакты вне Git: `.tmp/rooms-js.log`, `.tmp/rooms-chrome.log`,
`.tmp/rooms-python.log`, `.tmp/rooms-python-final.log`,
`.tmp/rooms-python-verified.log`, `.tmp/playwright-p1/results/` и report/.
Скриншоты: rooms-390.png и rooms-768.png в подкаталоге rooms-* результатов.
Токены фикстуры передаются по закрытому stdin/stdout-каналу теста, в отчёт/логи
не записываются. Trace выключен. Приватные тестовые копии полной регрессии
удаляются в finally после завершения дочернего процесса; рабочая база не используется.

Linux/VPS/production и независимая приёмка Luna — NOT VERIFIED в этой задаче.
Результаты Sol не обозначены независимыми. Заполнение финальной демобазы 50 комнатами
и проверка реальных правил университета не выполнялись. Коммита нет.

### Заключительная полная Python-регрессия №8

`.venv/Scripts/python.exe -B -m unittest discover -s tests -v` на приватной
копии backend/frontend/tests: **232/232 PASS**, 0 FAIL/ERROR/SKIP, 425.534 s,
**exit code 0**. Журнал: `.tmp/rooms-python-verified.log`. После завершения
дочернего процесса приватная копия удалена finally; runner также завершился exit 0.
Этот прогон включает исправленные исторические миграционные фикстуры,
backup/restore/rollback, Coursework, БРС, посещаемость, расписание и все 7 RoomTests.
Предыдущий уточняющий прогон завершился с единственным неверным ожидаемым списком
в test_identity (0024 ошибочно заменена вместо добавления 0025); исправлено до
заключительного прогона. Успехом эти промежуточные прогоны не считаются.

Последняя правка frontend — явный EN-текст центрального уведомления о завершённой
сессии — повторно проверена `npm test`: 108/108, exit 0, и rooms Chrome: 1/1, exit 0.
Полная Chrome-регрессия: 23/23, exit 0; журнал содержит явный EXIT_CODE=0.
Общий незакоммиченный состав: 39 текстовых файлов. Индекс пуст. В изменениях нет
SQLite, backup, .env, ключей, логов и снимков экрана; эвристическая проверка
приватных ключей/форматов токенов совпадений не дала (не заменяет аудит безопасности).
Git diff --check: PASS. Linux и независимая приёмка Luna остаются NOT VERIFIED.

## №8 — исправления после REJECT Luna

База main 7f5e6c5d48fb65f8d88a819042698c3db709d405, 39 незакоммиченных путей.
Исходный test_upgrade_filled_0024_and_migrator_repeat перед исправлением
локально: 1/1 PASS. Сбой Luna здесь не воспроизведён; теперь тест не полагается
на неявный полный каталог, проверяет наличие/полное содержимое backup, и
ошибочная миграция выполняется отдельным независимым сценарием.

- `.venv/Scripts/python.exe -B -m unittest tests.test_rooms -v`: 8/8 PASS,
  exit 0; .tmp/rooms-luna-python-target.log. Только синтетические SQLite.
- `npm test`: 109/109 PASS, 0 FAIL/SKIP, exit 0; .tmp/rooms-luna-js.log.
  Новый тест проверяет status.textContent для количества, unknown, empty,
  error и очистки; Chrome дополнительно проверяет реальное подключение к DOM.
- Полная Python-регрессия и Chrome запущены; заключительные результаты ниже.

Полный Python выполняется на отдельной защищённой копии backend/frontend/tests
в профиле Windows, с удалением только этой копии в finally. Рабочая SQLite
и реальные backup не открываются. Linux и реальная речь скринридера NOT VERIFIED.
Независимая повторная приёмка Luna пока NOT VERIFIED.

Chrome после исправлений Luna: `node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/playwright.config.js`
— **23/23 PASS**, exit 0, 1.6 min; `.tmp/rooms-luna-chrome.log`.
Использованы реальные Uvicorn и HTTP health 200 на временных синтетических базах.
Проверены новые live-region объявления в DOM на 390/768 px, RU/EN, empty/error;
существующие Student/Staff сценарии прошли. Настройки сети/безопасности не менялись.
Синтаксис изменённых Python/JS: PASS; 39 путей, индекс пуст, запрещённых типов
файлов в составе изменений нет. Скринридер NVDA/JAWS вручную НЕ проверялся.

### Итог повторных собственных проверок №8 — 20.11.2026 МСК

Полная Python-регрессия: `C:/Projects/MGIMOv/.venv/Scripts/python.exe -B -m unittest discover -s tests -v`
из отдельной приватной копии исходников — **233/233 PASS**, 0 FAIL/ERROR/SKIP,
426.047 s, exit 0. Runner завершился exit 0 после finally/очистки своей копии.
Журнал: `.tmp/rooms-luna-python-full.log`. Включает оба независимых миграционных
сценария №8, полный backup/restore/rollback и существующие регрессии.
Целевые Python: 8/8; JS: 109/109; Chrome: 23/23; все exit 0.
Git diff --check PASS; индекс пуст; исходные 39 путей сохранены, новых путей
сверх этого состава нет. Изменения итерации: tests/test_rooms.py,
frontend/js/rooms.js, tests/rooms.test.js, tests/browser/rooms.spec.js и
существующие документы результатов/координации. Production-миграция и мигратор
не изменены. QR и Gemini не затрагивались; нет commit/push/merge/tag/ZIP/deploy.
Linux, NVDA/JAWS и повторный независимый прогон Luna NOT VERIFIED.
Описанный Luna исходный сбой локально не воспроизведён; причина различия сред
не установлена. Явная фикстура теперь не может принять обновление без 0025
или использовать backup, не подтвердив его существование и содержимое.

20.11.2026: пользователь сообщил независимый вердикт Luna ACCEPT и разрешил
локальный checkpoint №8. Это решение о приёмке не означает нового собственного
прогона или подтверждения Linux/NVDA/JAWS. Состав независимых динамических
прогонов в этом сообщении не уточнён. Прежний REJECT заменён для текущего diff.

## 20.11.2026 — QR-посещаемость V1

База main 16374b071d542f0824a2436637cc38151ccd574f, незакоммиченный diff.
Только собственные синтетические SQLite, без файлов/worktree Luna и Gemini.

Фактически выполнено:

- `.venv/Scripts/python.exe -B -m unittest tests.test_attendance_qr -v`: **12/12 PASS**,
  exit 0, 6.454 s в последнем прогоне. .tmp/qr-target-final.log. Авторизация/CSRF,
  чужой студент, реальные Student/Staff-сессии, все ручные статусы, собственная
  история, токены только в хешах, preview без отметки, expiry/revoke/rotation,
  logout издателя, актуальность состава/занятия, issue replay, конкурентные
  одинаковые/разные Student запросы, конкуренция с ручной отметкой, rate limit,
  обязательный audit/receipt с rollback, включая RAISE IGNORE. Дополнительно
  в последнем прогоне проверены конкурентный первый выпуск одного ключа и
  отказ повтору issue после отзыва назначения; только один ответ содержит код.
- Связанный набор `tests.test_attendance_qr tests.test_attendance tests.test_rooms
  tests.test_coursework_http`: 38/38 PASS до добавления последнего негативного
  QR-сценария; результат исторический, не подменяет последнюю полную регрессию.
- Полная `.venv/Scripts/python.exe -B -m unittest discover -s tests -v` на приватной
  копии backend/frontend/tests: **245/245 PASS**, 0 FAIL/ERROR/SKIP, 393.277 s,
  exit 0; .tmp/qr-python-full.log. Включает backup/restore/rollback с новой
  схемой и миграции. Приватная копия создаётся с защитой ACL, cleanup только
  собственного каталога в finally после завершения subprocess. Последующее
  расширение assertions гонки выпуска проверено целевым прогоном 12/12.
- `npm test`: **116/116 PASS**, 0 FAIL/SKIP, exit 0; .tmp/qr-js.log. Безопасный SVG,
  удаление fragment, отсутствие авто-отметки, двойная отправка, account/role
  switch, поздние success/401, logout во время запроса, явный network retry,
  сохранение request_key при неопределённости и новый ключ для новой операции.
- Полный `node tests/browser/node_modules/@playwright/test/cli.js test --config
  tests/browser/playwright.config.js`: **24/24 PASS**, exit 0, 1.5 min;
  .tmp/qr-chrome-full.log. Реальные HTTP/Uvicorn, health 200, существующие
  Student/Staff, расписание, БРС, Coursework, посещаемость, сроки, аудитории.
- Расширенный `... attendance-qr.spec.js`: **1/1 PASS**, exit 0, 1.1 min;
  .tmp/qr-chrome-target.log. Staff 1280/Student 390, явная отметка, ручное
  исправление/приоритет, отзыв/expiry, чужой студент, удаление URL fragment,
  повтор после реального сетевого отказа и RU/EN. Авторизация/бизнес-ответы
  не подменялись; route.abort использован только для имитации сетевого отказа.
- AST Python / node --check, git diff --check: PASS. `pip check`: PASS.

Миграция: заполненная 0025 с подтверждённым составом и ручной историей
обновлена реальным migrator до 0026, старые события совпали, повтор — no-op,
integrity_check=ok, foreign_key_check пуст. Копия backup 0025 с ошибочной 0026
полностью откатывается: logical dump, схема, триггеры и история не изменены.

Артефакты .tmp не отслеживаются Git. Снимки без действующих QR:
.tmp/playwright-p1/results/attendance-qr-*/qr-student-confirmed-390.png и
qr-staff-revoked-1280.png. Trace выключен; bearer tokens/сессии не пишутся в
отчёты, сетевые URL или логи. PNG не создаются/не используются генератором QR.

NOT VERIFIED: независимая приёмка Luna, Linux/production/VPS, реальное считывание
QR камерой телефона через доступный телефону HTTPS-origin, ручной скринридер.
Chrome вводит реальную выданную ссылку, не имитирует её декодирование камерой.
Стандартный генератор проверен матрицей/визуальным выводом, физическое сканирование
не заявляется выполненным. Никакой гарантии физического присутствия нет.

## QR V1 — P1/P2 после REJECT Luna, 20.11.2026

База main 16374b071d542f0824a2436637cc38151ccd574f, 43 незакоммиченных пути.
До правок дефекты воспроизведены: .tmp/qr-p1-before.log — cleanup FK ERROR
(exit 1); .tmp/qr-p2-before.log — неверный present при текущем absent (exit 1).
Эти отрицательные прогоны не считаются успешными проверками.

После исправлений на временных синтетических SQLite:

- `.venv/Scripts/python.exe -B -m unittest tests.test_attendance_qr -v`: 15/15 PASS,
  8.035 s, exit 0; .tmp/qr-fix-target.log. Сюда входят 0025→0026 с историей,
  backup, повтор migrator, rollback ошибочной 0026, integrity/FK и P2 повтор
  исходного receipt после ручного absent без новых событий/receipt.
- Отдельно три test_attendance_qr.AttendanceQRTests: test_cleanup_cli_after_qr_uses_unmodified_production_command,
  test_cleanup_expired_issuer_preserves_qr_history_and_other_sessions,
  test_logout_then_physical_cleanup_rejects_token_before_and_after: 3/3 PASS,
  2.366 s, exit 0; .tmp/qr-fix-cleanup.log. Реальные cleanup/main с parser и
  --confirm-cleanup; только часы фикстуры инжектированы для датированных данных.
  Удалены issuer и другие просроченные сессии, неизменны QR sessions/receipts/events,
  integrity_check=ok, foreign_key_check пуст, QR даёт 409 до и после удаления
  при неизменном времени ещё не истёкшего токена.
- `npm test`: 117/117 PASS, exit 0; .tmp/qr-fix-js.log.
- `node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/playwright.config.js attendance-qr.spec.js`:
  1/1 PASS, 5.3 s, exit 0; .tmp/qr-fix-chrome-target.log. Реальные HTTP/Uvicorn,
  старый receipt outcome=present при текущем absent, manual_mark, корректный RU
  и EN текст, без перезаписи ручной отметки. Модалка закрывается перед сменой языка.

Полные Python/Chrome прогоны запущены отдельно, результаты записываются ниже.
Метаданные сохраняемой data/deanery.sqlite3: только 0001_initial, 0026 не
применялась; custom MGIMOV_DB_PATH отсутствует. Чтение immutable, рабочие данные
не выводились. Базы/worktree Luna и Gemini не открывались. Другие сохраняемые
внешние базы NOT VERIFIED; при старой применённой 0026 нужен отдельный переход.

### Заключительный результат P1/P2

Полная `.venv/Scripts/python.exe -B -m unittest discover -s tests -v` на
приватной копии: **248/248 PASS**, 0 FAIL/ERROR/SKIP, 397.613 s, exit 0.
Runner также завершился exit 0 после cleanup своей копии. Журнал:
.tmp/qr-fix-python-full.log. Полный Chrome: **24/24 PASS**, 1.8 min, exit 0;
.tmp/qr-fix-chrome-full.log. Целевой QR Chrome: 1/1 PASS, 5.3 s, exit 0.
JS: 117/117; QR HTTP/SQL: 15/15; cleanup отдельно: 3/3, все exit 0.
Git diff --check / AST / node --check: PASS. Индекс пуст, сохранены 43 пути.

SHA-256 сохраняемой data/deanery.sqlite3 до и после работы совпал; чтение
метаданных и checksum не изменило файл. 0026 к ней не применялась.
Исправлены 6 файлов кода/тестов: backend/migrations/0026_attendance_qr.sql,
backend/attendance_qr.py, frontend/js/attendance-qr.js, tests/test_attendance_qr.py,
tests/attendance-qr.test.js, tests/browser/attendance-qr.spec.js; дополнены
существующие docs/attendance-qr.md, test-results.md, ai-development-log.md и
три документа координации. 0001–0025, cleanup_sessions.py и глобальная FK-защита
не менялись. Нет commit/merge/push/tag/ZIP/deploy или подключений к VPS.

NOT VERIFIED: повторный независимый аудит Luna, Linux, физическая камера
телефона/публичный HTTPS и ручной скринридер, сохраняемые базы за пределами
проверенных мест текущего проекта. Worktree Luna/Gemini не открывались.

20.11.2026: пользователь сообщил независимый ACCEPT Luna для QR V1 и разрешил
локальный checkpoint 43 путей. Это заменяет прежний независимый REJECT;
собственные результаты остаются Python 248/248, JS 117/117, Chrome 24/24 PASS.
В операции фиксации функциональные тесты заново не запускались. Состав
независимых динамических прогонов не уточнён; Linux/телефон/NVDA/JAWS не
объявляются проверенными. Перед коммитом повторены diff --check, состав
индекса и проверка защищённых файлов/исключённых артефактов.

## Интеграция только калькулятора БРС, 20.11.2026

Основа main 03dfcc25ca4874bf86e44eeb7cb12b443a166a13. Источник Gemini:
07de95b8ff0aa308626ec56cec4b17ceddecb10e (исправления) вместе с реализацией
родительского 8c22536c1b608ff1751d41742c5b561941e16488. Worktree Gemini
проверен чистым; чужие файлы не менялись. Демогенератор не переносился.

Применён предметный diff от общей базы 7aa98fc, без замены app.py/HTML целиком:
три ресурса калькулятора добавлены к текущим ASSETS, CSS — к текущему HTML.
QR, аудитории, CSP/IdentityGuard и миграции сохранены. Статус review, коммит
не разрешён. Требуется независимая приёмка объединённого diff.

Проверки: Python контракт/прогноз/QR/аудитории 32/32 PASS, exit 0; JS 124/124
PASS; standalone Chrome калькулятора PASS, exit 0 (реальный HTTP, 49→50,
integer-only, empty/zero, RU/EN, 390 px, reset, network failure, account switch).
Chrome регрессия QR/аудитории 2/2 PASS, exit 0. Полная Python/Chrome-регрессия
в этой ограниченной интеграции не запускалась; Linux/VPS NOT VERIFIED.
Логи и review diff в .tmp/calculator-integration*. Индекс пуст, HEAD сохранён.

## DEMO-FINAL — финальная синтетическая конкурсная демосреда

**Рабочая ветка:** `demo/contest-final-data`; основа `16374b071d542f0824a2436637cc38151ccd574f`.
**Окружение:** Python 3.13 из `C:\Projects\MGIMOv\.venv`, Windows 11; все SQLite
создавались только в текущем worktree `.tmp`, без рабочей базы и VPS.

- `python -B -m py_compile backend/commands/seed_attestations.py backend/commands/seed_contest_final.py backend/room_routes.py tests/test_contest_final_demo.py` — PASS, exit 0.
- `python -B -m unittest -v tests.test_contest_final_demo` — **5/5 PASS**, exit 0. Проверены свежие миграции текущего checkout, целостность/FK, 20 аккаунтов и валидность всех паролей по Argon2-хешам, роли, BRS 49/50/51, разделение прогноза/официального результата, prior-semester debt, Coursework, переведённая историческая ведомость, Staff scope, поиск помещений и обратная совместимость старого seed без параметров.
- `git diff --check` — PASS, exit 0.
- Прямая `prepare()` на Windows — PASS: приватный каталог и DPAPI-файл созданы, миграционный статус (25), 20 аккаунтов и 51 помещение проверены; временный экземпляр удалён. Это тест функции подготовки, а не проверка полного интерактивного CLI.
- Попытка Uvicorn + HTTP smoke на новой временной SQLite: серверный процесс стартовал, однако клиентский connect на `127.0.0.1` завершался `WinError 10013`. `/api/health` за 20 секунд не получен; процесс остановлен, временная папка удалена. HTTP, входы в браузере и browser E2E — **NOT VERIFIED**.
- `TestClient` в этом Windows-окружении зависал до первого запроса; отдельные suite с TestClient не запускались повторно. Это ограничение среды, не утверждение о дефекте продукта.
- JS/Chrome, мобильные размеры, Linux, QR-схема и полный регрессионный набор не запускались; frontend-код не изменялся.

Из-за невозможности выполнить loopback HTTP smoke генератор готов к повторной проверке,
но конкурсная демосреда пока не считается полностью подтверждённой. Полную инструкцию
и матрицу сценариев см. [contest-final-demo](contest-final-demo.md).

### DEMO-FINAL — исправления по первому аудиту, 20.11.2026

Worktree `demo/contest-final-data`, база `de1c8f2ce51e685f60291bc60dfbc525ac029488`.
Независимое воспроизведение показало дефект `no_exam_students={'s04'}`:
базовый seed пытался создать специальный экзаменационный слот для студента без
экзаменационного назначения, используя слот предыдущего студента. Исправление
пропускает оба специальных сценария экзамена для исключённого студента; тест
подтверждает отсутствие слотов и событий S04.

- `.venv\Scripts\python.exe -B -m unittest -v tests.test_contest_final_demo` —
  **10/10 PASS**, exit 0, 52.703 s. Включает полную сверку применённых миграций
  с текущим реестром (без жёсткой привязки к 0025), существующий файл/повторный
  запуск, путь вне `.tmp` и неверное расширение, появление конкурирующего файла
  после preflight, отказ перезаписи, очистку staging после искусственной ошибки,
  no-exam S04, два независимых запуска и проверку приватности credentials,
  аккаунты, BRS/Coursework/attendance и room availability. Временные SQLite
  синтетические и удаляются фикстурами.
- Полная команда `python -B -m unittest discover -s tests -v` — **NOT VERIFIED**:
  прогон остановлен вручную после зависания на первом
  `test_anonymous_staff_idor_query_json_and_mutations`; следующего вывода за
  70 секунд не появилось. Это не PASS и не результат полного набора.
- `git diff --check` и компиляция изменённых Python-файлов — результаты записаны
  в review-handoff после финального локального прогона.

Генератор строит базу в случайном staging-файле, проверяет данные и только затем
атомарно публикует путь без замены появившегося конкурентного файла. Ошибка до
публикации удаляет staging; ошибка подготовки/проверки DPAPI удаляет только
файлы созданного ею приватного запуска. На Windows публикация использует
`os.rename`, на POSIX — hard-link create-if-absent и удаление staging-имени.
Это локальные Windows-проверки; POSIX-путь и Linux-права NOT VERIFIED.

## Интеграция финального демогенератора, 20.11.2026 — передача на аудит

Основной HEAD acdbfcdef3ce9c9fa3cbf7cf37f479f01b1660d8 (main, чист до переноса).
Источник demo/contest-final-data: de1c8f2ce51e685f60291bc60dfbc525ac029488 и
b9f3b9cb4a6183d8349d8af54f5696f33b5a5aa3; исходный worktree проверен чистым,
не изменялся. Пользователь сообщил ACCEPT WITH CONDITIONS Opus для источника;
это не независимый ACCEPT текущей интеграции. Калькулятор уже принят и находится
в main; прежние записи о запрете его коммита относятся к предыдущему этапу.

Перенесены 13 путей источника. Документы сведены добавлением истории к main,
а не заменой старой веткой. SQL поиска вынесен в available_rooms без изменения
семантики/авторизации. Дополнительно: итоговый seed исключает экзаменационные
слоты S04 вместе с S01 (проверено на финальной базе), новая проверка backup/restore
демобазы, собственная приватная Chrome-фикстура и её включение в полный набор.
Всего интеграция затрагивает 16 путей. Миграции 0001–0026, cleanup_sessions,
приложение, авторизация, QR, калькулятор и frontend-ресурсы не изменяются.

Целевые Python 35/35 PASS, exit 0; JS 124/124 PASS, exit 0; standalone Chrome
калькулятора PASS, exit 0; повторный Chrome демогенератора/Coursework 9/9 PASS,
exit 0. Полная регрессия записывается ниже после фактического завершения.
Реальные HTTP-входы Student/Staff, изоляция Coursework, calculator, rooms 390 px,
QR из нового seed (S07 present; S02 отказ) подтверждены Chrome. Учётные данные
передаются только через приватный IPC, traces отключены; скриншоты без токенов.

История неуспешных прогонов сохранена: первая собственная browser-фикстура
ожидала отсутствующий __init__.py; затем тест искал журнал преподавателя в
деканатском списке без соответствующих прав. Исправлен переход через штатную
кнопку «Посещаемость», права не расширялись. Первый полный Chrome: 23 PASS,
2 timeout, exit 1. Первый добавленный backup-тест дал ошибку строгой ACL-проверки
в tempfile-каталоге; используется существующая защищённая backup-фикстура,
повтор 35/35 PASS. Оборванный запуск полной Python-регрессии без exit code
не считается PASS; повтор запущен с отдельным устойчивым журналом.

Linux/systemd/VPS и реальная камера QR/публичный HTTPS NOT VERIFIED.
Тестовый clock используется только в изолированной HTTP-фикстуре (21.11, 09:15).
Реальный QR требует времени занятия: у seed g-a/law 09:00–10:00 МСК даты-якоря.
Для другого времени нужна штатная подготовка расписания и подтверждение состава,
не отключение серверного ограничения. Демобазы только синтетические; production,
реальные backup, worktree Gemini/Luna не менялись. Коммит/публикация запрещены
до независимого ACCEPT интеграции. Публичный выпуск не разрешён.

Итоговый полный Chrome: 25/25 PASS, exit 0 (1,9 мин); журнал
`.tmp/demo-integration-chrome-final-full.log`. Калькулятор standalone также PASS.
Первичные тайм-ауты не включены в число успешных прогонов.

Команды интеграционной проверки (Windows; Python — приватная копия проекта,
созданная PrivateDemoDirectory в профиле, только синтетические SQLite):

```text
C:\Projects\MGIMOv\.venv\Scripts\python.exe -B -m unittest -v tests.test_contest_final_demo tests.test_attendance_qr tests.test_rooms tests.test_brs_calculator_contract
C:\Projects\MGIMOv\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
npm test
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/playwright.config.js
MGIMOV_PLAYWRIGHT_MODULE=<installed tests/browser/node_modules/playwright/index.mjs>
MGIMOV_TEST_PYTHON=<main .venv/Scripts/python.exe>
node tests/browser/brs-calculator.e2e.mjs
git diff --check
```

Полные журналы без credentials/session IPC: `.tmp/demo-integration-python-targeted-final.log`,
`.tmp/demo-integration-python-full-final.log`, `.tmp/demo-integration-js.log`,
`.tmp/demo-integration-chrome-final-full.log`, `.tmp/demo-integration-calculator-chrome.log`.
Chrome HTML/report и скриншоты — `.tmp/playwright-p1/`; они исключены из Git.

Окончательная регрессия интеграции: Python unittest discover 261 PASS / 0 FAIL /
0 SKIP, 500,348 с, exit 0; целевые Python 35 PASS / 0 FAIL / 0 SKIP, exit 0;
JavaScript 124 PASS / 0 FAIL, exit 0; полный Chrome 25 PASS / 0 FAIL, exit 0;
standalone калькулятора Chrome PASS, exit 0. В полном Python прошли миграции,
backup/restore и репетиция двух rollback. Ранее оборванный журнал и неуспешные
браузерные попытки сохранены отдельно, их результаты не заменяются PASS.

Синтетическая база: 11 Student + 9 Staff, 50 добавленных аудиторий (51 всего),
две Coursework, БРС 49/50/51, долг S02, попытки/пересдачи, отмена/перенос занятий,
составы и история посещаемости, S04 без слотов/событий экзамена по праву.
integrity_check=ok, foreign_key_check=[], весь реестр 0001–0026 применён без
pending. Подтверждены no-overwrite/repeat, удаление собственного staging при
ошибке, реальные Windows ACL и DPAPI. Новых незакрытых P0/P1/P2 в интеграции
по выполненным проверкам не обнаружено; это не независимая приёмка безопасности.

READY FOR INDEPENDENT AUDIT. HEAD acdbfcdef3ce9c9fa3cbf7cf37f479f01b1660d8,
main; 16 незакоммиченных путей (11 modified + 5 untracked), индекс пуст.
Коммита, merge, push, tag, ZIP, deploy и обращения к VPS не было.
Для публичного релиза сохраняются Linux/systemd/права, эксплуатационный
restore/rollback, уведомления и реальный публичный HTTPS/камера — NOT VERIFIED.
