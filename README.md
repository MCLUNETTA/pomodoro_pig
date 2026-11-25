# Pig Assistant 🐷

Pomodoro-ассистент со свинкой, который работает **по твоему расписанию Google Calendar**.

В обычном режиме приложение само запрашивает доступ к календарю, загружает события,
находит текущий слот и показывает:

- **активный слот** (`study`, `programming`) → свинка сразу бежит, дальше цикл
  **45 минут работы → бег → 15 минут отдыха → бег** до конца слота;
- **неактивный слот** (`sleep`, `утро`, `сборы в колледж`, `дорога в колледж`,
  `обед!!!`, `дорога до актерского`, `актерское мастерство`, `дорога домой`,
  `home`, `night routine`) → спящая свинка с «zZz» и обратный отсчёт до конца слота.

Если расписание получить не удалось, на экране появляется окно
«Не удалось получить расписание: …».

Всё, что связано с Google API и разбором событий, живёт в `table.py`.
`main.py` работает уже с готовым списком слотов.

---

## Быстрый старт

### Вариант A: одной командой (рекомендуется)

```powershell
git clone <ССЫЛКА_НА_РЕПОЗИТОРИЙ> pig_assistant_test
cd pig_assistant_test
python setup.py
```

`setup.py`:

1. проверяет, установлены ли `PySide6`, `google-auth`, `google-auth-oauthlib`,
   `google-api-python-client`;
2. ставит **только недостающие** пакеты с зеркала
   `https://pypi.mirrors.ustc.edu.cn/simple/` (`--trusted-host` уже включён);
3. запускает `main.py`, передавая ему все аргументы.

Тестовый режим без календаря:

```powershell
python setup.py --test
```

### Вариант B: вручную

```powershell
python -m pip install -r requirements.txt
python main.py
```

или с обычного PyPI:

```powershell
python -m pip install PySide6 google-auth google-auth-oauthlib google-api-python-client
python main.py
```

---

## Что запускать

| Команда | Что делает |
| --- | --- |
| `python setup.py` | Проверит/доустановит зависимости с зеркала и запустит обычный режим по расписанию |
| `python setup.py --test` | То же, но тестовый режим: работа → бег → отдых → бег … |
| `python main.py` | Обычный режим, если зависимости уже установлены |
| `python main.py --test` | Тестовый режим, если зависимости уже установлены |

В тестовом режиме при старте спрашиваются две длительности в минутах
(по умолчанию `0.1` и `0.05` — чтобы быстро увидеть всю анимацию). Календарь
в этом режиме не трогается.

В обычном режиме запроса минут нет: внутри активного слота жёстко используются
45 минут работы и 15 минут отдыха. Фазы обрезаются по концу слота.

---

## Как работает приложение

```
Запуск (обычный режим)
  │
  ├─ table.load_slots()  → OAuth → Google Calendar API → список Slot
  │                                      │
  │                                      └─ сохраняется в schedule.csv
  │
  ├─ каждые 10 мин: перезагрузка расписания
  └─ каждую секунду: table.current_slot(slots)
        │
        ├─ активный слот  → бег → Работа 45 → бег → Отдых 15 → бег → … → конец слота
        ├─ неактивный слот → спящая свинка + «название: MM:SS» (или HH:MM:SS)
        └─ слота нет       → «Ожидание слота»
```

Состояния внутри `Assistant`: `idle`, `sleep`, `run`, `work`, `break`.
Таймер обновляется каждые 250 мс, анимация бега — по 16 мс, смена кадров спрайта —
каждые 110 мс.

---

## Структура проекта

| Файл | Назначение |
| --- | --- |
| `main.py` | GUI на PySide6, состояния Pomodoro, анимации, таймеры, окно ошибки |
| `table.py` | **Всё**: OAuth, запросы к Google Calendar API, разбор событий, `Slot`, `export_slots()` |
| `setup.py` | Проверка и установка зависимостей с зеркала + запуск `main.py` |
| `requirements.txt` | Список пакетов для обычного `pip install -r` |
| `credentials.example.json` | Шаблон OAuth-клиента (только заглушки `YOUR_*`) |
| `assets/` | Спрайты свинки, `bell.wav`, `pig_oink.mp3` |
| `schedule.csv` | Сгенерированный файл расписания для просмотра в Excel (создаётся сам) |
| `.gitignore` | Исключает `credentials.json`, `token.json`, `schedule.csv`, `__pycache__` |

---

## Откуда берутся данные: `credentials.json` → расписание

**Важно:** `credentials.json` не содержит расписания. В нём только данные
OAuth-клиента (то есть «кто просит доступ»): `client_id`, `client_secret`,
`project_id`, `auth_uri`, `token_uri`, `redirect_uris`.

### 1. Как получить `credentials.json`

1. Создай проект: https://console.cloud.google.com/projectcreate
2. Включи Calendar API:
   https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
   → **ENABLE**
3. Настрой экран согласия:
   https://console.cloud.google.com/apis/credentials/consent
   - User type → **External** → **Create**
   - App name: `Pig Assistant`, e-mail для поддержки и разработчика — свой
   - **Scopes** → **Add or remove scopes** → галочка
     `https://www.googleapis.com/auth/calendar.readonly` → **UPDATE**
   - **Test users** → добавь **тот же e-mail**, которым будешь входить
     (иначе будет `403: access_denied`)
