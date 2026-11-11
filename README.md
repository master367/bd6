# Edge Drowsiness Model Catalog

Учебная рекомендательная платформа для Assignment 6, Advanced Databases.
Пользователь выбирает методы анализа временных рядов для детекции сонливости с учётом
типа сигнала, бюджета памяти и допустимой задержки на заданном эталонном устройстве.

Основной результат: MongoDB с валидаторами и обоснованными индексами, REST API на FastAPI,
CLI, аналитические агрегации и воспроизводимый эксперимент с `explain`.
Все модели в генераторе и их характеристики **синтетические**. Нейросети не обучались;
приложение не выполняет детекцию сонливости по камере или датчикам.

## Что реализовано

- Регистрация, вход, Argon2id-хеширование паролей, JWT на 30 минут.
- Профили пользователей и вложенные требования к устройству.
- CRUD каталога: изменения доступны администраторам; удаление архивирует запись.
- Полнотекстовый поиск, категории, сигналы, фильтры памяти и задержки.
- История взаимодействий с курсорной пагинацией и изоляцией пользователей.
- Защита от повторной записи события по `request_id`, в том числе при гонке запросов.
- MongoDB `$jsonSchema`, уникальные, составные, multikey и text-индексы.
- Агрегации популярности, последних пользовательских оценок, активности и статистики модели.
- Базовый подбор по ограничениям устройства; план развития алгоритма описан в proposal.
- Генератор тестовых данных, CLI и тесты на настоящей MongoDB.

## Быстрый запуск в Windows PowerShell

Требуется Python 3.12+ и доступный MongoDB 8.x. Команды выполняются из корня проекта.
Если `.venv` уже существует, шаг создания окружения пропускается.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe scripts\init_env.py
.\.venv\Scripts\python.exe -m app.manage init-db
.\.venv\Scripts\python.exe -m app.manage seed --users 100 --models 60 --interactions 100000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

В `requirements.lock` закреплено проверенное окружение, включая инструменты тестирования.
Файлы `requirements.txt` и `requirements-dev.txt` описывают допустимые диапазоны зависимостей
для осознанного обновления окружения.

Если MongoDB слушает другой адрес, измените `MONGODB_URI` в `.env`.
`scripts/init_env.py` создаёт случайные секреты и сохраняет существующий `.env`.
База приложения называется `edge_catalog`; другие базы не изменяются.

- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI: <http://127.0.0.1:8000/openapi.json>
- Проверка подключения: <http://127.0.0.1:8000/health>

## Демонстрация через CLI

Откройте второй терминал в корне проекта при работающем API:

```powershell
.\.venv\Scripts\python.exe -m app.cli demo
.\.venv\Scripts\python.exe -m app.cli catalog --signal eeg
.\.venv\Scripts\python.exe -m app.cli history
.\.venv\Scripts\python.exe -m app.cli recommend
.\.venv\Scripts\python.exe -m app.cli request GET /analytics/ratings
```

`demo` читает локальный `.demo-credentials.json`, входит как демонстрационный администратор,
показывает каталог, записывает **одно новое событие просмотра** и запрашивает историю,
подбор и аналитику. Каждый запуск добавляет одно событие, поэтому общий счётчик растёт.
Пароль и токен в вывод не попадают.

Учётная запись демо-администратора: `demo-admin@example.com`. Случайный пароль находится
в локальном `.demo-credentials.json`. Для Swagger нажмите **Authorize**, в поле `username`
укажите email. Все демо-пользователи имеют один случайный учебный пароль из `.env`.
Создавать собственные независимые учётные записи можно через `/auth/register`.

```powershell
.\.venv\Scripts\python.exe -m app.cli login --email your-email@example.com
.\.venv\Scripts\python.exe -m app.cli request PUT /users/me --json-file examples/profile.json
.\.venv\Scripts\python.exe -m app.cli logout
```

Для создания отдельного администратора:

```powershell
.\.venv\Scripts\python.exe -m app.manage create-admin --email owner@example.com
```

Команда запросит пароль и создаст новую учётную запись. Существующий аккаунт не заменяется.
`.env`, `.demo-credentials.json` и `.cli-session.json` исключены из Git; их не следует
включать в сдаваемый архив. При передаче проекта новый пользователь запускает `init_env.py`.

