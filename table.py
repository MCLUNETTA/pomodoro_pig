"""Загрузка расписания пользователя из Google Calendar.

Весь код, который обращается к Google API и разбирает события календаря
(включая определение активного/неактивного слота), живёт в этом модуле.
`main.py` получает уже готовый список слотов и работает только с ним.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
TOKEN_PATH = BASE_DIR / "token.json"

# Ссылка на нужный календарь. Если пусто — primary календарь аккаунта,
# под которым выполнен вход через OAuth.
# Пример: https://calendar.google.com/calendar/u/0/r?cid=example%40group.calendar.google.com
CALENDAR_URL = ""

SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)

ACTIVE_SLOTS = ("study", "programming")
INACTIVE_SLOTS = (
    "sleep",
    "утро",
    "сборы в колледж",
    "дорога в колледж",
    "обед!!!",
    "дорога до актерского",
    "актерское мастерство",
    "дорога домой",
    "home",
    "night routine",
)

LOOKBACK_DAYS = 1
LOOKAHEAD_DAYS = 2
MAX_EVENTS = 250


class ScheduleError(Exception):
    """Ошибка получения или разбора расписания."""


@dataclass(frozen=True)
class Slot:
    name: str
    start: datetime
    end: datetime
    active: bool

    def key(self):
        return (self.name, self.start.isoformat(), self.end.isoformat())


def normalize_name(name):
    return " ".join(str(name).strip().lower().split())


def classify(name):
    """True — активный слот, False — неактивный, None — неизвестное событие."""
    normalized = normalize_name(name)
    if any(word in normalized for word in ACTIVE_SLOTS):
        return True
    if any(word in normalized for word in INACTIVE_SLOTS):
        return False
    return None


def calendar_id_from_url(url=None):
    """Достаёт id календаря из ссылки Google Calendar."""
    url = CALENDAR_URL if url is None else url
    if not url or not url.strip():
        return "primary"

    raw = url.strip()
    parsed = urlparse(raw)
    query = parse_qs(parsed.query)

    if "cid" in query:
        return unquote(query["cid"][0])

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if "ical" in parts:
        index = parts.index("ical")
        if index + 1 < len(parts):
            return parts[index + 1]

    if "@" in raw and " " not in raw and "/" not in raw:
        return raw

    raise ScheduleError("Не удалось получить id календаря из ссылки: " + raw)


def _import_google():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ScheduleError(
            "Не установлены библиотеки Google API. Выполни: "
            "python -m pip install google-auth google-auth-oauthlib "
            "google-api-python-client"
        ) from exc

    return Request, Credentials, InstalledAppFlow, build


def _validate_credentials_file():
    if not CREDENTIALS_PATH.exists():
        raise ScheduleError(
            "Нет файла credentials.json. Скопируй credentials.example.json "
            "в credentials.json и подставь свои client_id/client_secret "
            "из OAuth-клиента (Desktop app) Google Cloud Console."
        )

    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        client = data.get("installed", data.get("web", {}))
        if "YOUR_" in str(client.get("client_id", "")) or (
            "YOUR_" in str(client.get("client_secret", ""))
        ):
            raise ScheduleError(
                "В credentials.json остались значения-заглушки. "
                "Подставь свои client_id и client_secret из Google Cloud Console."
            )
    except ScheduleError:
        raise
    except Exception:
        # Формат всё равно проверится библиотекой google-auth ниже.
        pass


def _authorize():
    """Авторизуется в аккаунте Google (при первом запуске — через браузер)."""
    _validate_credentials_file()
    Request, Credentials, InstalledAppFlow, _build = _import_google()

    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(TOKEN_PATH), list(SCOPES)
            )
        except Exception:
            creds = None

    if creds is not None and creds.valid:
        return creds

    if creds is not None and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            creds = None

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_PATH), list(SCOPES)
        )
        # Откроется браузер: нужно разрешить доступ к календарю того
        # аккаунта, чьё расписание используется.
        creds = flow.run_local_server(port=0)
    except Exception as exc:
        raise ScheduleError(
            "Не удалось получить доступ к аккаунту Google: " + str(exc)
        ) from exc

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _parse_time(value):
    if not isinstance(value, dict):
        raise ScheduleError("Некорректное время события: " + repr(value))

    if "dateTime" in value:
        text = str(value["dateTime"]).replace("Z", "+00:00")
        return datetime.fromisoformat(text)

    if "date" in value:
        # Событие на весь день начинается в полночь локального времени.
        return datetime.fromisoformat(str(value["date"])).astimezone()

    raise ScheduleError("У события нет dateTime/date: " + repr(value))


def load_slots(now=None):
    """Загружает слоты расписания через Google Calendar API.

    Возвращает список Slot, отсортированный по времени начала.
    """
    _Request, _Credentials, _Flow, build = _import_google()
    creds = _authorize()
    service = build("calendar", "v3", credentials=creds)

    now = now or datetime.now().astimezone()
    time_min = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    time_max = (now + timedelta(days=LOOKAHEAD_DAYS)).isoformat()

    try:
        events = service.events().list(
            calendarId=calendar_id_from_url(),
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=MAX_EVENTS,
        ).execute()
    except Exception as exc:
        raise ScheduleError(
            "Не удалось загрузить события календаря: " + str(exc)
        ) from exc

    slots = []
    for event in events.get("items", ()):
        name = str(event.get("summary", "")).strip()
        active = classify(name)
        if active is None:
            continue

        try:
            start = _parse_time(event.get("start"))
            end = _parse_time(event.get("end"))
        except (ScheduleError, ValueError) as exc:
            raise ScheduleError(
                "Ошибка разбора события «" + name + "»: " + str(exc)
            ) from exc

        if end <= start:
            continue

        slots.append(
            Slot(
                name=name,
                start=start.astimezone(),
                end=end.astimezone(),
                active=active,
            )
        )

    if not slots:
        raise ScheduleError(
            "В календаре не найдено слотов study/programming "
            "или неактивных слотов."
        )

    return sorted(slots, key=lambda slot: slot.start)


def current_slot(slots, now=None):
    """Возвращает слот, в котором находится текущее время, или None."""
    now = now or datetime.now().astimezone()
    for slot in slots:
        if slot.start <= now < slot.end:
            return slot
    return None


def seconds_until_end(slot, now=None):
    now = now or datetime.now().astimezone()
    return max(0, math.ceil((slot.end - now).total_seconds()))


def export_slots(slots, path=None):
    """Сохраняет расписание в CSV, который открывается в Excel.

    Разделитель «;» и BOM UTF-8 нужны, чтобы русские названия и столбцы
    корректно отображались в Excel с русской локалью.
    """
    path = Path(path) if path is not None else BASE_DIR / "schedule.csv"

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(
            ["Название", "Тип", "Начало", "Конец", "Длительность, мин"]
        )

        for slot in slots:
            writer.writerow(
                [
                    slot.name,
                    "активный" if slot.active else "неактивный",
                    slot.start.strftime("%Y-%m-%d %H:%M:%S %z"),
                    slot.end.strftime("%Y-%m-%d %H:%M:%S %z"),
                    round((slot.end - slot.start).total_seconds() / 60, 1),
                ]
            )

    return path