4. Создай ключ: https://console.cloud.google.com/apis/credentials
   → **+ CREATE CREDENTIALS** → **OAuth client ID** → **Desktop app** → **Create**
5. Скачай JSON (⬇), переименуй в `credentials.json` и положи **в папку проекта
   рядом с `main.py`**.

Можно также скопировать `credentials.example.json` → `credentials.json` и
подставить туда свои `client_id` / `project_id` / `client_secret` из скачанного файла.

### 2. Что происходит при запуске (код в `table.py`)

1. `_validate_credentials_file()` проверяет, что файл есть и в нём не осталось
   заглушек `YOUR_`.
2. `_authorize()`:
   - если есть `token.json` и токен ещё действителен — использует его;
   - если токен истёк — обновляет через `refresh_token` и перезаписывает файл;
   - если токена нет — `InstalledAppFlow.from_client_secrets_file(...)`
     открывает браузер (`run_local_server(port=0)`), ты разрешаешь доступ
     **только на чтение календаря**, результат сохраняется в `token.json`.
3. `build("calendar", "v3", credentials=creds)` создаёт клиент API.
4. `events().list(...)` запрашивает события:
   - `calendarId` — из `CALENDAR_URL` в `table.py`, или `"primary"`, если пусто;
   - `timeMin` = сейчас − 1 день, `timeMax` = сейчас + 2 дня;
   - `singleEvents=True`, `orderBy="startTime"`, `maxResults=250`.
5. У каждого события берётся `summary` и передаётся в `classify()`.
   Совпадение (регистронезависимое, по подстроке) с активными/неактивными
   названиями превращает событие в `Slot(name, start, end, active)`.
   Остальные события игнорируются.
6. Слоты сортируются по времени, сохраняются в `schedule.csv` и отдаются
   в `main.py`.

Если нужен не основной календарь, открой календарь в Google Calendar →
«Настройки и доступ» → скопируй **Calendar ID** или ссылку и вставь в `table.py`:

```python
CALENDAR_URL = "https://calendar.google.com/calendar/u/0/r?cid=example%40group.calendar.google.com"
```

---

## Настройки

| Что менять | Где |
| --- | --- |
| 45 / 15 минут | `WORK_MINUTES`, `BREAK_MINUTES` в `main.py` |
| Список активных/неактивных слотов | `ACTIVE_SLOTS`, `INACTIVE_SLOTS` в `table.py` |
| Конкретный календарь | `CALENDAR_URL` в `table.py` |
| Диапазон загрузки событий | `LOOKBACK_DAYS`, `LOOKAHEAD_DAYS`, `MAX_EVENTS` в `table.py` |
| Частота обновления расписания | `SCHEDULE_RELOAD_MS` в `main.py` (по умолчанию 10 мин) |

---

## Решение проблем

| Симптом | Что делать |
| --- | --- |
| `403: access_denied`, «проверено только одобренными тестировщиками» | Добавь свой e-mail в **Test users** экрана согласия и выбери именно этот аккаунт в браузере |
| «Нет файла credentials.json» | Скачай OAuth-клиент (Desktop app) и положи файл рядом с `main.py` |
| «В credentials.json остались заглушки» | Замени `YOUR_CLIENT_ID` / `YOUR_CLIENT_SECRET` на реальные значения |
| «Не установлены библиотеки Google API» | `python setup.py` или `python -m pip install -r requirements.txt` |
| «В календаре не найдено слотов…» | Проверь названия событий и списки в `table.py`; поиск идёт по подстроке без учёта регистра |
| «Не удалось получить id календаря из ссылки» | Вставь Calendar ID вместо полной ссылки в `CALENDAR_URL` |
| Зеркало не скачивает пакеты | Зеркало нужно только для pip; сами Google API должны быть доступны напрямую (возможно, нужен прокси) |
| Нет звука колокольчика | `bell.wav` воспроизводится через `winsound` только на Windows; хрюканье — через Qt на любой ОС |

---

## Безопасность

- `credentials.json` и `token.json` содержат секреты аккаунта — они **не должны**
  попадать в репозиторий. Они уже добавлены в `.gitignore`.
- `credentials.example.json` должен оставаться только с заглушками `YOUR_*`.
- Если `client_secret` когда-либо был опубликован, сбрось его:
  https://console.cloud.google.com/apis/credentials → OAuth-клиент →
  **EDIT OAuth client** → **RESET SECRET**, затем удали `token.json` и
  авторизуйся заново.
- Проверить перед коммитом можно так:

  ```powershell
  git status --ignored
  ```

---

## Публикация на GitHub

```powershell
git init
git add .
git commit -m "Initial release: schedule-aware pig pomodoro"
git remote add origin https://github.com/<ТВОЙ_ЛОГИН>/<РЕПОЗИТОРИЙ>.git
git branch -M main
git push -u origin main
```

Перед `git add .` убедись, что реальных `credentials.json` и `token.json`
в папке нет (или они проигнорированы). Если репозиторий уже инициализирован,
первые три команды (`git init` / `git add` / `git commit`) можно пропустить.
После клонирования пользователю достаточно `python setup.py`
(или `python setup.py --test`) и OAuth-ключа по инструкции выше.

> Приложение находится в режиме **Testing**, поэтому вход разрешён только
> тестировщикам, добавленным на экране согласия. Для личного пользования
> публикация в Production не нужна.