## Проверки и эксперимент с индексом

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests scripts
.\.venv\Scripts\python.exe -m app.manage benchmark
```

Для экспорта проверяемых материалов при запущенном API:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=output/test-results.xml
.\.venv\Scripts\python.exe scripts\export_evidence.py
```

Экспортируются текущие API-ответы, валидаторы, индексы и итог тестов в `output/`,
а статическая OpenAPI-схема — в `docs/openapi.json`. Пароли и токены не экспортируются.

Интеграционные тесты создают отдельные случайные базы `edge_catalog_test_<uuid>` и удаляют
только эти базы после проверки. Для другого тестового сервера задайте `MONGODB_TEST_URI`.
Тесты без сервера: `python -m pytest -q -m "not integration"`.

Эксперимент сохраняет исходные планы и статистику в `output/benchmark.json`. Он сравнивает
принудительный полный просмотр и индекс `user_recent` на одних данных, пять раз для каждого
пути; индексы не удаляются. Это сравнение путей доступа, а не нагрузочный тест всего API.

В проверенном запуске на 100 000 событиях: **100 000 против 20 просмотренных документов**;
оба запроса вернули одинаковые 20 записей. Нулевые миллисекунды в `explain` означают
ограничение разрешения измерения, а не отсутствие времени выполнения.

## Docker как альтернативный способ запуска

Весь стек и тесты можно запускать внутри Docker. По умолчанию API публикуется на
`127.0.0.1:8001`, а MongoDB — на `127.0.0.1:27018`, поэтому локальный запуск на портах
8000/27017 может работать одновременно. Порты меняются через `API_PORT` и `MONGO_PORT` в `.env`.

```powershell
docker compose up -d --build --wait
docker compose exec api python -m app.manage seed --users 100 --models 60 --interactions 100000
docker compose run --rm tests
docker compose exec api python -m app.manage benchmark
docker compose exec api python -m app.cli demo
docker compose exec api python scripts/export_evidence.py
```

Swagger контейнерной версии: <http://127.0.0.1:8001/docs>.
MongoDB Compass можно подключить к `mongodb://127.0.0.1:27018/`, база `edge_catalog`.
Данные MongoDB сохраняются в именованном томе `bd6_mongo_data`.
Сервисы опубликованы только на `127.0.0.1`; конфигурация предназначена для локальной защиты.
В контейнерном варианте пароль демо хранится внутри контейнера в `.demo-credentials.json`.
Для воспроизводимого пароля seed передаётся `DEMO_PASSWORD` из `.env`.

Результаты тестов, измерений, CLI и экспорта доступны на хосте в `output/docker/`.
Тестовый сервис монтирует каталог `tests/` только для чтения и запускает проверки против
контейнерной MongoDB. После окончания тестовый контейнер удаляется, а временные тестовые
базы очищает сама тестовая фикстура. Рабочая `edge_catalog` тестами не очищается.

Остановить стек с сохранением данных:

```powershell
docker compose stop
```

После пересоздания контейнера API повторите команду seed: учётные записи и события в томе
сохранятся, а локальный файл демо-доступа внутри нового API-контейнера будет восстановлен.

## Документация

Готовый отчёт: `output/doc/Assignment_6_Zhalgasov_Adilbek_CSE-2602M.docx`.
15 страниц на английском, 9 реальных скриншотов локального Compass; в начале указаны
Zhalgasov Adilbek и CSE-2602M. Отдельного титульного листа нет.

- [Схема, запросы, индексы и компромиссы](docs/database.md)
- [Проектное предложение и связь с диссертацией](docs/proposal.md)
- [Описание API и ошибок](docs/api.md)
- [Результаты проверки и сценарий защиты](docs/verification.md)
- [Содержание отчёта по Assignment 6](docs/assignment-report.md)
- [Проверка полного Docker-стека](docs/docker-verification.md)
- [Сопоставление с требованиями Assignment 6](docs/assignment-checklist.md)

Реализация API находится в `app/main.py`, схема MongoDB — в `app/db.py`,
управление данными и эксперимент — в `app/manage.py`.
