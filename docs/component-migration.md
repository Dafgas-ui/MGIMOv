# Происхождение компонентов

Источник: C:\Projects\AI-Student-Dashboard. Это справочная запись, не runtime-путь.
Ни один исходный модуль, база, .env, .git или виртуальное окружение не подключены к приложению.

| Новый компонент | Источник | Реальные изменения и зависимости |
|---|---|---|
| backend/security/passwords.py | backend/auth/passwords.py | Сохранены hash_password, verify_password, valid_password, Argon2id (time_cost=3, memory_cost=65536, parallelism=4), semaphore. Удалены secrets и создание DUMMY_HASH при импорте. Зависимость argon2-cffi. Авторизация не переносилась |
| backend/migrations/manager.py | backend/migrations/manager.py | Перенесён автономный менеджер без содержательных изменений: контрольные суммы, проверка схемы, транзакции, verified_backup. Каталог вычисляется из нового __file__; зависимости только стандартной библиотеки. Новые CLI и SQL написаны отдельно |
| frontend/js/utils/dates.js | script.js: calendarKey, overlaps; принципы dateForDay/changeWeek | calendarKey и формула пересечения адаптированы, добавлена строгая валидация, parseDate/addDays/weekDates написаны независимо. Нет DOM, tasks, statistics, state или storage. Локальный календарный ключ не является UTC timestamp |
| backend/db.py | backend/auth/store.py: connection | Самостоятельный минимальный аналог транзакционного шаблона: Settings, existing-file mode, foreign_keys, read-only и rollback. Убрана зависимость от старой миграции аккаунтов |
| frontend/css/tokens.css и base.css | style.css: переменные и карточное оформление | Перенесены палитра и визуальный подход, layout/адаптивность написаны отдельно; нет старых DOM-id, внешних шрифтов и изображений |

Не перенесены: script.js целиком, общий API, storage.py со снимком, старый sync,
iframe, browser namespaces, задачи, статистика, CSV UI, Telegram, пользовательские данные,
старые миграции, логи, секреты, зависимости из старого окружения и Git-история.

Перед первым коммитом повторно сверены SHA-256 четырёх исходных файлов:
script.js, passwords.py, migrations/manager.py и style.css. Изменений не обнаружено.
Остальные исходные файлы не изменялись командами этой задачи; полного сравнения всего
исходного диска и runtime-данных работающего Dashboard не выполнялось.

Версии прямых библиотек взяты из исходного проекта, зависимости установлены независимо
и зафиксированы по фактически проверенному окружению в constraints.txt.
Лицензионный аудит всех транзитивных библиотек не завершён; это условие перед публикацией.
