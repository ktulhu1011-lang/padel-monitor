#!/usr/bin/env python3
"""
Проверка слотов падел-кортов на russpass.ru — запускается GitHub Actions.
Состояние хранится в slots_state.json (коммитится в репо).

Переменные окружения:
    TG_TOKEN            — токен бота
    TG_CHAT_IDS         — получатели по Матвеевской, через запятую
    TG_CHAT_IDS_VNUKOVO — получатели по Внуково, через запятую
"""

import json
import os
import uuid
import warnings
from datetime import datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings()
warnings.filterwarnings("ignore")

STATE_FILE = "slots_state.json"
TG_TOKEN = os.environ["TG_TOKEN"]

EVENTS = [
    {
        "id": "69f3df933984161967fbdf2b",
        "name": "Матвеевская (Очаково)",
        "chat_env": "TG_CHAT_IDS",
    },
    {
        "id": "6a68b0643916173f30907ce7",
        "name": "Внуково",
        "chat_env": "TG_CHAT_IDS_VNUKOVO",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://russpass.ru/",
    "Origin": "https://russpass.ru",
    "Accept": "application/json",
}

DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def is_interesting(date_str: str, time_start: str) -> bool:
    """Выходные целиком + будни с 19:00."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = dt.weekday()  # 0=пн, 5=сб, 6=вс
    hour = int(time_start.split(":")[0])
    return weekday >= 5 or (weekday < 5 and hour >= 19)


def fetch_sessions(event_id: str) -> dict:
    """Слоты события. Бросает исключение — вызывающий сам решает что делать."""
    start = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    end = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%dT23:59:59")
    r = requests.get(
        f"https://api.russpass.ru/events/portal/v1/events/{event_id}/schedule",
        params={"startDate": start, "endDate": end},
        headers={**HEADERS, "rqid": str(uuid.uuid4())},
        verify=False,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    sessions = {}
    for day in data.get("dates", []):
        date = day.get("date", "")
        for s in day.get("sessions", []):
            if not s.get("isActive"):
                continue
            start_time = s["time"]["start"]
            if not is_interesting(date, start_time):
                continue
            ext = json.loads(s["sessionExtendedId"])
            pid = str(ext["performanceId"])
            sessions[pid] = {
                "date": date,
                "start": start_time,
                "end": s["time"]["end"],
                "tickets": s.get("availableTicketsCount", 0),
            }
    return sessions


def send_telegram(text: str, chat_ids: list):
    for chat_id in chat_ids:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )


def load_state() -> dict:
    """Состояние: {event_id: {performanceId: {...}}}."""
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        state = json.load(f)
    # Миграция старого плоского формата (только Матвеевская)
    if state and all(isinstance(v, dict) and "date" in v for v in state.values()):
        return {EVENTS[0]["id"]: state}
    return state


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def format_slots(sessions: dict) -> str:
    lines = []
    for s in sorted(sessions.values(), key=lambda x: (x["date"], x["start"])):
        day = DAYS[datetime.strptime(s["date"], "%Y-%m-%d").weekday()]
        lines.append(f"📅 {s['date']} ({day})  {s['start']}–{s['end']}  (билетов: {s['tickets']})")
    return "\n".join(lines)


def main():
    state = load_state()

    for event in EVENTS:
        eid, name = event["id"], event["name"]
        chat_ids = [c.strip() for c in os.environ.get(event["chat_env"], "").split(",") if c.strip()]

        if not chat_ids:
            print(f"[{name}] ⚠️  Секрет {event['chat_env']} не задан — пропускаю")
            continue

        try:
            current = fetch_sessions(eid)
        except Exception as e:
            # Слоты ещё не выложены (500) или сеть моргнула — состояние НЕ трогаем,
            # иначе после восстановления прилетит спам "все слоты новые".
            print(f"[{name}] нет расписания: {e}")
            continue

        known = state.get(eid, {})
        new = {k: v for k, v in current.items() if k not in known}

        if new:
            text = (
                f"🎾 <b>Новые слоты — {name}</b>\n\n"
                f"{format_slots(new)}\n\n"
                f"<a href='https://russpass.ru/event/{eid}'>Забронировать →</a>"
            )
            send_telegram(text, chat_ids)
            print(f"[{name}] отправлено: {len(new)} новых слотов")
        else:
            print(f"[{name}] без изменений, интересных слотов: {len(current)}")

        state[eid] = current

    save_state(state)


if __name__ == "__main__":
    main()
